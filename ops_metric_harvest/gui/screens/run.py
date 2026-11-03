"""Run progress, cancellation, and bounded results preview."""
from PySide6.QtWidgets import QPushButton, QProgressBar, QPlainTextEdit, QTableWidget, QTableWidgetItem
from .common import Page
from .objects import button_row


class RunPage(Page):
    def __init__(self):
        super().__init__("Run collection", "Review the scope, then collect. Cancellation takes effect between requests; an in-flight request may finish first.")
        self.form.setSpacing(8)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFixedHeight(110)
        self.refresh_counts = QPushButton("Refresh object counts")
        self.start = QPushButton("Start collection")
        self.start.setProperty("variant", "primary")
        self.cancel = QPushButton("Cancel collection")
        self.cancel.setEnabled(False)
        self.progress = QProgressBar()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(90)
        self.table = QTableWidget(0, 6)
        self.table.setMinimumHeight(180)
        self.table.setMaximumHeight(220)
        self.table.setHorizontalHeaderLabels(["Object", "Field", "Type / time basis", "Time (UTC)", "Value", "Unit"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for widget in (self.summary, button_row(self.refresh_counts, self.start, self.cancel), self.progress, self.log, self.table):
            self.form.addRow(widget)
        self.result = None
        self.files = []

    def begin(self):
        self.result = None
        self.files = []
        self.table.setRowCount(0)
        self.log.clear()
        self.status.setText("Collecting…")
        self.progress.setRange(0, 0)

    def report_progress(self, message, done, total):
        self.log.appendPlainText(message)
        self.progress.setRange(0, total if total > 0 else 0)
        self.progress.setValue(done)

    def show_result(self, payload):
        result, files, export_errors = payload
        self.result, self.files = result, files
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        text = (f"{result.status.capitalize()}: {len(result.samples)} samples, "
                f"{len(result.resolved_resources)} objects, {len(result.warnings)} warnings, "
                f"{len(result.errors)} collection errors. {len(files)} files saved.")
        if export_errors:
            text += f" {len(export_errors)} export errors."
        self.status.setText(text)
        for message in [*result.warnings, *(str(e) for e in result.errors), *export_errors, *files]:
            self.log.appendPlainText(message)
        samples = result.samples[:200]
        self.table.setRowCount(len(samples))
        for row, sample in enumerate(samples):
            for col, value in enumerate((sample.resource_name, sample.metric_key, f"{sample.field_type} / {sample.timestamp_basis}", sample.time_utc, sample.value, sample.unit)):
                self.table.setItem(row, col, QTableWidgetItem("Missing" if value is None else str(value)))
        self.table.resizeColumnsToContents()
