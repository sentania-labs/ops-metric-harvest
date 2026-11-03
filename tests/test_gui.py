"""Native Qt behavior through widgets, background tasks, profiles, and real exporters."""
import json
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from ops_metric_harvest.client import OpsClient
from ops_metric_harvest.gui.main_window import MainWindow
from ops_metric_harvest.gui.screens.collection import CollectionPage
from ops_metric_harvest.gui.screens.connection import ConnectionPage
from ops_metric_harvest.gui.screens.metrics import MetricsPage
from ops_metric_harvest.gui.screens.objects import ObjectsPage
from ops_metric_harvest.gui.theme import apply_theme
from ops_metric_harvest.gui.workers import make_client
from ops_metric_harvest.models import CollectionGroup, MetricSet, ObjectSelector, TimeRange


@pytest.fixture
def window(qtbot):
    client = Mock()
    client.test_connection.return_value = {"status": "ok"}
    client.list_auth_sources.return_value = ["AD", "Local"]
    client.list_resource_kinds.return_value = ["CustomKind", "HostSystem", "VirtualMachine"]
    client.list_adapter_kinds.return_value = ["VMWARE"]
    client.get_property_keys.return_value = {}
    client.resource_page.return_value = {"resources": [{"name": "vm-a", "resourceId": "id-a", "adapterKind": "VMWARE", "resourceKind": "VirtualMachine"}], "page": 0, "total": 1, "has_next": False}
    client.search_resources.return_value = [{"name": "vm-a", "resourceId": "id-a"}]
    client.get_stat_keys.return_value = {"cpu|test": {"name": "CPU test", "unit": "%"}}
    factory = Mock(return_value=client)
    widget = MainWindow(client_factory=factory)
    qtbot.addWidget(widget)
    widget.objects.set_kinds({"adapters": ["VMWARE"], "kinds": ["HostSystem", "VirtualMachine"]})
    widget.show()
    return widget


def wait_task(qtbot, window):
    qtbot.waitUntil(lambda: window.task is None, timeout=5000)


def test_connection_modes_tls_and_no_secrets(qtbot):
    page = ConnectionPage()
    qtbot.addWidget(page)
    page.show()
    assert page.password.isVisible()
    assert not page.token.isVisible()
    page.password.setText("test-secret")
    page.auth.setCurrentIndex(1)
    page.token.setText("test-token")
    assert page.token.isVisible() and not page.password.isVisible()
    assert "token" not in page.value() and "password" not in page.value()
    assert page.value(secrets=True)["token"] == "test-token"
    page.insecure.setChecked(True)
    assert page.warning.isVisible()
    assert not page.ca.isEnabled()
    assert page.value()["verify_ssl"] is False
    page.load({"server": "ops.example", "password": "not-loaded", "token": "not-loaded"})
    assert not page.password.text() and not page.token.text()
    assert page.value()["verify_ssl"] is True


def test_connection_test_and_sources(window, qtbot):
    window.connection.test.click()
    wait_task(qtbot, window)
    assert "Connected successfully" in window.connection.status.text()
    window.connection.server.setText("ops.example")
    assert window.connection.status.text() == "Status: Not checked"
    window.connection.sources.click()
    wait_task(qtbot, window)
    assert window.connection.source.findText("AD") >= 0
    assert window.client_factory.call_args.kwargs == {"authenticate": False}


def test_connection_failure_redacts_runtime_secret(window, qtbot):
    window.connection.password.setText("private-value")
    window.client_factory.side_effect = ValueError("Rejected private-value")
    window.connection.test.click()
    wait_task(qtbot, window)
    assert window.connection.status.text() == "Error: Rejected [REDACTED]"
    assert window.connection.test.isEnabled()


def test_client_config_auth_and_ca():
    client_type = Mock()
    cfg = {"server": "ops.example", "auth_type": "basic", "username": "alice", "password": "secret",
           "auth_source": "Local", "verify_ssl": True, "ca_bundle": "lab.pem"}
    client = make_client(cfg, client_type=client_type)
    assert client_type.call_args.kwargs["ca_bundle"] == "lab.pem"
    client.login.assert_called_once_with("alice", "secret", None)
    cfg.update(auth_type="token", token="token-value")
    make_client(cfg, client_type=client_type)
    client.set_token.assert_called_once_with("token-value")
    client.reset_mock()
    make_client(cfg, authenticate=False, client_type=client_type)
    client.login.assert_not_called()
    client.set_token.assert_not_called()


@pytest.mark.parametrize("server", ["", "http://ops.example", "https://user:secret@ops.example", "https://ops.example?password=x"])
def test_client_rejects_unsafe_or_missing_url(server):
    with pytest.raises(ValueError):
        make_client({"server": server}, authenticate=False)


def test_ca_bundle_is_loaded_before_requests():
    context = Mock()
    with patch("ssl.create_default_context", return_value=context):
        OpsClient("ops.example", ca_bundle="lab.pem")
    context.load_verify_locations.assert_called_once_with(cafile="lab.pem")
    context.reset_mock()
    with patch("ssl.create_default_context", return_value=context):
        OpsClient("ops.example", ca_bundle="missing.pem", verify=False)
    context.load_verify_locations.assert_not_called()


def test_auth_sources_api():
    client = OpsClient("ops.example")
    with patch.object(client, "_request", return_value={"sources": [{"name": "Local"}, {}, {"name": "AD"}]} ) as request:
        assert client.list_auth_sources() == ["Local", "AD"]
        request.assert_called_once_with("GET", "/auth/sources")


def test_objects_modes_and_embedded_csv(qtbot):
    page = ObjectsPage()
    qtbot.addWidget(page)
    group = CollectionGroup("CSV group", "VirtualMachine", ObjectSelector("VirtualMachine", "imported", csv_content="Name\nvm-a\n"), MetricSet())
    page.load(group)
    assert page.value().csv_content == "Name\nvm-a\n"
    page.csv.edit.setText("/tmp/new.csv")
    assert page.value().csv_content is None
    page.dynamic.setChecked(True)
    page.query.setText("db")
    assert page.value().selection_mode == "search"
    assert page.value().search_query == "db"
    page.clear_selection()
    assert page.value().resource_ids == []
    assert page.value().selection_mode == "explicit"


def test_objects_discovery(window, qtbot):
    window.nav.setCurrentRow(1)
    window.objects.refresh.click()
    wait_task(qtbot, window)
    assert window.objects.kind.findText("CustomKind") >= 0
    window.objects.dynamic.setChecked(True)
    window.objects.query.setText("vm")
    window.objects.preview.click()
    wait_task(qtbot, window)
    assert window.objects.matches.item(0, 0).text() == "vm-a"
    window.client_factory.return_value.resource_page.assert_called_once_with("VirtualMachine", "VMWARE", "vm", 0)


def test_metric_filter_preserves_checked_keys(qtbot):
    page = MetricsPage()
    qtbot.addWidget(page)
    page.load(MetricSet(["cpu|usage"], {"cpu|usage": {"name": "CPU"}}), "VirtualMachine")
    page.set_catalogue({"cpu|usage": {"name": "CPU"}, "mem|usage": {"name": "Memory"}})
    page.filter.setText("Memory")
    assert page.list.item(0).isHidden()
    assert page.value().stat_keys == ["cpu|usage"]
    page.list.item(3).setCheckState(Qt.Checked)
    page.manual.setText("extra|metric, extra|metric")
    page.add.click()
    assert page.value().stat_keys == ["cpu|usage", "extra|metric", "mem|usage"]


def test_metric_catalogue_and_kind_reset(window, qtbot):
    window.nav.setCurrentRow(2)
    window.metrics.refresh.click()
    wait_task(qtbot, window)
    assert "cpu|test" in window.metrics.catalogue
    window.objects.kind.setCurrentText("HostSystem")
    window.objects.commit_scope()
    assert not window.metrics.value().stat_keys
    assert window.metrics.kind == "HostSystem"


def test_typing_scope_keeps_metrics_until_committed(window, qtbot):
    window.metrics.select_starters()
    selected = window.metrics.value().stat_keys
    assert selected
    window.objects.adapter.setCurrentText("VMWAR")
    window.objects.kind.lineEdit().setText("Host")
    assert window.metrics.value().stat_keys == selected
    window.objects.adapter.setCurrentText("VMWARE")
    window.objects.kind.lineEdit().setText("VirtualMachine")
    window.objects.adapter.lineEdit().editingFinished.emit()
    assert window.metrics.value().stat_keys == selected
    window.objects.kind.lineEdit().setText("HostSystem")
    assert window.metrics.value().stat_keys == selected
    window.objects.kind.lineEdit().editingFinished.emit()
    assert not window.metrics.value().stat_keys
    assert window.metrics.kind == "HostSystem"


def test_collection_modes_and_native_picker(qtbot, tmp_path):
    page = CollectionPage()
    qtbot.addWidget(page)
    page.mode.setCurrentIndex(2)
    page.latest.setValue(17)
    tr, _ = page.value()
    assert tr.max_samples == 17 and tr.mode == "relative"
    assert not page.rollup.isEnabled()
    page.load(TimeRange(mode="absolute", start_time="2026-10-01T12:00:00Z", end_time="2026-10-02T12:00:00Z"), {"formats": ["json"], "output_dir": str(tmp_path)})
    tr, config = page.value()
    assert tr.start_time == "2026-10-01T12:00:00Z"
    assert tr.end_time == "2026-10-02T12:00:00Z"
    assert tr.max_samples is None
    assert config["formats"] == ["json"]
    with patch("ops_metric_harvest.gui.screens.common.QFileDialog.getExistingDirectory", return_value=str(tmp_path / "picked")):
        page.output.browse.click()
    assert page.value()[1]["output_dir"] == str(tmp_path / "picked")


def test_group_switch_and_profile_round_trip(window, qtbot, tmp_path):
    window.objects.name.setText("First")
    window.objects.dynamic.setChecked(True)
    window.metrics.select_starters()
    first_keys = window.metrics.value().stat_keys
    window.add_group()
    window.objects.name.setText("Second")
    window.objects.selected = {"id-a": "vm-a", "id-b": "vm-b"}
    window.metrics.select_starters()
    window.group_picker.setCurrentIndex(0)
    assert window.objects.name.text() == "First"
    assert window.metrics.value().stat_keys == first_keys
    window.connection.password.setText("not-in-profile")
    path = tmp_path / "profile.json"
    window.save_profile_path(path)
    data = json.loads(path.read_text())
    assert data["schema_version"] == "2.0"
    assert len(data["groups"]) == 2
    assert "password" not in data["connection"]
    window.load_profile_path(path)
    assert window.connection.password.text() == ""
    assert window.snapshot().to_dict() == data
    window.group_picker.setCurrentIndex(1)
    assert window.objects.value().resource_ids == ["id-a", "id-b"]
    window.remove_group()
    assert len(window.job.groups) == 1


def test_existing_multigroup_profile_preserves_overrides(window, tmp_path):
    path = Path(__file__).parents[1] / "examples/profiles/scenario_c_two_vm_groups.json"
    window.load_profile_path(path)
    window.job.groups[0].query_overrides = {"preserve": "value"}
    window.collection.mode.setCurrentIndex(2)
    window.collection.latest.setValue(12)
    saved = tmp_path / "saved.json"
    window.save_profile_path(saved)
    window.load_profile_path(saved)
    assert window.job.groups[0].query_overrides == {"preserve": "value"}
    assert window.snapshot().time_range.max_samples == 12
    assert len(window.job.groups) == 2


def test_invalid_profile_does_not_replace_job(window, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":"9.0"}')
    before = window.snapshot().to_dict()
    with pytest.raises(Exception, match="Unsupported schema_version"):
        window.load_profile_path(path)
    assert window.snapshot().to_dict() == before


def test_preflight_rejects_missing_metrics(window):
    window.metrics.load(MetricSet(), "VirtualMachine")
    window.start_collection()
    assert window.task is None
    assert "at least one stat key" in window.run_page.status.text()
    window.client_factory.assert_not_called()


def test_collection_background_exports_and_preview(window, qtbot, tmp_path, mock_client):
    window.client_factory = Mock(return_value=mock_client)
    # The all-VM fixture intentionally returns only unrelated misalignment keys.
    window.objects.kind.setCurrentText("HostSystem")
    window.objects.commit_scope()
    window.metrics.select_starters()
    window.objects.dynamic.setChecked(True)
    window.collection.output.edit.setText(str(tmp_path))
    for check in window.collection.formats.values():
        check.setChecked(True)
    window.nav.setCurrentRow(4)
    window.run_page.start.click()
    wait_task(qtbot, window)
    assert window.run_page.result.status in ("success", "partial")
    assert window.run_page.table.rowCount() > 0
    assert len(window.run_page.files) == 5
    assert all(Path(path).is_file() and Path(path).stat().st_size for path in window.run_page.files)
    assert "files saved" in window.run_page.status.text()
    assert window.run_page.start.isEnabled()
    assert not window.run_page.cancel.isEnabled()


def test_cancellation_and_close_wait_for_worker(window, qtbot):
    entered = Event()
    observed_stop = Event()
    def operation(progress, stop):
        entered.set()
        while not stop():
            observed_stop.wait(0.01)
        observed_stop.set()
        return None
    window.launch(operation, lambda result: None, window.connection)
    qtbot.waitUntil(entered.is_set)
    window.close()
    assert window.isVisible()  # Close deferred while the thread owns work.
    wait_task(qtbot, window)
    qtbot.waitUntil(lambda: not window.isVisible())
    assert observed_stop.is_set()


def test_theme_switch_updates_palette(window, qapp):
    window.theme.setCurrentText("Dark")
    assert qapp.palette().color(QPalette.Window).name() == "#1b1f24"
    window.theme.setCurrentText("Light")
    assert qapp.palette().color(QPalette.Window).name() == "#f6f7f9"
    apply_theme(qapp, "light")


def test_engine_cancellation_returns_cancelled_summary(window, qtbot, tmp_path, mock_client):
    window.metrics.select_starters()
    window.objects.dynamic.setChecked(True)
    entered, release = Event(), Event()
    original_search = mock_client.search_resources
    def delayed_search(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original_search(*args, **kwargs)
    mock_client.search_resources = delayed_search
    window.client_factory = Mock(return_value=mock_client)
    window.collection.output.edit.setText(str(tmp_path))
    window.nav.setCurrentRow(4)
    window.run_page.start.click()
    qtbot.waitUntil(entered.is_set)
    window.run_page.cancel.click()
    release.set()
    wait_task(qtbot, window)
    assert window.run_page.result.status == "cancelled"
    assert window.run_page.status.text().startswith("Cancelled:")
    assert not window.run_page.files


def test_export_failure_keeps_results(window, qtbot, tmp_path, mock_client):
    window.client_factory = Mock(return_value=mock_client)
    window.objects.kind.setCurrentText("HostSystem")
    window.objects.commit_scope()
    window.metrics.select_starters()
    window.objects.dynamic.setChecked(True)
    destination = tmp_path / "not-a-directory"
    destination.write_text("keep")
    window.collection.output.edit.setText(str(destination))
    window.nav.setCurrentRow(4)
    window.run_page.start.click()
    wait_task(qtbot, window)
    assert window.run_page.table.rowCount() > 0
    assert "1 export errors" in window.run_page.status.text()
    assert "Cannot create export folder" in window.run_page.log.toPlainText()
    assert destination.read_text() == "keep"


def test_gui_command_smoke_exits_cleanly(tmp_path):
    import os
    import subprocess
    import sys
    path = tmp_path / "connection.png"
    result = subprocess.run([sys.executable, "-m", "ops_metric_harvest.cli", "gui", "--screenshot", str(path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("mode", ["all", "search", "explicit"])
def test_non_imported_stale_csv_path_does_not_block_run(window, tmp_path, mode):
    window.metrics.select_starters()
    job = window.snapshot()
    job.groups[0].selector = ObjectSelector(
        "VirtualMachine", mode, search_query="vm", resource_ids=["id-a"],
        csv_path=str(tmp_path / "missing.csv"))
    window.validate(job, for_run=True)


@pytest.mark.parametrize("selection", ["dynamic", "fixed"])
def test_leaving_imported_selection_clears_stale_csv(window, tmp_path, selection):
    group = CollectionGroup("Imported", "VirtualMachine",
                            ObjectSelector("VirtualMachine", "imported", csv_path=str(tmp_path / "missing.csv")),
                            MetricSet(["cpu|usage"]))
    window.objects.load(group)
    window.metrics.load(group.metric_set, group.resource_kind)
    with pytest.raises(ValueError, match="CSV file does not exist"):
        window.validate(window.snapshot(), for_run=True)
    if selection == "dynamic":
        window.objects.dynamic.setChecked(True)
        assert window.objects.value().selection_mode == "all"
        # Returning to fixed selection must not reactivate the old import.
        window.objects.dynamic.setChecked(False)
    window.objects.show_matches({"resources": [{"resourceId": "id-a", "name": "vm-a", "adapterKind": "VMWARE",
                                               "resourceKind": "VirtualMachine"}],
                                 "page": 0, "total": 1, "has_next": False})
    window.objects.matches.item(0, 0).setCheckState(Qt.Checked)
    selector = window.objects.value()
    assert selector.selection_mode == "explicit"
    assert selector.resource_ids == ["id-a"]
    assert selector.csv_path is None and selector.csv_content is None
    assert window.objects.csv.edit.text() == ""
    window.validate(window.snapshot(), for_run=True)


def test_non_imported_loaded_profile_drops_inactive_csv(window, tmp_path):
    group = CollectionGroup("Fixed", "VirtualMachine",
                            ObjectSelector("VirtualMachine", "explicit", resource_ids=["id-a"],
                                           csv_path=str(tmp_path / "missing.csv"), csv_content="Name\nvm-b"),
                            MetricSet(["cpu|usage"]))
    window.objects.load(group)
    selector = window.objects.value()
    assert selector.resource_ids == ["id-a"]
    assert selector.csv_path is None and selector.csv_content is None
    assert window.objects.csv.edit.text() == ""
