"""Live object browser.

Shell contract: load/value/group_name/set_kinds/show_matches/clear_preview/set_status.
Signals: scopeChanged, kindsRequested(adapter), previewRequested(request dictionary).
Requests carry a selector plus page or relationship or list-resolution information.
"""
from copy import deepcopy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QWidget, QHBoxLayout, QCheckBox,
)
from ops_metric_harvest.models import ObjectSelector
from .common import Page, PathPicker, combo


def button_row(*widgets):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return row


class ObjectsPage(Page):
    scopeChanged = Signal()
    kindsRequested = Signal(str)
    previewRequested = Signal(object)

    def __init__(self):
        super().__init__("Select objects", "Browse a live type, then choose fixed IDs or all matching objects. Add a collection group for another adapter or type.")
        self.layout.setContentsMargins(24, 10, 24, 10)
        self.layout.setSpacing(8)
        self.form.setSpacing(8)
        self._loading = False
        self._selector = ObjectSelector("VirtualMachine", "explicit")
        self.selected = {}
        self.page = 0
        self.relation = None
        self.rows = []
        self.name = QLineEdit()
        self.adapter = combo(["VMWARE"], editable=True)
        self.kind = combo(["VirtualMachine"], editable=True)
        self.refresh = QPushButton("Refresh types")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Name contains…")
        self.preview = QPushButton("Search")
        self.matches = QTableWidget(0, 4)
        self.matches.setHorizontalHeaderLabels(["Select / name", "Resource ID", "Adapter", "Type"])
        self.matches.setEditTriggers(QTableWidget.NoEditTriggers)
        self.matches.setSelectionBehavior(QTableWidget.SelectRows)
        self.matches.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matches.setFixedHeight(150)
        self.previous = QPushButton("Previous")
        self.next_page = QPushButton("Next page")
        self.page_label = QLabel("Search to load a page")
        self.parents = QPushButton("Parents")
        self.children = QPushButton("Children")
        self.browse = QPushButton("Back to type")
        self.open_type = QPushButton("Browse related type")
        self.dynamic = QCheckBox("All matching this type / filter (resolved at run time)")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.review = QPushButton("Review selection")
        self.clear = QPushButton("Clear")
        self.review_list = QPlainTextEdit()
        self.review_list.setReadOnly(True)
        self.review_list.setFixedHeight(65)
        self.review_list.hide()
        self.secondary = QCheckBox("Paste or import a name / ID list")
        self.names = QPlainTextEdit()
        self.names.setPlaceholderText("One exact name or resource ID per line")
        self.names.setMaximumHeight(70)
        self.csv = PathPicker("Import list", file_filter="CSV (*.csv);;All files (*)")
        self.resolve = QPushButton("Resolve list to fixed IDs")
        for label, widget in [("Group:", self.name), ("Adapter / type:", button_row(self.adapter, self.kind, self.refresh)),
                              ("Search:", button_row(self.query, self.preview)), ("", self.matches),
                              ("", button_row(self.previous, self.page_label, self.next_page)),
                              ("Relationships:", button_row(self.parents, self.children, self.open_type, self.browse)),
                              ("", self.dynamic), ("Selection:", button_row(self.summary, self.review, self.clear)),
                              ("", self.review_list), ("", self.secondary), ("List:", self.names),
                              ("File:", self.csv), ("", self.resolve)]:
            self.form.addRow(label, widget)
        self._scope = self._current_scope()
        self.kind.activated.connect(self.commit_scope)
        self.kind.lineEdit().editingFinished.connect(self.commit_scope)
        self.adapter.activated.connect(self.commit_scope)
        self.adapter.lineEdit().editingFinished.connect(self.commit_scope)
        self.refresh.clicked.connect(lambda: self.kindsRequested.emit(self.adapter.currentText()))
        self.preview.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.query.textChanged.connect(self.filter_changed)
        self.previous.clicked.connect(lambda: self.request_page(self.page - 1))
        self.next_page.clicked.connect(lambda: self.request_page(self.page + 1))
        self.matches.itemChanged.connect(self.check_object)
        self.parents.clicked.connect(lambda: self.show_relations("PARENT"))
        self.children.clicked.connect(lambda: self.show_relations("CHILD"))
        self.open_type.clicked.connect(self.browse_related_type)
        self.browse.clicked.connect(self.search)
        self.dynamic.toggled.connect(self.change_selection_mode)
        self.review.clicked.connect(self.toggle_review)
        self.clear.clicked.connect(self.clear_selection)
        self.secondary.toggled.connect(self.update_fields)
        self.resolve.clicked.connect(self.resolve_list)
        self.csv.edit.textChanged.connect(lambda: setattr(self._selector, "csv_content", None))
        self.update_fields()
        self.clear_preview()
        self.update_summary()

    def _current_scope(self):
        return self.adapter.currentText().strip(), self.kind.currentText().strip()

    def commit_scope(self):
        if self._loading or self._current_scope() == self._scope:
            return
        self.previous_selection = self.value()
        self.previous_selection.adapter_kind, self.previous_selection.resource_kind = self._scope
        self._scope = self._current_scope()
        self.clear_selection()
        self.clear_preview()
        self.scopeChanged.emit()

    def group_name(self):
        return self.name.text().strip()

    def value(self):
        adapter, kind = self._current_scope()
        if self.dynamic.isChecked():
            query = self.query.text().strip()
            return ObjectSelector(kind, "search" if query else "all", adapter, query or None)
        # Legacy names/imports remain intact until explicitly resolved by the user.
        selector = deepcopy(self._selector)
        selector.adapter_kind, selector.resource_kind = adapter, kind
        if selector.selection_mode not in ("imported", "explicit"):
            selector = ObjectSelector(kind, "explicit", adapter)
        if selector.selection_mode == "imported" and self.selected:
            # Checked objects replace the imported list; the engine ignores IDs on an imported selector.
            selector = ObjectSelector(kind, "explicit", adapter)
        selector.resource_ids = list(self.selected)
        if selector.selection_mode != "imported":
            selector.csv_path = selector.csv_content = None
        return selector

    def load(self, group):
        self._loading = True
        self.name.setText(group.name)
        self.adapter.setCurrentText(group.selector.adapter_kind or "VMWARE")
        self.kind.setCurrentText(group.resource_kind)
        self.query.setText(group.selector.search_query or "")
        self.csv.edit.setText(group.selector.csv_path or "")
        self.names.setPlainText("\n".join(group.selector.names))
        self._selector = deepcopy(group.selector)
        if self._selector.selection_mode != "imported":
            self._selector.csv_path = self._selector.csv_content = None
            self.csv.edit.clear()
        self.selected = {rid: rid for rid in group.selector.resource_ids}
        self.dynamic.setChecked(group.selector.selection_mode in ("all", "search"))
        self.secondary.setChecked(bool(group.selector.names or group.selector.csv_path or group.selector.csv_content))
        self._scope = self._current_scope()
        self._loading = False
        self.clear_preview()
        self.update_summary()

    def set_kinds(self, payload):
        self._loading = True
        if isinstance(payload, dict):
            adapters, kinds = payload["adapters"], payload["kinds"]
        else:
            adapters, kinds = [], payload
        for widget, entries in ((self.adapter, adapters), (self.kind, kinds)):
            current = widget.currentText()
            widget.clear()
            widget.addItems(entries)
            widget.setCurrentText(current)
        self._loading = False
        self.status.setText(f"{len(kinds)} live types. Counts appear when browsing a type.")

    def clear_preview(self):
        self.page = 0
        self.relation = None
        self.rows = []
        self.matches.setRowCount(0)
        self.previous.setEnabled(False)
        self.next_page.setEnabled(False)
        self.page_label.setText("Search to load a page")
        self.status.clear()

    def filter_changed(self):
        if not self._loading:
            self.clear_preview()
            self.update_summary()

    def search(self):
        self.relation = None
        self.request_page(0)

    def request_page(self, page):
        self.previewRequested.emit({"selector": self.value(), "query": self.query.text().strip(),
                                    "page": max(0, page), "relation": self.relation})

    def current_resource(self):
        row = self.matches.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def show_relations(self, direction):
        resource = self.current_resource()
        if resource:
            self.relation = (resource["resourceId"], direction)
            self.request_page(0)
        else:
            self.set_status("Select a row to browse its parents or children.")

    def browse_related_type(self):
        resource = self.current_resource()
        if resource and resource.get("adapterKind") and resource.get("resourceKind"):
            self.adapter.setCurrentText(resource["adapterKind"])
            self.kind.setCurrentText(resource["resourceKind"])
            self.commit_scope()
            self.query.clear()
            self.search()

    def show_matches(self, result):
        if "resolved" in result:
            for resource in result["resolved"]:
                self.selected[resource["resourceId"]] = resource["name"]
            self.use_fixed_selection()
            self.dynamic.setChecked(False)
            self.update_summary()
            self.set_status("\n".join(result["warnings"]) or "List resolved to fixed IDs.")
            return
        self.rows = result["resources"]
        self.page = result["page"]
        self.matches.blockSignals(True)
        self.matches.setRowCount(len(self.rows))
        for row, resource in enumerate(self.rows):
            for col, key in enumerate(("name", "resourceId", "adapterKind", "resourceKind")):
                item = QTableWidgetItem(resource.get(key) or "")
                if col == 0 and (resource.get("adapterKind"), resource.get("resourceKind")) == self._current_scope():
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if resource["resourceId"] in self.selected else Qt.Unchecked)
                self.matches.setItem(row, col, item)
        self.matches.blockSignals(False)
        total = result["total"]
        self.page_label.setText(f"Page {self.page + 1} · {total if total is not None else 'unknown'} total matches")
        self.previous.setEnabled(self.page > 0)
        self.next_page.setEnabled(result["has_next"])
        self.set_status(f"{len(self.rows)} objects on this page." + (" Related types need their own collection group." if self.relation else ""))

    def check_object(self, item):
        if item.column() != 0:
            return
        resource = self.rows[item.row()]
        if item.checkState() == Qt.Checked:
            self.selected[resource["resourceId"]] = resource["name"]
        else:
            self.selected.pop(resource["resourceId"], None)
        self.use_fixed_selection()
        self.dynamic.setChecked(False)
        self.update_summary()

    def use_fixed_selection(self):
        self._selector = ObjectSelector(self.kind.currentText(), "explicit", self.adapter.currentText())
        self.csv.edit.clear()

    def change_selection_mode(self, dynamic):
        if dynamic and not self._loading:
            self.use_fixed_selection()
        self.update_summary()

    def update_summary(self):
        if self.dynamic.isChecked():
            text = f"Dynamic: all {self.kind.currentText()} matching '{self.query.text().strip() or '*'}'"
        else:
            text = f"{len(self.selected)} fixed IDs"
            if self._selector.selection_mode == "imported" and self.selected:
                text += " · replaces the imported list"
            elif self._selector.names or self._selector.selection_mode == "imported":
                text += " · legacy list requires resolution"
        self.summary.setText(text)
        self.review_list.setPlainText(text + "\n" + "\n".join(f"{name}  {rid}" for rid, name in self.selected.items()))

    def toggle_review(self):
        self.form.setRowVisible(self.review_list, not self.review_list.isVisible())

    def clear_selection(self):
        self.selected.clear()
        self.use_fixed_selection()
        self.dynamic.setChecked(False)
        self.matches.blockSignals(True)
        for row in range(self.matches.rowCount()):
            item = self.matches.item(row, 0)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Unchecked)
        self.matches.blockSignals(False)
        self.update_summary()

    def update_fields(self):
        for widget in (self.names, self.csv, self.resolve):
            self.form.setRowVisible(widget, self.secondary.isChecked())

    def resolve_list(self):
        selector = ObjectSelector(self.kind.currentText(), "explicit", self.adapter.currentText(),
                                  names=[s.strip() for s in self.names.toPlainText().splitlines() if s.strip()])
        if self.csv.edit.text().strip() or self._selector.csv_content:
            selector.selection_mode = "imported"
            selector.csv_path = self.csv.edit.text().strip() or None
            selector.csv_content = self._selector.csv_content
        self.previewRequested.emit({"resolve": selector})
