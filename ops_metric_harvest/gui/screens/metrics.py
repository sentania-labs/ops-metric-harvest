"""Metric catalogue and selection screen, independent of the shell."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QPushButton
from ops_metric_harvest.models import MetricSet
from ops_metric_harvest.starter_metrics import STARTER_METRIC_SETS
from .common import Page


class MetricsPage(Page):
    def __init__(self):
        super().__init__("Select metrics", "Filter the catalogue and check metrics for the current group. Selected metrics remain selected when filtered.")
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by metric key or display name")
        self.refresh = QPushButton("Load catalogue")
        self.starters = QPushButton("Select starter metrics")
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("Metric keys, separated by commas")
        self.add = QPushButton("Add metric keys")
        for label, widget in [("Filter:", self.filter), ("", self.refresh), ("", self.starters),
                              ("Metrics:", self.list), ("Manual keys:", self.manual), ("", self.add)]:
            self.form.addRow(label, widget)
        self.catalogue = {}
        self.kind = "VirtualMachine"
        self.filter.textChanged.connect(self.apply_filter)
        self.starters.clicked.connect(self.select_starters)
        self.add.clicked.connect(self.add_manual)
        self.list.itemChanged.connect(self.update_count)

    def value(self):
        keys = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]
        return MetricSet(keys, {k: dict(self.catalogue.get(k, {})) for k in keys})

    def load(self, metric_set, kind):
        self.kind = kind
        self.catalogue = dict(metric_set.metadata)
        self.set_catalogue(self.catalogue, metric_set.stat_keys)

    def set_catalogue(self, catalogue, selected=None):
        selected = self.value().stat_keys if selected is None else selected
        self.catalogue = {k: self.catalogue.get(k, {}) for k in selected}
        self.catalogue.update(catalogue)
        self.list.clear()
        for key in sorted(set(self.catalogue) | set(selected)):
            meta = self.catalogue.get(key, {})
            item = QListWidgetItem(f"{meta.get('name', key)}  [{meta.get('unit', '')}]  {key}")
            item.setData(Qt.UserRole, key)
            item.setToolTip(meta.get("description", key))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
            self.list.addItem(item)
        self.apply_filter()
        self.update_count()

    def select_starters(self):
        starters = {m["key"]: m for m in STARTER_METRIC_SETS.get(self.kind, [])}
        selected = list(dict.fromkeys([*self.value().stat_keys, *starters]))
        self.set_catalogue({**self.catalogue, **starters}, selected)

    def add_manual(self):
        keys = [key.strip() for key in self.manual.text().split(",") if key.strip()]
        self.set_catalogue(self.catalogue, list(dict.fromkeys([*self.value().stat_keys, *keys])))
        self.manual.clear()

    def apply_filter(self):
        query = self.filter.text().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(query not in item.text().casefold())

    def update_count(self):
        self.status.setText(f"{len(self.value().stat_keys)} metrics selected")
