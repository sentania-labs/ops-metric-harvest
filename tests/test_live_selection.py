"""Live flow invariants through the real client, engine, profiles and native controls."""
import csv
import io
import json
from unittest.mock import patch

from PySide6.QtCore import Qt

from ops_metric_harvest.cli import build_parser
from ops_metric_harvest.client import OpsClient
from ops_metric_harvest.engine import CollectionEngine
from ops_metric_harvest.exporters.csv_export import export_csv_long, export_csv_wide
from ops_metric_harvest.gui.main_window import MainWindow
from ops_metric_harvest.models import CollectionGroup, CollectionJob, MetricSet, ObjectSelector, TimeRange
from ops_metric_harvest.profiles import load_profile, save_profile
from tests.fixtures.live_client import LiveClient


def group(selector, props=None):
    return CollectionGroup("Production", selector.resource_kind, selector,
                           MetricSet(["cpu|usage", "mem|usage"], property_keys=props or []))


def check_key(widget, key):
    for index in range(widget.count()):
        item = widget.item(index)
        if item.data(Qt.UserRole) == key:
            item.setCheckState(Qt.Checked)
            return
    raise AssertionError(key)


def test_one_page_is_one_request_and_count_is_filtered():
    client = LiveClient()
    page = client.resource_page("VirtualMachine", name_query="production-", page=1, page_size=20)
    assert len(client.calls) == 1
    assert page["total"] == 125 and len(page["resources"]) == 20
    assert page["resources"][0]["resourceId"] == "vm-020"
    assert page["has_next"]
    assert client.calls[0][2]["adapterKind"] == "VMWARE"
    assert "regex" in client.calls[0][2] and "name" not in client.calls[0][2]
    assert client.resource_page("VirtualMachine", name_query="production-000")["total"] == 1


def test_unknown_count_is_not_invented_and_empty_pages_stop():
    client = OpsClient("ops.example")
    raw = {"resourceList": [LiveClient.resource("one", "one")]}
    with patch.object(client, "_request", side_effect=[raw, {"resourceList": []}]) as request:
        assert client.search_resources("VirtualMachine", page_size=1)[0]["resourceId"] == "one"
        assert request.call_count == 2
    with patch.object(client, "_request", return_value=raw):
        assert client.resource_page("VirtualMachine")["total"] is None


def test_fixed_ids_dynamic_membership_adapter_scoping_and_ambiguity():
    client = LiveClient()
    engine = CollectionEngine(client)
    fixed = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000"]))
    objects, _, errors = engine.resolve_group_objects(fixed, {})
    assert [r["resourceId"] for r in objects] == ["vm-000"] and not errors
    assert client.calls[-1][2]["resourceId"] == ["vm-000"]
    dynamic = group(ObjectSelector("VirtualMachine", "search", search_query="production-"))
    assert len(engine.resolve_group_objects(dynamic, {})[0]) == 125
    client.inventory.append(client.resource("vm-new", "production-new"))
    assert len(engine.resolve_group_objects(dynamic, {})[0]) == 126
    assert len(engine.resolve_group_objects(fixed, {})[0]) == 1
    cache = {}
    other = group(ObjectSelector("VirtualMachine", "all", "OTHER"))
    engine.resolve_group_objects(group(ObjectSelector("VirtualMachine")), cache)
    assert [r["resourceId"] for r in engine.resolve_group_objects(other, cache)[0]] == ["other-01"]
    names = group(ObjectSelector("VirtualMachine", "explicit", names=["duplicate", "absent", "vm-000"]))
    objects, warnings, errors = engine.resolve_group_objects(names, {})
    assert [r["resourceId"] for r in objects] == ["vm-000"]
    assert len(errors) == 2
    assert any("Ambiguous" in w for w in warnings) and any("not found" in w for w in warnings)


def test_properties_current_values_missing_data_and_export_namespaces():
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000", "vm-001"]),
                     ["config|os", "missing"])
    result = CollectionEngine(client).execute(CollectionJob("mixed", [selected]))
    assert result.status == "success" and not result.errors
    props = [s for s in result.samples if s.field_type == "property"]
    assert {s.timestamp_basis for s in props} == {"collection"}
    assert [s.value for s in props] == ["Linux", None, "Linux", None]
    assert any("Missing property" in w for w in result.warnings)
    assert any(s.value is None and s.metric_key == "mem|usage" for s in result.samples)
    props[0].value = "=untrusted"
    assert "'=untrusted" in export_csv_long(result)
    # A property can share a key with a metric without overwriting the wide cell.
    props[0].metric_key = "cpu|usage"
    headers = next(csv.reader(io.StringIO(export_csv_wide(result))))
    assert any(h.startswith("Property (latest, collected at): cpu|usage") for h in headers)
    assert "FieldType" in next(csv.reader(io.StringIO(export_csv_long(result))))


def test_property_only_profile_cli_roundtrip_exports(tmp_path):
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000"]), ["config|os"])
    selected.metric_set.stat_keys.clear()
    job = CollectionJob("Property job", [selected], TimeRange(max_samples=7),
                        {"server": "ops.example", "password": "never-save", "token": "never-save"},
                        {"formats": ["csv", "csv_wide", "json"], "output_dir": str(tmp_path / "exports")})
    profile = tmp_path / "profile.json"
    save_profile(job, str(profile))
    payload = profile.read_text()
    assert "never-save" not in payload
    loaded, _ = load_profile(str(profile))
    assert loaded.to_dict() == json.loads(payload) and loaded.schema_version == "2.0"
    args = build_parser().parse_args(["profiles", "run", str(profile), "--quiet"])
    with patch("ops_metric_harvest.cli.get_client", return_value=client):
        assert args.func(args) == 0
    files = list((tmp_path / "exports").glob("harvest-*/*"))
    assert len(files) == 3 and all(p.stat().st_size for p in files)
    assert not any("/stats" in call[1] for call in client.calls)


def test_widget_page_selection_relationships_scopes_and_properties(qtbot, tmp_path):
    client = LiveClient()
    window = MainWindow(client_factory=lambda *a, **k: client)
    qtbot.addWidget(window)
    window.show()
    def wait():
        qtbot.waitUntil(lambda: window.task is None)
    window.connection.test.click()
    wait()
    window.nav.setCurrentRow(1)
    window.objects.query.setText("production-")
    window.objects.preview.click()
    wait()
    assert window.objects.matches.rowCount() == 50
    window.objects.matches.item(0, 0).setCheckState(Qt.Checked)
    window.objects.next_page.click()
    wait()
    window.objects.matches.item(0, 0).setCheckState(Qt.Checked)
    assert window.objects.value().resource_ids == ["vm-000", "vm-050"]
    window.objects.previous.click()
    wait()
    assert window.objects.matches.item(0, 0).checkState() == Qt.Checked
    window.objects.matches.setCurrentCell(0, 0)
    window.objects.parents.click()
    wait()
    assert window.objects.rows[0]["resourceKind"] == "HostSystem"
    window.nav.setCurrentRow(2)
    window.metrics.refresh.click()
    wait()
    check_key(window.metrics.list, "cpu|usage")
    check_key(window.metrics.properties, "config|os")
    window.metrics.filter.setText("unmatched")
    assert window.metrics.value().property_keys == ["config|os"]
    window.objects.kind.setCurrentText("HostSystem")
    window.objects.commit_scope()
    assert len(window.job.groups) == 2
    assert window.job.groups[0].metric_set.property_keys == ["config|os"]
    assert not window.metrics.value().property_keys
    window.group_picker.setCurrentIndex(0)
    assert window.objects.value().resource_ids == ["vm-000", "vm-050"]
    assert window.metrics.value().property_keys == ["config|os"]
    client.property_error = "HTTP 403: property catalogue access denied"
    window.metrics.refresh.click()
    wait()
    assert not window.metrics.tabs.isTabEnabled(1)
    assert "HTTP 403" in window.metrics.property_status.text()
    assert window.metrics.value().property_keys == ["config|os"]


def test_dynamic_review_counts_are_server_totals_and_profile_preserves_groups(qtbot, tmp_path):
    client = LiveClient()
    window = MainWindow(client_factory=lambda *a, **k: client)
    qtbot.addWidget(window)
    window.objects.query.setText("production-")
    window.objects.dynamic.setChecked(True)
    window.metrics.set_catalogue({"cpu|usage": {"name": "CPU"}}, ["cpu|usage"])
    window.nav.setCurrentRow(4)
    assert "last preview: unknown" in window.run_page.summary.toPlainText()
    window.run_page.refresh_counts.click()
    qtbot.waitUntil(lambda: window.task is None)
    assert "last preview: 125 objects" in window.run_page.summary.toPlainText()
    assert client.calls[-1][2]["pageSize"] == 1
    window.add_group()
    window.objects.selected = {"vm-000": "production-000"}
    window.metrics.set_properties({"config|os": {"name": "OS"}}, ["config|os"])
    path = tmp_path / "mixed.json"
    window.save_profile_path(path)
    window.load_profile_path(path)
    assert len(window.job.groups) == 2
    assert window.job.groups[0].selector.selection_mode == "search"
    assert window.job.groups[0].selector.search_query == "production-"
    assert window.job.groups[1].selector.resource_ids == ["vm-000"]
    assert window.job.groups[1].metric_set.property_keys == ["config|os"]


def test_properties_failure_is_reported_without_losing_metrics():
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000"]), ["config|os"])
    with patch.object(client, "get_resource_properties", side_effect=RuntimeError("Access denied")):
        result = CollectionEngine(client).execute(CollectionJob("mixed", [selected]))
    assert result.status == "partial" and result.errors
    assert any(s.value == 23.5 for s in result.samples if s.field_type == "metric")
    assert any(s.value is None for s in result.samples if s.field_type == "property")


def test_every_property_fetch_failing_is_an_error_and_progress_is_counted():
    client = LiveClient()
    only_props = CollectionGroup("Props", "VirtualMachine",
                                 ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000", "vm-001", "vm-002"]),
                                 MetricSet([], property_keys=["config|os"]))
    progress = []
    engine = CollectionEngine(client, progress_cb=lambda msg, done, total: progress.append((done, total)), max_workers=2)
    with patch.object(client, "get_resource_properties", side_effect=RuntimeError("Access denied")):
        result = engine.execute(CollectionJob("props", [only_props]))
    assert result.status == "error" and len(result.errors) == 3
    assert (3, 3) in progress


def test_property_fetch_cancellation_raises():
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000", "vm-001"]), ["config|os"])
    stop = {"now": False}
    engine = CollectionEngine(client, should_stop=lambda: stop["now"])
    real = client.get_resource_properties

    def cancelling(rid):
        stop["now"] = True
        return real(rid)

    with patch.object(client, "get_resource_properties", side_effect=cancelling):
        try:
            engine.execute(CollectionJob("cancel", [selected]))
        except Exception as exc:
            assert "cancelled" in str(exc).lower()
        else:
            raise AssertionError("cancellation was ignored")


def test_wide_export_repeats_latest_properties_on_every_metric_row():
    client = LiveClient()
    both = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000"]), ["config|os"])
    only_props = CollectionGroup("Props", "VirtualMachine", ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-001"]),
                                 MetricSet([], property_keys=["config|os"]))
    result = CollectionEngine(client).execute(CollectionJob("wide", [both, only_props]))
    metric_row_times = {s.timestamp_ms for s in result.samples if s.field_type == "metric"}
    assert metric_row_times
    rows = list(csv.DictReader(io.StringIO(export_csv_wide(result))))
    os_col = next(k for k in rows[0] if k.startswith("Property (latest, collected at): config|os"))
    cpu_col = next(k for k in rows[0] if k.startswith("cpu|usage"))
    combined = [r for r in rows if r["Group"] == "Production"]
    assert len(combined) == len(metric_row_times)
    assert all(r[os_col] == "Linux" and r[cpu_col] == "23.5" for r in combined)
    prop_only = [r for r in rows if r["Group"] == "Props"]
    assert len(prop_only) == 1 and prop_only[0][os_col] == "Linux" and prop_only[0][cpu_col] == ""


def test_cancel_during_fixed_id_lookup_is_not_reported_as_missing_objects():
    client = LiveClient()
    ids = [f"vm-{i:03}" for i in range(120)]
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=ids))
    requests = []
    real = client.resource_page

    def page(*args, **kwargs):
        requests.append(args)
        return real(*args, **kwargs)

    engine = CollectionEngine(client, should_stop=lambda: len(requests) >= 1)
    cache = {}
    with patch.object(client, "resource_page", side_effect=page):
        try:
            engine.resolve_group_objects(selected, cache)
        except Exception as exc:
            assert "cancelled" in str(exc).lower()
        else:
            raise AssertionError("cancellation returned a partial resolution")
    assert cache == {}


def test_cancel_during_dynamic_inventory_does_not_cache_partial_membership():
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "all"))
    seen = []
    real = client.resource_page

    def page(*args, **kwargs):
        seen.append(args)
        return real(*args, **kwargs)

    engine = CollectionEngine(client, should_stop=lambda: bool(seen))
    cache = {}
    with patch.object(client, "resource_page", side_effect=page):
        try:
            engine.resolve_group_objects(selected, cache)
        except Exception as exc:
            assert "cancelled" in str(exc).lower()
        else:
            raise AssertionError("cancellation returned a partial resolution")
    assert cache == {}


def test_fixed_id_lookup_failure_is_one_error_not_per_id_missing_objects():
    client = LiveClient()
    selected = group(ObjectSelector("VirtualMachine", "explicit", resource_ids=["vm-000", "vm-001"]))
    with patch.object(client, "resource_page", side_effect=RuntimeError("server down")):
        objects, warnings, errors = CollectionEngine(client).resolve_group_objects(selected, {})
    assert objects == [] and warnings == []
    assert len(errors) == 1 and "server down" in errors[0]["error"]


def test_checking_object_in_imported_selection_runs_the_checked_ids(qtbot):
    from ops_metric_harvest.gui.screens.objects import ObjectsPage
    page = ObjectsPage()
    qtbot.addWidget(page)
    # Profile carries an imported selector plus a previously picked ID.
    imported = ObjectSelector("VirtualMachine", "imported", csv_content="Name\nvm-000\n", resource_ids=["vm-001"])
    page.load(group(imported))
    assert page.value().selection_mode == "explicit"
    assert "replaces the imported list" in page.summary.text()
    page.show_matches({"resources": [{"name": "production-002", "resourceId": "vm-002", "adapterKind": "VMWARE",
                                      "resourceKind": "VirtualMachine"}], "page": 0, "total": 1, "has_next": False})
    page.matches.item(0, 0).setCheckState(Qt.Checked)
    selector = page.value()
    assert selector.selection_mode == "explicit" and selector.csv_content is None
    objects, _, errors = CollectionEngine(LiveClient()).resolve_group_objects(group(selector), {})
    assert "vm-002" in [r["resourceId"] for r in objects] and not errors
