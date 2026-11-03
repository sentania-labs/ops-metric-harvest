"""Native workflow shell. Selection modules communicate through shared engine models."""
from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QStackedWidget, QScrollArea, QFrame, QLabel, QPushButton, QFileDialog,
)
from ops_metric_harvest.models import CollectionJob, CollectionGroup, ObjectSelector, MetricSet
from ops_metric_harvest.engine import CollectionEngine
from ops_metric_harvest.profiles import load_profile, save_profile, validate_profile_dict
from .theme import apply_theme
from .workers import Task, make_client, collect
from .screens.common import combo
from .screens.connection import ConnectionPage
from .screens.objects import ObjectsPage
from .screens.metrics import MetricsPage
from .screens.collection import CollectionPage
from .screens.run import RunPage
from .screens.profiles import ProfilesPage


def new_group(number):
    return CollectionGroup(f"Group {number}", "VirtualMachine",
                           ObjectSelector("VirtualMachine", "explicit"), MetricSet())


class MainWindow(QMainWindow):
    def __init__(self, client_factory=make_client, theme="light"):
        super().__init__()
        self.client_factory = client_factory
        self.task = None
        self.closing = False
        self.group_index = 0
        self.preview_counts = {}
        self.job = CollectionJob("Metrics collection", [new_group(1)])
        self.setWindowTitle("VCF Operations Metrics Explorer")
        self.resize(1280, 800)
        root = QWidget()
        root.setObjectName("lattice-root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        header = QFrame()
        header.setProperty("lattice", "header")
        top = QHBoxLayout(header)
        title = QLabel("VCF Operations Metrics Explorer")
        title.setProperty("lattice", "page-title")
        top.addWidget(title, 1)
        top.addWidget(QLabel("Theme:"))
        self.theme = combo(["Light", "Dark"])
        self.theme.setCurrentText(theme.capitalize())
        top.addWidget(self.theme)
        self.theme.currentTextChanged.connect(lambda value: apply_theme(QApplication.instance(), value.lower()))
        outer.addWidget(header)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.nav = QListWidget()
        self.nav.setProperty("lattice", "steps")
        self.nav.addItems(["1  Connection", "2  Objects", "3  Fields", "4  Collection", "5  Run", "Profiles"])
        self.nav.setFixedWidth(185)
        body.addWidget(self.nav)
        right = QVBoxLayout()
        body.addLayout(right, 1)
        self.group_bar = QWidget()
        groups = QHBoxLayout(self.group_bar)
        groups.addWidget(QLabel("Collection group:"))
        self.group_picker = combo([self.job.groups[0].name])
        groups.addWidget(self.group_picker, 1)
        self.add_group_button = QPushButton("Add group")
        self.remove_group_button = QPushButton("Remove group")
        groups.addWidget(self.add_group_button)
        groups.addWidget(self.remove_group_button)
        right.addWidget(self.group_bar)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.connection = ConnectionPage()
        self.objects = ObjectsPage()
        self.metrics = MetricsPage()
        self.collection = CollectionPage()
        self.run_page = RunPage()
        self.profiles = ProfilesPage()
        self.pages = [self.connection, self.objects, self.metrics, self.collection, self.run_page, self.profiles]
        for page in self.pages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        footer = QHBoxLayout()
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        footer.addWidget(self.back)
        footer.addStretch()
        footer.addWidget(self.next)
        right.addLayout(footer)
        self.nav.currentRowChanged.connect(self.navigate)
        self.back.clicked.connect(lambda: self.nav.setCurrentRow(max(0, self.nav.currentRow()-1)))
        self.next.clicked.connect(lambda: self.nav.setCurrentRow(min(5, self.nav.currentRow()+1)))
        self.group_picker.currentIndexChanged.connect(self.switch_group)
        self.add_group_button.clicked.connect(self.add_group)
        self.remove_group_button.clicked.connect(self.remove_group)
        self.objects.scopeChanged.connect(self.change_scope)
        self.objects.kindsRequested.connect(self.load_kinds)
        self.objects.previewRequested.connect(self.preview_objects)
        self.metrics.catalogueRequested.connect(self.load_metrics)
        self.connection.test.clicked.connect(self.test_connection)
        self.connection.sources.clicked.connect(self.load_sources)
        self.connection.changed.connect(self.invalidate_catalogue)
        self.profiles.load_button.clicked.connect(self.choose_profile)
        self.profiles.save_button.clicked.connect(self.choose_save_profile)
        self.run_page.start.clicked.connect(self.start_collection)
        self.run_page.refresh_counts.clicked.connect(self.refresh_counts)
        self.run_page.cancel.clicked.connect(self.cancel_collection)
        self.load_group()
        self.nav.setCurrentRow(0)
        apply_theme(QApplication.instance(), theme)

    def navigate(self, index):
        self.store_group()
        selector = self.objects.value()
        self.metrics.scope.setText(f"{selector.adapter_kind} / {selector.resource_kind}")
        self.stack.setCurrentIndex(index)
        self.group_bar.setVisible(index in (1, 2))
        self.back.setEnabled(index > 0)
        self.next.setEnabled(index < 5)
        if index == 4:
            job = self.snapshot()
            self.run_page.summary.setPlainText(self.review_text(job, self.preview_counts))

    def store_group(self):
        group = self.job.groups[self.group_index]
        group.name = self.objects.group_name()
        group.selector = self.objects.value()
        group.resource_kind = group.selector.resource_kind
        group.metric_set = self.metrics.value()
        self.group_picker.setItemText(self.group_index, group.name or "Unnamed group")

    def load_group(self):
        group = self.job.groups[self.group_index]
        self.objects.load(group)
        self.metrics.load(group.metric_set, group.resource_kind)
        self.metrics.scope.setText(f"{group.selector.adapter_kind} / {group.resource_kind}")
        self.remove_group_button.setEnabled(len(self.job.groups) > 1)

    def switch_group(self, index):
        if index < 0:
            return
        self.store_group()
        self.group_index = index
        self.load_group()

    def rebuild_groups(self):
        self.group_picker.blockSignals(True)
        self.group_picker.clear()
        self.group_picker.addItems([g.name for g in self.job.groups])
        self.group_picker.setCurrentIndex(self.group_index)
        self.group_picker.blockSignals(False)
        self.load_group()

    def add_group(self):
        self.store_group()
        self.job.groups.append(new_group(len(self.job.groups)+1))
        self.group_index = len(self.job.groups)-1
        self.rebuild_groups()

    def remove_group(self):
        if len(self.job.groups) > 1:
            del self.job.groups[self.group_index]
            self.group_index = max(0, self.group_index-1)
            self.rebuild_groups()

    def change_scope(self):
        previous = self.objects.previous_selection
        if previous.resource_ids or previous.names or previous.selection_mode in ("all", "search", "imported"):
            # Keep a selected scope and its basket as an independent collection group.
            old = self.job.groups[self.group_index]
            old.name = self.objects.group_name()
            old.selector = previous
            old.resource_kind = previous.resource_kind
            old.metric_set = self.metrics.value()
            current = CollectionGroup(f"Group {len(self.job.groups) + 1}", self.objects.value().resource_kind,
                                      self.objects.value(), MetricSet())
            self.job.groups.append(current)
            self.group_index = len(self.job.groups) - 1
            self.rebuild_groups()
        self.metrics.load(MetricSet(), self.objects.value().resource_kind)
        self.metrics.scope.setText(" / ".join((self.objects.value().adapter_kind, self.objects.value().resource_kind)))
        self.objects.clear_preview()

    def invalidate_catalogue(self):
        self.preview_counts.clear()
        # Keep deliberate metric choices but discard unselected definitions from the old server.
        self.metrics.load(self.metrics.value(), self.objects.value().resource_kind)
        self.objects.clear_preview()

    def snapshot(self):
        self.store_group()
        job = deepcopy(self.job)
        job.name = self.profiles.name.text().strip()
        job.connection = self.connection.value()
        job.time_range, job.export_config = self.collection.value()
        return job

    def validate(self, job, for_run=False):
        validate_profile_dict(job.to_dict())
        job.time_range.calculate_bounds()
        if not job.name:
            raise ValueError("Enter a job name in Profiles.")
        for group in job.groups:
            selector = group.selector
            if selector.selection_mode == "search" and not selector.search_query:
                raise ValueError(f"{group.name}: enter a name filter or select All.")
            if selector.selection_mode == "explicit" and not (selector.names or selector.resource_ids):
                raise ValueError(f"{group.name}: enter at least one object name or ID.")
            if selector.selection_mode == "imported" and not (selector.csv_content or selector.csv_path):
                raise ValueError(f"{group.name}: choose a CSV file.")
            if for_run and selector.csv_path and not selector.csv_content and not Path(selector.csv_path).is_file():
                raise ValueError(f"{group.name}: CSV file does not exist.")
        if for_run:
            if not job.export_config["formats"]:
                raise ValueError("Choose at least one export format.")
            if not job.export_config["output_dir"]:
                raise ValueError("Choose an output folder.")
            ZoneInfo(job.export_config["timezone"])

    def busy(self, active):
        for page in (self.connection, self.objects, self.metrics, self.collection, self.profiles):
            page.setEnabled(not active)
        self.group_bar.setEnabled(not active)
        self.run_page.refresh_counts.setEnabled(not active)
        self.run_page.start.setEnabled(not active)
        self.run_page.cancel.setEnabled(active and self.stack.currentIndex() == 4)

    def launch(self, operation, success, page):
        if self.task is not None:
            return
        config = self.connection.value(secrets=True)
        self.task = Task(operation, (config.get("password"), config.get("token")), self)
        self.task.succeeded.connect(success)
        self.task.failed.connect(lambda message: self.failed(page, message))
        self.task.progress.connect(self.run_page.report_progress)
        self.task.finished.connect(self.task_finished)
        self.busy(True)
        self.task.start()

    def failed(self, page, message):
        page.set_status(f"Error: {message}")
        if page is self.run_page:
            page.progress.setRange(0, 1)
            page.progress.setValue(0)

    def task_finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.busy(False)
        if self.closing:
            QTimer.singleShot(0, self.close)

    def test_connection(self):
        config = self.connection.value(secrets=True)
        self.connection.status.setText("Testing connection…")
        adapter = self.objects.value().adapter_kind
        def operation(progress, stop):
            client = self.client_factory(config)
            client.test_connection()
            return {"adapters": client.list_adapter_kinds(), "kinds": client.list_resource_kinds(adapter)}
        def connected(result):
            self.connection.status.setText("Status: Connected successfully")
            self.objects.set_kinds(result)
        self.launch(operation, connected, self.connection)

    def load_sources(self):
        config = self.connection.value(secrets=True)
        self.connection.status.setText("Loading login sources…")
        self.launch(lambda progress, stop: self.client_factory(config, authenticate=False).list_auth_sources(),
                    self.sources_loaded, self.connection)

    def sources_loaded(self, sources):
        self.connection.set_sources(sources)
        self.connection.status.setText("Login sources loaded. You can also enter a source name manually.")

    def load_kinds(self, adapter):
        config = self.connection.value(secrets=True)
        self.objects.set_status("Loading live types…")
        def operation(progress, stop):
            client = self.client_factory(config)
            return {"adapters": client.list_adapter_kinds(), "kinds": client.list_resource_kinds(adapter)}
        self.launch(operation, self.objects.set_kinds, self.objects)

    def preview_objects(self, request):
        config = self.connection.value(secrets=True)
        self.objects.set_status("Loading objects…")
        def operation(progress, stop):
            client = self.client_factory(config)
            if "resolve" in request:
                selector = request["resolve"]
                group = CollectionGroup("List resolution", selector.resource_kind, selector, MetricSet())
                resources, warnings, errors = CollectionEngine(client, should_stop=stop).resolve_group_objects(group, {})
                return {"resolved": resources, "warnings": warnings + [e["error"] for e in errors if e["error"] not in warnings]}
            selector = request["selector"]
            if request.get("relation"):
                rid, direction = request["relation"]
                return client.relationship_page(rid, direction, request["page"])
            return client.resource_page(selector.resource_kind, selector.adapter_kind,
                                        request["query"], request["page"])
        def show(result):
            if "resolve" not in request and not request.get("relation"):
                self.preview_counts[self.count_key(request["selector"], request["query"])] = result["total"]
            self.objects.show_matches(result)
        self.launch(operation, show, self.objects)

    def load_metrics(self):
        config = self.connection.value(secrets=True)
        selector = self.objects.value()
        self.metrics.set_status("Loading catalogue…")
        def operation(progress, stop):
            client = self.client_factory(config)
            metrics = client.get_stat_keys(selector.adapter_kind, selector.resource_kind)
            try:
                properties = client.get_property_keys(selector.adapter_kind, selector.resource_kind)
                error = None
            except Exception as exc:
                properties, error = {}, str(exc).splitlines()[0]
            return metrics, properties, error
        self.launch(operation, self.metrics_loaded, self.metrics)

    def metrics_loaded(self, payload):
        metrics, properties, error = payload
        self.metrics.set_catalogue(metrics)
        self.metrics.set_properties(properties, error=error)
        if not metrics:
            self.metrics.set_status("No metric catalogue returned. Check the connection, adapter, and kind; manual keys remain available.")

    @staticmethod
    def count_key(selector, query=None):
        return (selector.adapter_kind, selector.resource_kind,
                query if query is not None else selector.search_query or "")

    def refresh_counts(self):
        job = self.snapshot()
        config = self.connection.value(secrets=True)
        def operation(progress, stop):
            client = self.client_factory(config)
            counts = {}
            for group in job.groups:
                selector = group.selector
                if stop():
                    break
                if selector.selection_mode in ("all", "search"):
                    result = client.resource_page(selector.resource_kind, selector.adapter_kind,
                                                  selector.search_query, page_size=1)
                    counts[self.count_key(selector)] = result["total"]
            return counts
        def show(counts):
            self.preview_counts.update(counts)
            self.run_page.summary.setPlainText(self.review_text(job, self.preview_counts))
            self.run_page.set_status("Object counts refreshed. Dynamic membership is resolved again when collection starts.")
        self.launch(operation, show, self.run_page)

    @staticmethod
    def review_text(job, counts=None):
        lines = []
        for group in job.groups:
            selector = group.selector
            objects = (f"{len(selector.resource_ids)} fixed IDs" if selector.selection_mode == "explicit" and not selector.names
                       else f"dynamic {selector.selection_mode}: {selector.search_query or '*'} (count resolved at run time)"
                       if selector.selection_mode in ("all", "search") else "legacy list resolved at run time")
            if selector.selection_mode in ("all", "search"):
                count = (counts or {}).get(MainWindow.count_key(selector))
                objects += f" · last preview: {count if count is not None else 'unknown'} objects"
            lines.append(f"{group.name}: {selector.adapter_kind}/{group.resource_kind} · {objects} · "
                         f"{len(group.metric_set.stat_keys)} metrics / {len(group.metric_set.property_keys)} properties")
        tr = job.time_range
        if tr.max_samples and tr.mode == "relative":
            lines.append(f"Metrics: latest {tr.max_samples} samples per metric")
        else:
            period = tr.relative_preset if tr.mode == "relative" else f"{tr.start_time} to {tr.end_time}"
            lines.append(f"Historical metrics: {period} · rollup {tr.rollup_type} · interval {tr.interval_type}")
        if any(group.metric_set.property_keys for group in job.groups):
            lines.append("Properties: latest values, stamped at collection time")
        lines.append(f"Export: {', '.join(job.export_config.get('formats', []))} → {job.export_config.get('output_dir', '')}")
        lines.append("Fixed IDs are reused; dynamic membership is re-evaluated on every run.")
        return "\n".join(lines)

    def load_profile_path(self, path):
        job, warnings = load_profile(str(path))
        self.validate(job)
        self.job = job
        self.preview_counts.clear()
        self.group_index = 0
        self.connection.load(job.connection)
        self.collection.load(job.time_range, job.export_config)
        self.profiles.name.setText(job.name)
        self.rebuild_groups()
        self.profiles.status.setText("\n".join([f"Loaded {path}", *warnings]))

    def save_profile_path(self, path):
        job = self.snapshot()
        self.validate(job)
        save_profile(job, str(path))
        self.profiles.status.setText(f"Saved {path}. No credentials included.")

    def choose_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load profile", "", "JSON profiles (*.json)")
        if path:
            try:
                self.load_profile_path(path)
            except Exception as exc:
                self.failed(self.profiles, str(exc))

    def choose_save_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save profile", "collection.json", "JSON profiles (*.json)")
        if path:
            try:
                self.save_profile_path(path)
            except Exception as exc:
                self.failed(self.profiles, str(exc))

    def start_collection(self):
        if self.task is not None:
            return
        try:
            job = self.snapshot()
            self.validate(job, for_run=True)
        except Exception as exc:
            self.failed(self.run_page, str(exc))
            return
        config = self.connection.value(secrets=True)
        self.run_page.begin()
        self.launch(lambda progress, stop: collect(self.client_factory(config), job, progress, stop),
                    self.run_page.show_result, self.run_page)

    def cancel_collection(self):
        if self.task:
            self.task.stop.set()
            self.run_page.cancel.setEnabled(False)
            self.run_page.status.setText("Cancellation requested. Waiting for the current request to finish…")

    def closeEvent(self, event):
        if self.task is not None:
            self.closing = True
            self.task.stop.set()
            self.statusBar().showMessage("Closing when the current operation finishes…")
            event.ignore()
        else:
            event.accept()
