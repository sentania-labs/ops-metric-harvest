"""Versioned profile controls. Persistence remains in the shared profile module."""
from PySide6.QtWidgets import QLineEdit, QPushButton
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
