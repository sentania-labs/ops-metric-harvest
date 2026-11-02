"""Native application entry point and deterministic headless screenshot smoke."""
import sys
from pathlib import Path


def run_gui(theme="light", screenshot=None):
    from PySide6.QtCore import QTimer, QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("VCF Operations Metrics Explorer")
    app.setOrganizationName("sentania-labs")
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        # Hide only the console created for an Explorer launch. A caller's terminal
        # belongs to the caller and must remain visible for CLI use.
        import ctypes
        kernel = ctypes.windll.kernel32
        processes = (ctypes.c_ulong * 2)()
        if kernel.GetConsoleProcessList(processes, 2) == 1:
            kernel.GetConsoleWindow.restype = ctypes.c_void_p
            ctypes.windll.user32.ShowWindow.argtypes = (ctypes.c_void_p, ctypes.c_int)
            ctypes.windll.user32.ShowWindow(kernel.GetConsoleWindow(), 0)
    window = MainWindow(theme=theme)
    window.show()
    if screenshot:
        def capture():
            path = Path(screenshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = window.grab().save(str(path))
            app.exit(0 if ok else 1)
        QTimer.singleShot(500, capture)
    try:
        return app.exec()
    finally:
        # Destroy the window tree while QApplication is still alive. Python signal
        # closures can otherwise keep widgets alive until interpreter teardown.
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
