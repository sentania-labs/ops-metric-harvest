"""Connection form. Secrets are only present in runtime snapshots."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QCheckBox, QPushButton, QLabel
from .common import Page, PathPicker, combo


class ConnectionPage(Page):
    changed = Signal()

    def __init__(self):
        super().__init__("Connect to VCF Operations", "Connect to discover inventory and metrics. Credentials stay in memory and are excluded from profiles.")
        self.server = QLineEdit()
        self.server.setPlaceholderText("https://vcf-ops.example.com")
        self.auth = combo(["Username & Password", "OpsToken"])
        self.source = combo(["Local"], editable=True)
        self.source.setToolTip("Where the account lives: Local, or a directory or SSO source configured in VCF Operations")
        self.sources = QPushButton("Refresh login sources")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.ca = PathPicker("Trusted CA bundle", file_filter="Certificates (*.pem *.crt);;All files (*)")
        self.insecure = QCheckBox("Ignore SSL validation")
        self.test = QPushButton("Test connection")
        self.test.setProperty("variant", "primary")
        for label, widget in [("VCF Operations URL:", self.server), ("Authentication:", self.auth),
                              ("Login Source:", self.source), ("", self.sources), ("Username:", self.username),
                              ("Login password:", self.password), ("OpsToken:", self.token),
                              ("Trusted CA bundle:", self.ca), ("", self.insecure), ("", self.test)]:
            self.form.addRow(label, widget)
        self.warning = QLabel("Warning: server identity will not be verified. Use only for a trusted lab.")
        self.warning.setWordWrap(True)
        self.warning.setProperty("lattice", "banner")
        self.warning.setProperty("status", "warn")
        self.form.insertRow(self.form.rowCount()-1, self.warning)
        self.insecure.toggled.connect(self.update_fields)
        self.auth.currentIndexChanged.connect(self.update_fields)
        for field in (self.server, self.username, self.password, self.token, self.ca.edit):
            field.textChanged.connect(self.invalidate)
        self.source.currentTextChanged.connect(self.invalidate)
        self.auth.currentIndexChanged.connect(self.invalidate)
        self.insecure.toggled.connect(self.invalidate)
        self.extra = {}
        self.update_fields()
        self.invalidate()

    def update_fields(self):
        token = self.auth.currentIndex() == 1
        for widget in (self.source, self.sources, self.username, self.password):
            self.form.setRowVisible(widget, not token)
        self.form.setRowVisible(self.token, token)
        self.form.setRowVisible(self.warning, self.insecure.isChecked())
        self.ca.setEnabled(not self.insecure.isChecked())

    def invalidate(self):
        self.status.setText("Status: Not checked")
        self.changed.emit()

    def value(self, secrets=False):
        data = dict(self.extra)
        data.update(server=self.server.text().strip(), auth_type="token" if self.auth.currentIndex() else "basic",
                    username=self.username.text().strip(), auth_source=self.source.currentText().strip(),
                    verify_ssl=not self.insecure.isChecked(), ca_bundle=self.ca.edit.text().strip())
        if secrets:
            data.update(password=self.password.text(), token=self.token.text().strip())
        return data

    def load(self, data):
        self.extra = {k: v for k, v in data.items() if k not in ("password", "token", "Authorization")}
        self.password.clear()
        self.token.clear()
        self.server.setText(data.get("server", ""))
        self.auth.setCurrentIndex(int(data.get("auth_type") == "token"))
        self.username.setText(data.get("username") or "")
        self.source.setCurrentText(data.get("auth_source") or "Local")
        self.ca.edit.setText(data.get("ca_bundle") or "")
        self.insecure.setChecked(not data.get("verify_ssl", True))
        self.invalidate()

    def set_sources(self, sources):
        current = self.source.currentText()
        self.source.clear()
        self.source.addItems(list(dict.fromkeys(["Local", *sources])))
        self.source.setCurrentText(current)
