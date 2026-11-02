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
    return CollectionGroup(f"Group {number}", "VirtualMachine", ObjectSelector("VirtualMachine"), MetricSet())


class MainWindow(QMainWindow):
    def __init__(self, client_factory=make_client, theme="light"):
        super().__init__()
        self.client_factory = client_factory
        self.task = None
        self.closing = False
        self.loading_group = False
        self.group_index = 0
        self.job = CollectionJob("Metrics collection", [new_group(1)])
        self.setWindowTitle("VCF Operations Metrics Explorer")
        self.resize(1120, 860)
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
        self.nav.addItems(["1  Connection", "2  Objects", "3  Metrics", "4  Collection", "5  Run", "Profiles"])
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
        self.objects.kind_changed.connect(self.change_kind)
        self.objects.adapter.textChanged.connect(self.change_adapter)
        self.connection.test.clicked.connect(self.test_connection)
        self.connection.sources.clicked.connect(self.load_sources)
        self.connection.changed.connect(self.invalidate_catalogue)
        self.objects.refresh.clicked.connect(self.load_kinds)
        self.objects.preview.clicked.connect(self.preview_objects)
        self.metrics.refresh.clicked.connect(self.load_metrics)
        self.profiles.load_button.clicked.connect(self.choose_profile)
        self.profiles.save_button.clicked.connect(self.choose_save_profile)
        self.run_page.start.clicked.connect(self.start_collection)
        self.run_page.cancel.clicked.connect(self.cancel_collection)
        self.load_group()
        self.metrics.select_starters()
        self.nav.setCurrentRow(0)
        apply_theme(QApplication.instance(), theme)

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        self.group_bar.setVisible(index in (1, 2))
        self.back.setEnabled(index > 0)
        self.next.setEnabled(index < 5)
        if index == 4:
            job = self.snapshot()
            scope = [f"{g.name}: {g.resource_kind}, {g.selector.selection_mode}, {len(g.metric_set.stat_keys)} metrics" for g in job.groups]
            self.run_page.summary.setPlainText("\n".join(scope + [f"Output: {job.export_config['output_dir']}"]))

    def store_group(self):
        group = self.job.groups[self.group_index]
        group.name = self.objects.name.text().strip()
        group.selector = self.objects.value()
        group.resource_kind = group.selector.resource_kind
        group.metric_set = self.metrics.value()
        self.group_picker.setItemText(self.group_index, group.name or "Unnamed group")

    def load_group(self):
        self.loading_group = True
        group = self.job.groups[self.group_index]
        self.objects.load(group)
        self.metrics.load(group.metric_set, group.resource_kind)
        self.loading_group = False
        self.remove_group_button.setEnabled(len(self.job.groups) > 1)

    def switch_group(self, index):
        if index < 0 or self.loading_group:
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
        self.metrics.select_starters()

    def remove_group(self):
        if len(self.job.groups) > 1:
            del self.job.groups[self.group_index]
            self.group_index = max(0, self.group_index-1)
            self.rebuild_groups()

    def change_kind(self, kind):
        if not self.loading_group:
            self.metrics.load(MetricSet(), kind)
            self.objects.matches.clear()
            self.objects.status.clear()

    def change_adapter(self):
        if not self.loading_group:
            self.metrics.load(MetricSet(), self.objects.kind.currentText())

    def invalidate_catalogue(self):
        # Keep deliberate metric choices but discard unselected definitions from the old server.
        self.metrics.load(self.metrics.value(), self.objects.kind.currentText())
        self.objects.matches.clear()

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
        page.status.setText(f"Error: {message}")
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
        self.launch(lambda progress, stop: self.client_factory(config).test_connection(),
                    lambda result: self.connection.status.setText("Status: Connected successfully"), self.connection)

    def load_sources(self):
        config = self.connection.value(secrets=True)
        self.connection.status.setText("Loading login sources…")
        self.launch(lambda progress, stop: self.client_factory(config, authenticate=False).list_auth_sources(),
                    self.sources_loaded, self.connection)

    def sources_loaded(self, sources):
        self.connection.set_sources(sources)
        self.connection.status.setText("Login sources loaded. You can also enter a source name manually.")

    def load_kinds(self):
        config = self.connection.value(secrets=True)
        adapter = self.objects.adapter.text().strip() or "VMWARE"
        self.objects.status.setText("Loading resource kinds…")
        self.launch(lambda progress, stop: self.client_factory(config).list_resource_kinds(adapter),
                    self.kinds_loaded, self.objects)

    def kinds_loaded(self, kinds):
        self.objects.set_kinds(kinds)
        self.objects.status.setText(f"{len(kinds)} resource kinds available.")

    def preview_objects(self):
        config = self.connection.value(secrets=True)
        selector = self.objects.value()
        self.objects.status.setText("Loading preview…")
        self.launch(lambda progress, stop: self.client_factory(config).search_resources(
            selector.resource_kind, name_query=selector.search_query if selector.selection_mode == "search" else None,
            max_resources=200), self.objects.show_matches, self.objects)

    def load_metrics(self):
        config = self.connection.value(secrets=True)
        selector = self.objects.value()
        self.metrics.status.setText("Loading catalogue…")
        self.launch(lambda progress, stop: self.client_factory(config).get_stat_keys(selector.adapter_kind, selector.resource_kind),
                    self.metrics_loaded, self.metrics)

    def metrics_loaded(self, catalogue):
        if catalogue:
            self.metrics.set_catalogue(catalogue)
        else:
            self.metrics.status.setText("No catalogue returned. Check the connection, adapter, and kind; manual keys remain available.")

    def load_profile_path(self, path):
        job, warnings = load_profile(str(path))
        self.validate(job)
        self.job = job
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
