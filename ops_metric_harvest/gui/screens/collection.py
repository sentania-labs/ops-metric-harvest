"""Collection and export settings; no collection semantics live here."""
from pathlib import Path
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QLineEdit, QSpinBox, QDateTimeEdit, QCheckBox, QWidget, QHBoxLayout
from ops_metric_harvest.models import TimeRange
from .common import Page, PathPicker, combo


class CollectionPage(Page):
    def __init__(self):
        super().__init__("Collection settings", "Choose a historical sample range or the latest N samples per metric, then the export formats and destination.")
        self.mode = combo(["Relative range", "Absolute range (UTC)", "Latest N samples"])
        self.relative = combo(["1h", "12h", "1d", "7d", "30d"], editable=True)
        self.relative.setCurrentText("7d")
        self.start = QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(-7))
        self.end = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        for widget in (self.start, self.end):
            widget.setTimeSpec(Qt.UTC)
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss 'UTC'")
        self.latest = QSpinBox()
        self.latest.setRange(1, 1000000)
        self.latest.setValue(10)
        self.interval = QSpinBox()
        self.interval.setRange(1, 1000000)
        self.interval.setValue(5)
        self.interval_type = combo(["MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS", "YEARS", "NONE"])
        self.rollup = combo(["AVG", "SUM", "MIN", "MAX", "NONE", "LATEST", "COUNT"])
        self.output = PathPicker("Output folder", directory=True)
        self.output.edit.setText(str(Path.home() / "Documents"))
        self.timezone = QLineEdit("America/Chicago")
        self.formats = {}
        formats_row = QWidget()
        row = QHBoxLayout(formats_row)
        row.setContentsMargins(0, 0, 0, 0)
        for key, label in [("csv", "CSV (long)"), ("csv_wide", "CSV (wide)"), ("xlsx", "Excel"), ("json", "JSON"), ("table", "Text table")]:
            check = QCheckBox(label)
            check.setChecked(key in ("csv", "xlsx"))
            self.formats[key] = check
            row.addWidget(check)
        for label, widget in [("Sample mode:", self.mode), ("Relative range:", self.relative),
                              ("Start:", self.start), ("End:", self.end), ("Latest samples:", self.latest),
                              ("Interval:", self.interval), ("Interval unit:", self.interval_type),
                              ("Rollup:", self.rollup), ("Formats:", formats_row),
                              ("Output folder:", self.output), ("Export timezone:", self.timezone)]:
            self.form.addRow(label, widget)
        self.extra = {}
        self._range = TimeRange()
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        mode = self.mode.currentIndex()
        for widget, visible in [(self.relative, mode == 0), (self.start, mode == 1),
                                (self.end, mode == 1), (self.latest, mode == 2)]:
            self.form.setRowVisible(widget, visible)
        for widget in (self.interval, self.interval_type, self.rollup):
            widget.setEnabled(mode != 2)

    def value(self):
        mode = self.mode.currentIndex()
        data = self._range.to_dict()
        data.update(mode="absolute" if mode == 1 else "relative",
                    relative_preset=self.relative.currentText(),
                    interval_minutes=self.interval.value(), interval_type=self.interval_type.currentText(),
                    rollup_type=self.rollup.currentText(), max_samples=self.latest.value() if mode == 2 else None)
        if mode == 1:
            data.update(start_time=self.start.dateTime().toUTC().toString(Qt.ISODate),
                        end_time=self.end.dateTime().toUTC().toString(Qt.ISODate))
        time_range = TimeRange.from_dict(data)
        config = dict(self.extra)
        config.update(formats=[key for key, check in self.formats.items() if check.isChecked()],
                      output_dir=self.output.edit.text().strip(), timezone=self.timezone.text().strip())
        return time_range, config

    def load(self, time_range, config):
        self._range = TimeRange.from_dict(time_range.to_dict())
        self.relative.setCurrentText(time_range.relative_preset)
        for widget, value in [(self.start, time_range.start_time), (self.end, time_range.end_time)]:
            if value:
                dt = QDateTime.fromString(value, Qt.ISODate)
                if not dt.isValid():
                    raise ValueError("Profile contains an invalid absolute timestamp")
                widget.setDateTime(dt.toUTC())
        self.interval.setValue(time_range.interval_minutes)
        self.interval_type.setCurrentText(time_range.interval_type)
        self.rollup.setCurrentText(time_range.rollup_type)
        self.latest.setValue(time_range.max_samples or 10)
        self.mode.setCurrentIndex(1 if time_range.mode == "absolute" else 2 if time_range.max_samples else 0)
        self.extra = dict(config)
        self.output.edit.setText(config.get("output_dir") or str(Path.home() / "Documents"))
        self.timezone.setText(config.get("timezone", "America/Chicago"))
        formats = config.get("formats", ["csv", "xlsx"])
        for key, check in self.formats.items():
            check.setChecked(key in formats)
