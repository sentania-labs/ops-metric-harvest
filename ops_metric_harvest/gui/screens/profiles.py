"""Versioned profile controls. Persistence remains in the shared profile module."""
from PySide6.QtWidgets import QLineEdit, QPushButton, QLabel
from .common import Page


class ProfilesPage(Page):
    def __init__(self):
        super().__init__("Collection profiles", "Load or save versioned JSON profiles shared with the CLI. Passwords and tokens are never saved; loading clears current credentials.")
        self.name = QLineEdit("Metrics collection")
        self.load_button = QPushButton("Load profile…")
        self.save_button = QPushButton("Save profile…")
        self.form.addRow("Job name:", self.name)
        self.form.addRow(self.load_button)
        self.form.addRow(self.save_button)
        explanation = QLabel("Profiles save every group, selector, field, time range and export setting. Fixed IDs are reused on every run. Dynamic type/filter selections are resolved again and may include newly discovered objects. No credentials are saved.")
        explanation.setWordWrap(True)
        self.form.addRow(explanation)
