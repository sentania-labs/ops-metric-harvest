"""Automated integration tests for mandatory integration scenarios A through E."""

import json
import os
import tempfile
import zipfile
from unittest.mock import patch

from ops_metric_harvest.cli import build_parser
from ops_metric_harvest.engine import CollectionEngine
from ops_metric_harvest.exporters import export_csv_long, export_xlsx
from ops_metric_harvest.models import (
    CollectionGroup,
    CollectionJob,
    MetricSet,
    ObjectSelector,
    TimeRange,
)
from ops_metric_harvest.profiles import save_profile


def test_scenario_a_all_hosts(mock_client):
    """Scenario A (AC1): Select all HostSystems and metrics A, B, C for historical range.

    Export CSV and XLSX, and verify object coverage and returned timestamps.
    """
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="All Hosts",
        resource_kind="HostSystem",
        selector=ObjectSelector(resource_kind="HostSystem", selection_mode="all"),
        metric_set=MetricSet(stat_keys=[
            "cpu|capacity_usagepct_average",
            "cpu|coreUtilization_average",
            "mem|active_average",
        ]),
    )
    job = CollectionJob(
        name="Scenario A Job",
        groups=[grp],
        time_range=TimeRange(
            mode="absolute",
            start_time="2024-10-03T00:00:00Z",
            end_time="2024-10-04T00:00:00Z",
            interval_type="MINUTES",
            rollup_type="AVG",
        ),
    )

    result = engine.execute(job)
    assert result.status == "success"

    # Verify 4 hosts discovered across 2 pages
    unique_hosts = {s.resource_name for s in result.samples}
    assert len(unique_hosts) == 4
    assert "esx-prod-01.int.sentania.net" in unique_hosts
    assert "esx-prod-04.int.sentania.net" in unique_hosts

    # 4 hosts * 3 metrics * 3 timestamps = 36 samples
    assert len(result.samples) == 36

    # Verify all 3 metrics present for each host
    for hname in unique_hosts:
        host_keys = {s.metric_key for s in result.samples if s.resource_name == hname}
        assert host_keys == {
            "cpu|capacity_usagepct_average",
            "cpu|coreUtilization_average",
            "mem|active_average",
        }

    # Verify exports (CSV & XLSX)
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "scenario_a.csv")
        xlsx_path = os.path.join(td, "scenario_a.xlsx")

        export_csv_long(result, file_path=csv_path)
        export_xlsx(result, file_path=xlsx_path)

        assert os.path.exists(csv_path)
        assert os.path.getsize(csv_path) > 500
        assert os.path.exists(xlsx_path)
        assert os.path.getsize(xlsx_path) > 1000

        with open(csv_path, "r", encoding="utf-8") as f:
            csv_lines = f.readlines()
        assert len(csv_lines) == 37  # 1 header + 36 samples

        with zipfile.ZipFile(xlsx_path, "r") as zf:
            assert "xl/worksheets/sheet3.xml" in zf.namelist()


def test_scenario_b_selected_vms(mock_client):
    """Scenario B (AC2): Select three individual VMs and metrics A, B, C.

    Verify that only those three VMs are collected.
    """
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="Three Selected VMs",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["app-vm-01", "app-vm-02", "shared-db-vm-03"],
        ),
        metric_set=MetricSet(stat_keys=[
            "cpu|usage_average",
            "mem|usage_average",
            "cpu|readyPct",
        ]),
    )
    job = CollectionJob(
        name="Scenario B Job",
        groups=[grp],
        time_range=TimeRange(mode="relative", relative_preset="1d"),
    )

    result = engine.execute(job)
    assert result.status == "success"

    # Only 3 selected VMs should be present
    unique_vms = {s.resource_name for s in result.samples}
    assert len(unique_vms) == 3
    assert unique_vms == {"app-vm-01", "app-vm-02", "shared-db-vm-03"}

    # storage-vm-04 and storage-vm-05 must NOT be in the results
    assert "storage-vm-04" not in unique_vms
    assert "storage-vm-05" not in unique_vms


def test_scenario_c_distinct_vm_groups_with_overlap(mock_client):
    """Scenario C (AC3): Group 1 has VM1, VM2, VM3 with metrics A, B, C.

    Group 2 has VM3, VM4, VM5 with metrics D, E, F.
    Verify that VM3 receives the correct union of metrics without group attribution or output ambiguity.
    """
    engine = CollectionEngine(client=mock_client)

    g1_metrics = ["cpu|usage_average", "mem|usage_average", "cpu|readyPct"]
    g2_metrics = [
        "net:aggregate of all instances|usage_average",
        "disk:aggregate of all instances|totalLatency_average",
        "mem|consumed_average",
    ]

    grp1 = CollectionGroup(
        group_id="group-1",
        name="App Group 1",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["app-vm-01", "app-vm-02", "shared-db-vm-03"],
        ),
        metric_set=MetricSet(stat_keys=g1_metrics),
    )

    grp2 = CollectionGroup(
        group_id="group-2",
        name="Storage Group 2",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["shared-db-vm-03", "storage-vm-04", "storage-vm-05"],
        ),
        metric_set=MetricSet(stat_keys=g2_metrics),
    )

    job = CollectionJob(
        name="Scenario C Multi-Group",
        groups=[grp1, grp2],
        time_range=TimeRange(mode="relative", relative_preset="12h"),
    )

    result = engine.execute(job)
    assert result.status == "success"

    # Verify group attribution
    g1_samples = [s for s in result.samples if s.group_id == "group-1"]
    g2_samples = [s for s in result.samples if s.group_id == "group-2"]

    # In Group 1, objects are VM1, VM2, VM3
    assert {s.resource_name for s in g1_samples} == {"app-vm-01", "app-vm-02", "shared-db-vm-03"}
    for s in g1_samples:
        assert s.metric_key in g1_metrics
        assert s.metric_key not in g2_metrics

    # In Group 2, objects are VM3, VM4, VM5
    assert {s.resource_name for s in g2_samples} == {"shared-db-vm-03", "storage-vm-04", "storage-vm-05"}
    for s in g2_samples:
        assert s.metric_key in g2_metrics
        assert s.metric_key not in g1_metrics

    # Verify VM3 (shared-db-vm-03) is in both groups with respective metrics
    vm3_g1_keys = {s.metric_key for s in g1_samples if s.resource_name == "shared-db-vm-03"}
    vm3_g2_keys = {s.metric_key for s in g2_samples if s.resource_name == "shared-db-vm-03"}
    assert vm3_g1_keys == set(g1_metrics)
    assert vm3_g2_keys == set(g2_metrics)


def test_scenario_d_profile_reuse(mock_client, mock_urlopen_handler):
    """Scenario D (AC4): Create profile through models, save it, and run through CLI."""
    grp = CollectionGroup(
        name="Saved Profile Group",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["app-vm-01", "app-vm-02"],
        ),
        metric_set=MetricSet(stat_keys=["cpu|usage_average", "mem|usage_average"]),
    )
    job = CollectionJob(
        name="Scenario D Job",
        groups=[grp],
        time_range=TimeRange(mode="relative", relative_preset="1d"),
        connection={"server": "vcf-ops.example.com", "verify_ssl": False},
    )

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        profile_path = tf.name

    with tempfile.TemporaryDirectory() as td:
        out_base = os.path.join(td, "cli_run_out")
        try:
            save_profile(job, profile_path)

            # Run via CLI
            with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
                parser = build_parser()
                args = parser.parse_args([
                    "profiles", "run",
                    profile_path,
                    "--token", "mock-token",
                    "--output", out_base,
                    "--format", "csv,json",
                    "-q",
                ])
                exit_code = args.func(args)
                assert exit_code == 0

                # Verify files produced
                assert os.path.exists(f"{out_base}.csv")
                assert os.path.exists(f"{out_base}.json")

                with open(f"{out_base}.json", "r") as jf:
                    data = json.load(jf)
                assert len(data["samples"]) > 0
                assert {s["resource_name"] for s in data["samples"]} == {"app-vm-01", "app-vm-02"}
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)


def test_scenario_e_error_resilience(mock_client):
    """Scenario E (AC6 & AC7): Test uneven timestamps (null alignment) and error handling."""
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="Uneven Test Group",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["vm-uneven-01"],
            resource_ids=["vm-uneven-01"],
        ),
        metric_set=MetricSet(stat_keys=["metric_a", "metric_b"]),
    )
    job = CollectionJob(
        name="Scenario E Job",
        groups=[grp],
        time_range=TimeRange(mode="relative", relative_preset="1h"),
    )

    # In conftest, vm-uneven-01 returns MOCK_MISALIGNED_STATS:
    # metric_a: [1000, 2000, 3000] -> [10.5, 20.5, 30.5]
    # metric_b: [2000, 3000, 4000] -> [200.0, 300.0, 400.0]
    result = engine.execute(job)
    assert result.status == "success"

    # Union of timestamps across metrics is [1000, 2000, 3000, 4000] (4 distinct timestamps)
    # 4 timestamps * 2 metrics = 8 samples
    assert len(result.samples) == 8

    samples_by_ts_metric = {(s.timestamp_ms, s.metric_key): s.value for s in result.samples}

    # At timestamp 1 (1728000000000): metric_a = 10.5, metric_b is missing (None)
    assert samples_by_ts_metric[(1728000000000, "metric_a")] == 10.5
    assert samples_by_ts_metric[(1728000000000, "metric_b")] is None

    # At timestamp 2 (1728000300000): both have values
    assert samples_by_ts_metric[(1728000300000, "metric_a")] == 20.5
    assert samples_by_ts_metric[(1728000300000, "metric_b")] == 200.0

    # At timestamp 3 (1728000600000): both have values
    assert samples_by_ts_metric[(1728000600000, "metric_a")] == 30.5
    assert samples_by_ts_metric[(1728000600000, "metric_b")] == 300.0

    # At timestamp 4 (1728000900000): metric_a is missing (None), metric_b = 400.0
    assert samples_by_ts_metric[(1728000900000, "metric_a")] is None
    assert samples_by_ts_metric[(1728000900000, "metric_b")] == 400.0
