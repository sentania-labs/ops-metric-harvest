"""Scoped field picker. load/value/set_catalogue/set_status; catalogueRequested signal.

A MetricSet contains independent metric and property namespaces. The shell loads
one collection group's adapter/kind scope at a time.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTabWidget, QLabel
from ops_metric_harvest.models import MetricSet
from ops_metric_harvest.starter_metrics import STARTER_METRIC_SETS
from .common import Page
from .objects import button_row


class MetricsPage(Page):
    catalogueRequested = Signal()

    def __init__(self):
        super().__init__("Select fields", "Fields apply only to this collection group's adapter and type. Catalogue availability does not guarantee data on every object.")
        self.layout.setContentsMargins(24, 10, 24, 10)
        self.layout.setSpacing(8)
        self.form.setSpacing(8)
        self.scope = QLabel()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search key, name, unit or description")
        self.refresh = QPushButton("Load live catalogue")
        self.starters = QPushButton("Starter metrics")
        self.tabs = QTabWidget()
        self.list = QListWidget()
        self.properties = QListWidget()
        self.tabs.addTab(self.list, "Metrics")
        self.tabs.addTab(self.properties, "Properties · latest")
        self.tabs.setFixedHeight(200)
        self.property_status = QLabel("Properties are current values; timestamps record collection time, independent of the metric range.")
        self.property_status.setWordWrap(True)
        self.basket = QListWidget()
        self.basket.setFixedHeight(85)
        self.remove = QPushButton("Remove selected field")
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("Optional raw metric keys, comma separated")
        self.add = QPushButton("Add keys")
        for label, widget in [("Scope:", self.scope), ("Search:", self.filter),
                              ("", button_row(self.refresh, self.starters)), ("", self.tabs),
                              ("", self.property_status), ("Selected:", button_row(self.basket, self.remove)),
                              ("Fallback:", button_row(self.manual, self.add))]:
            self.form.addRow(label, widget)
        self.catalogue = {}
        self.property_catalogue = {}
        self.kind = "VirtualMachine"
        self.filter.textChanged.connect(self.apply_filter)
        self.starters.clicked.connect(self.select_starters)
        self.add.clicked.connect(self.add_manual)
        self.list.itemChanged.connect(self.update_count)
        self.properties.itemChanged.connect(self.update_count)
        self.refresh.clicked.connect(self.catalogueRequested)
        self.remove.clicked.connect(self.remove_field)

    @staticmethod
    def selected(widget):
        return [widget.item(i).data(Qt.UserRole) for i in range(widget.count())
                if widget.item(i).checkState() == Qt.Checked]

    def value(self):
        keys, props = self.selected(self.list), self.selected(self.properties)
        return MetricSet(keys, {k: dict(self.catalogue.get(k, {})) for k in keys},
                         props, {k: dict(self.property_catalogue.get(k, {})) for k in props})

    def load(self, metric_set, kind):
        self.kind = kind
        self.scope.setText(kind)
        self.catalogue = dict(metric_set.metadata)
        self.property_catalogue = dict(metric_set.property_metadata)
        self.set_catalogue(self.catalogue, metric_set.stat_keys)
        self.set_properties(self.property_catalogue, metric_set.property_keys)

    def populate(self, widget, catalogue, selected):
        widget.blockSignals(True)
        widget.clear()
        category = None
        for key in sorted(set(catalogue) | set(selected)):
            group = key.split('|')[0]
            if group != category:
                heading = QListWidgetItem(group.upper())
                heading.setFlags(Qt.NoItemFlags)
                widget.addItem(heading)
                category = group
            meta = catalogue.get(key, {})
            item = QListWidgetItem(f"{meta.get('name', key)}  [{meta.get('unit') or 'no unit'}]\n{key}  ·  {meta.get('description', '')}")
            item.setData(Qt.UserRole, key)
            item.setToolTip(meta.get("description", key))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
            widget.addItem(item)
        widget.blockSignals(False)
        self.apply_filter()
        self.update_count()

    def set_catalogue(self, catalogue, selected=None):
        selected = self.value().stat_keys if selected is None else selected
        self.catalogue = {k: self.catalogue.get(k, {}) for k in selected}
        self.catalogue.update(catalogue)
        self.populate(self.list, self.catalogue, selected)

    def set_properties(self, catalogue, selected=None, error=None):
        selected = self.value().property_keys if selected is None else selected
        self.property_catalogue = {k: self.property_catalogue.get(k, {}) for k in selected}
        self.property_catalogue.update(catalogue)
        self.populate(self.properties, self.property_catalogue, selected)
        self.tabs.setTabEnabled(1, not error)
        self.property_status.setText(f"Properties unavailable: {error}" if error else
                                    "Properties are latest values. Timestamps record collection time, independent of the metric range.")

    def select_starters(self):
        starters = {m["key"]: m for m in STARTER_METRIC_SETS.get(self.kind, [])}
        self.set_catalogue({**self.catalogue, **starters}, list(dict.fromkeys([*self.value().stat_keys, *starters])))

    def add_manual(self):
        keys = [key.strip() for key in self.manual.text().split(",") if key.strip()]
        self.set_catalogue(self.catalogue, list(dict.fromkeys([*self.value().stat_keys, *keys])))
        self.manual.clear()

    def apply_filter(self):
        query = self.filter.text().casefold()
        for widget in (self.list, self.properties):
            heading = None
            visible = False
            for index in range(widget.count()):
                item = widget.item(index)
                if not item.data(Qt.UserRole):
                    if heading:
                        heading.setHidden(not visible)
                    heading, visible = item, False
                else:
                    match = query in item.text().casefold()
                    item.setHidden(not match)
                    visible |= match
            if heading:
                heading.setHidden(not visible)

    def update_count(self):
        value = self.value()
        self.basket.clear()
        for kind, keys in (("Metric", value.stat_keys), ("Property", value.property_keys)):
            for key in keys:
                item = QListWidgetItem(f"{kind}: {key}")
                item.setData(Qt.UserRole, (kind, key))
                self.basket.addItem(item)
        self.status.setText(f"{len(value.stat_keys)} metrics · {len(value.property_keys)} properties selected")

    def remove_field(self):
        item = self.basket.currentItem()
        if item:
            kind, key = item.data(Qt.UserRole)
            widget = self.list if kind == "Metric" else self.properties
            for index in range(widget.count()):
                if widget.item(index).data(Qt.UserRole) == key:
                    widget.item(index).setCheckState(Qt.Unchecked)
                    break
