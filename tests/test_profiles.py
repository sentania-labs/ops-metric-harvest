"""Unit tests for profiles validation, loading, and saving."""

import os
import tempfile

import pytest

from ops_metric_harvest.models import (
    CollectionGroup,
    CollectionJob,
    MetricSet,
    ObjectSelector,
    TimeRange,
)
from ops_metric_harvest.profiles import (
    ProfileValidationError,
    load_profile,
    save_profile,
    validate_profile_dict,
)


def test_validate_profile_valid():
    valid_data = {
        "schema_version": "1.0",
        "name": "Valid Test Profile",
        "connection": {"server": "vcf-ops.example.com", "verify_ssl": True},
        "time_range": {"mode": "relative", "relative_preset": "7d"},
        "groups": [
            {
                "name": "Group 1",
                "resource_kind": "HostSystem",
                "selector": {"selection_mode": "all", "resource_kind": "HostSystem"},
                "metric_set": {"stat_keys": ["cpu|usage"]},
            }
        ],
    }
    warns = validate_profile_dict(valid_data)
    assert len(warns) == 0


def test_selector_csv_content_serialization():
    sel = ObjectSelector(
        resource_kind="VirtualMachine",
        selection_mode="imported",
        csv_content="ObjectName,ResourceKind\nvm-01,VirtualMachine\n",
    )
    d = sel.to_dict()
    assert d.get("csv_content") == "ObjectName,ResourceKind\nvm-01,VirtualMachine\n"

    sel2 = ObjectSelector.from_dict(d)
    assert sel2.csv_content == "ObjectName,ResourceKind\nvm-01,VirtualMachine\n"
    assert sel2.selection_mode == "imported"



def test_validate_profile_strips_secrets():
    data_with_secrets = {
        "schema_version": "1.0",
        "name": "Secret Leaked Profile",
        "connection": {"server": "vcf-ops.example.com", "password": "mypassword", "token": "mytoken"},
        "time_range": {"mode": "relative", "relative_preset": "7d"},
        "groups": [
            {
                "name": "Group 1",
                "resource_kind": "HostSystem",
                "selector": {"selection_mode": "all", "resource_kind": "HostSystem"},
                "metric_set": {"stat_keys": ["cpu|usage"]},
            }
        ],
    }
    warns = validate_profile_dict(data_with_secrets)
    assert any("Security warning" in w for w in warns)


def test_validate_profile_missing_schema_version():
    data = {
        "name": "No Version",
        "groups": [{"name": "G", "resource_kind": "HostSystem", "metric_set": {"stat_keys": ["cpu|usage"]}}],
    }
    with pytest.raises(ProfileValidationError) as exc:
        validate_profile_dict(data)
    assert "missing 'schema_version'" in str(exc.value)


def test_validate_profile_no_groups():
    data = {"schema_version": "1.0", "name": "Empty Groups", "groups": []}
    with pytest.raises(ProfileValidationError) as exc:
        validate_profile_dict(data)
    assert "at least one collection group" in str(exc.value)


def test_save_and_load_profile():
    grp = CollectionGroup(
        name="SaveLoad Group",
        resource_kind="VirtualMachine",
        selector=ObjectSelector(resource_kind="VirtualMachine", selection_mode="search", search_query="web"),
        metric_set=MetricSet(stat_keys=["cpu|usage_average", "mem|usage_average"]),
    )
    job = CollectionJob(
        name="SaveLoad Job",
        groups=[grp],
        time_range=TimeRange(mode="relative", relative_preset="1d"),
        connection={"server": "vcf-ops.example.com"},
    )

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name

    try:
        saved_path = save_profile(job, path)
        assert os.path.exists(saved_path)

        loaded_job, warns = load_profile(saved_path)
        assert loaded_job.name == "SaveLoad Job"
        assert len(loaded_job.groups) == 1
        assert loaded_job.groups[0].name == "SaveLoad Group"
        assert loaded_job.groups[0].selector.search_query == "web"
        assert loaded_job.groups[0].metric_set.stat_keys == ["cpu|usage_average", "mem|usage_average"]
        assert len(warns) == 0
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_yaml_save_and_load():
    pytest.importorskip("yaml")
    grp = CollectionGroup(
        name="YAML Group",
        resource_kind="HostSystem",
        selector=ObjectSelector(resource_kind="HostSystem", selection_mode="all"),
        metric_set=MetricSet(stat_keys=["cpu|usage"]),
    )
    job = CollectionJob(
        name="YAML Job",
        groups=[grp],
        time_range=TimeRange(mode="relative", relative_preset="7d"),
        connection={"server": "vcf-ops.example.com"},
    )

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tf:
        path = tf.name

    try:
        saved_path = save_profile(job, path)
        assert os.path.exists(saved_path)

        loaded_job, warns = load_profile(saved_path)
        assert loaded_job.name == "YAML Job"
        assert len(loaded_job.groups) == 1
        assert loaded_job.groups[0].resource_kind == "HostSystem"
        assert loaded_job.groups[0].metric_set.stat_keys == ["cpu|usage"]
        assert len(warns) == 0
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_yaml_missing_dependency_raises():
    from unittest.mock import patch

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tf:
        tf.write(b"dummy: true\n")
        path = tf.name

    try:
        with patch.dict("sys.modules", {"yaml": None}):
            with pytest.raises(ProfileValidationError) as exc_load:
                load_profile(path)
            assert "PyYAML" in str(exc_load.value)

            job = CollectionJob(name="Test", groups=[], time_range=TimeRange())
            with pytest.raises(ProfileValidationError) as exc_save:
                save_profile(job, path)
            assert "PyYAML" in str(exc_save.value)
    finally:
        if os.path.exists(path):
            os.remove(path)

