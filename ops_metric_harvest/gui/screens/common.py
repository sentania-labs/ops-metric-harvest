"""Small shared widget constructors."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QFileDialog, QComboBox,
)


def combo(items, editable=False):
    widget = QComboBox()
    widget.addItems(items)
    widget.setEditable(editable)
    return widget


class Page(QWidget):
    def __init__(self, title, description):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 20, 24, 20)
        self.layout.setSpacing(16)
        heading = QLabel(title)
        heading.setProperty("lattice", "page-title")
        self.layout.addWidget(heading)
        caption = QLabel(description)
        caption.setWordWrap(True)
        caption.setProperty("lattice", "muted")
        self.layout.addWidget(caption)
        self.card = QFrame()
        self.card.setProperty("lattice", "card")
        self.form = QFormLayout(self.card)
        self.form.setContentsMargins(16, 16, 16, 16)
        self.form.setSpacing(12)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.layout.addWidget(self.card)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    def set_status(self, text):
        self.status.setText(text)


class PathPicker(QWidget):
    def __init__(self, title, directory=False, file_filter="All files (*)"):
        super().__init__()
        self.title, self.directory, self.file_filter = title, directory, file_filter
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.browse = QPushButton("Browse…")
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse)
        self.browse.clicked.connect(self.choose)

    def choose(self):
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, self.title, self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.title, self.edit.text(), self.file_filter)
        if path:
            self.edit.setText(path)
