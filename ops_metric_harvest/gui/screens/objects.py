"""Object selection screen. The shell uses only this contract, so the screen can be replaced.

Methods: load(group), value() -> ObjectSelector, group_name(), set_kinds(kinds),
show_matches(resources), clear_preview(), set_status(text).
Signals: scopeChanged (committed adapter or resource kind change),
kindsRequested(adapter_kind), previewRequested(selector).
"""
from copy import deepcopy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton
from ops_metric_harvest.models import ObjectSelector
from ops_metric_harvest.starter_metrics import DEFAULT_RESOURCE_KINDS
from .common import Page, PathPicker, combo


class ObjectsPage(Page):
    scopeChanged = Signal()
    kindsRequested = Signal(str)
    previewRequested = Signal(object)

    def __init__(self):
        super().__init__("Select objects", "Configure the current collection group. CSV accepts object names or resource IDs, with an optional resource kind column.")
        self.name = QLineEdit()
        self.kind = combo(DEFAULT_RESOURCE_KINDS, editable=True)
        self.adapter = QLineEdit("VMWARE")
        self.mode = combo(["All", "Filter by name", "Import CSV", "Explicit names / IDs"])
        self.query = QLineEdit()
        self.csv = PathPicker("Import objects", file_filter="CSV (*.csv);;All files (*)")
        self.names = QPlainTextEdit()
        self.ids = QPlainTextEdit()
        self.names.setMaximumHeight(90)
        self.ids.setMaximumHeight(90)
        self.preview = QPushButton("Preview matching objects")
        self.refresh = QPushButton("Refresh resource kinds")
        self.matches = QPlainTextEdit()
        self.matches.setReadOnly(True)
        self.matches.setMaximumHeight(180)
        for label, widget in [("Group name:", self.name), ("Resource kind:", self.kind),
                              ("Adapter kind:", self.adapter), ("", self.refresh), ("Selection:", self.mode),
                              ("Name contains:", self.query), ("CSV file:", self.csv),
                              ("Names (one per line):", self.names), ("IDs (one per line):", self.ids),
                              ("", self.preview), ("Preview:", self.matches)]:
            self.form.addRow(label, widget)
        self._selector = ObjectSelector("VirtualMachine")
        self._loading = False
        self._scope = self._current_scope()
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.kind.currentIndexChanged.connect(self.commit_scope)
        self.kind.lineEdit().editingFinished.connect(self.commit_scope)
        self.adapter.editingFinished.connect(self.commit_scope)
        self.refresh.clicked.connect(lambda: self.kindsRequested.emit(self.value().adapter_kind))
        self.preview.clicked.connect(lambda: self.previewRequested.emit(self.value()))
        self.csv.edit.textChanged.connect(self.clear_embedded_csv)
        self.update_fields()

    def _current_scope(self):
        return (self.adapter.text().strip() or "VMWARE", self.kind.currentText().strip())

    def commit_scope(self):
        scope = self._current_scope()
        if not self._loading and scope != self._scope:
            self._scope = scope
            self.scopeChanged.emit()

    def group_name(self):
        return self.name.text().strip()

    def clear_preview(self):
        self.matches.clear()
        self.status.clear()

    def clear_embedded_csv(self):
        self._selector.csv_content = None

    def update_fields(self):
        mode = self.mode.currentIndex()
        for widget, visible in [(self.query, mode == 1), (self.csv, mode == 2),
                                (self.names, mode == 3), (self.ids, mode == 3)]:
            self.form.setRowVisible(widget, visible)
        self.preview.setEnabled(mode in (0, 1))

    def value(self):
        selector = deepcopy(self._selector)
        selector.resource_kind = self.kind.currentText().strip()
        selector.adapter_kind = self.adapter.text().strip() or "VMWARE"
        selector.selection_mode = ["all", "search", "imported", "explicit"][self.mode.currentIndex()]
        selector.search_query = self.query.text().strip() or None
        selector.csv_path = self.csv.edit.text().strip() or None
        selector.names = [s.strip() for s in self.names.toPlainText().splitlines() if s.strip()]
        selector.resource_ids = [s.strip() for s in self.ids.toPlainText().splitlines() if s.strip()]
        return selector

    def load(self, group):
        self._loading = True
        self.name.setText(group.name)
        self.kind.setCurrentText(group.resource_kind)
        self.adapter.setText(group.selector.adapter_kind or "VMWARE")
        self.mode.setCurrentIndex(["all", "search", "imported", "explicit"].index(group.selector.selection_mode))
        self.query.setText(group.selector.search_query or "")
        self.csv.edit.setText(group.selector.csv_path or "")
        self._selector = deepcopy(group.selector)
        self.names.setPlainText("\n".join(group.selector.names))
        self.ids.setPlainText("\n".join(group.selector.resource_ids))
        self.matches.clear()
        self.status.setText("Embedded CSV loaded from profile." if group.selector.csv_content else "")
        self._scope = self._current_scope()
        self._loading = False

    def set_kinds(self, kinds):
        current = self.kind.currentText()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItems(list(dict.fromkeys([*DEFAULT_RESOURCE_KINDS, *kinds])))
        self.kind.setCurrentText(current)
        self.kind.blockSignals(False)
        self.status.setText(f"{len(kinds)} resource kinds available.")

    def show_matches(self, resources):
        self.matches.setPlainText("\n".join(f"{r['name']}   {r['resourceId']}" for r in resources))
        self.status.setText(f"{len(resources)} objects in preview (limited to 200). Collection resolves the full selection.")
