"""Vendored Lattice QSS and palette, applied together with Fusion."""
import json
from pathlib import Path
from PySide6.QtGui import QColor, QPalette

ASSETS = Path(__file__).parent / "assets"


def apply_theme(app, theme="light"):
    app.setStyle("Fusion")
    palette = QPalette()
    colors = json.loads((ASSETS / "lattice-palette.json").read_text())[theme]
    for group, roles in colors.items():
        for name, color in roles.items():
            role = getattr(QPalette.ColorRole, name, None)
            if role is not None:
                palette.setColor(getattr(QPalette.ColorGroup, group), role, QColor(color))
    app.setPalette(palette)
    filename = "lattice.qss" if theme == "light" else "lattice-dark.qss"
    app.setStyleSheet((ASSETS / filename).read_text())
