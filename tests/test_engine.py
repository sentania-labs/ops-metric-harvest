"""Unit tests for CollectionEngine."""

import pytest

from ops_metric_harvest.engine import CollectionEngine, EngineError
from ops_metric_harvest.models import (
    CollectionGroup,
    CollectionJob,
    MetricSet,
    ObjectSelector,
    TimeRange,
)


def test_engine_resolve_objects_all(mock_client):
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="All Hosts",
        resource_kind="HostSystem",
        selector=ObjectSelector(resource_kind="HostSystem", selection_mode="all"),
        metric_set=MetricSet(stat_keys=["cpu|capacity_usagepct_average"]),
    )
    cache = {}
    objs, warns, errs = engine.resolve_group_objects(grp, cache)
    assert len(objs) == 4
    assert not warns
    assert not errs


def test_engine_resolve_objects_search(mock_client):
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="Filtered VMs",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="search",
            search_query="app",
        ),
        metric_set=MetricSet(stat_keys=["cpu|usage_average"]),
    )
    cache = {}
    objs, warns, errs = engine.resolve_group_objects(grp, cache)
    assert len(objs) == 2
    names = [o["name"] for o in objs]
    assert "app-vm-01" in names
    assert "app-vm-02" in names


def test_engine_resolve_objects_csv_header_handling(mock_client):
    """Verify that CSV with headers does NOT parse the header row as a data record."""
    engine = CollectionEngine(client=mock_client)
    csv_text = "ObjectName,ResourceKind\napp-vm-01,VirtualMachine\napp-vm-02,VirtualMachine\n"
    grp = CollectionGroup(
        name="CSV VMs",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="imported",
            csv_content=csv_text,
        ),
        metric_set=MetricSet(stat_keys=["cpu|usage_average"]),
    )
    cache = {}
    objs, warns, errs = engine.resolve_group_objects(grp, cache)
    assert len(objs) == 2
    names = [o["name"] for o in objs]
    assert "ObjectName" not in names
    assert "app-vm-01" in names
    assert "app-vm-02" in names


def test_engine_resolve_objects_ambiguous_name(mock_client):
    """Verify ambiguous names (multiple objects sharing name) are flagged."""
    engine = CollectionEngine(client=mock_client)
    grp = CollectionGroup(
        name="Dup Test",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(
            resource_kind="VirtualMachine",
            selection_mode="explicit",
            names=["duplicate-vm"],
        ),
        metric_set=MetricSet(stat_keys=["cpu|usage_average"]),
    )
    # Supply duplicate inventory cache
    cache = {
        "VirtualMachine": [
            {"resourceId": "id-1", "name": "duplicate-vm", "adapterKind": "VMWARE", "resourceKind": "VirtualMachine"},
            {"resourceId": "id-2", "name": "duplicate-vm", "adapterKind": "VMWARE", "resourceKind": "VirtualMachine"},
        ]
    }
    objs, warns, errs = engine.resolve_group_objects(grp, cache)
    assert len(objs) == 0
    assert any("Ambiguous name match" in w for w in warns)


def test_engine_cancellation(mock_client):
    engine = CollectionEngine(client=mock_client, should_stop=lambda: True)
    grp = CollectionGroup(
        name="Test",
        resource_kind="HostSystem",
        selector=ObjectSelector(resource_kind="HostSystem", selection_mode="all"),
        metric_set=MetricSet(stat_keys=["cpu|capacity_usagepct_average"]),
    )
    job = CollectionJob(name="Cancel Job", groups=[grp], time_range=TimeRange())
    with pytest.raises(EngineError) as exc_info:
        engine.execute(job)
    assert "cancelled" in str(exc_info.value).lower()
