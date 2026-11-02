"""Unit tests for CSV, JSON, XLSX, and Table exporters."""

import io
import json
import os
import tempfile
import zipfile

import pytest

from ops_metric_harvest.exporters import (
    export_csv_long,
    export_csv_wide,
    export_json,
    export_table,
    export_xlsx,
)
from ops_metric_harvest.exporters.base import sanitize_formula_injection
from ops_metric_harvest.models import CollectionResult, MetricSample


@pytest.fixture
def sample_result():
    s1 = MetricSample(
        group_id="g1",
        group_name="Group 1",
        resource_id="res-01",
        resource_name="esx-01",
        resource_kind="HostSystem",
        metric_key="cpu|usage",
        metric_name="CPU Usage",
        timestamp_ms=1728000000000,
        time_utc="2024-10-03T20:00:00Z",
        value=45.5,
        unit="%",
    )
    s2 = MetricSample(
        group_id="g1",
        group_name="Group 1",
        resource_id="res-01",
        resource_name="esx-01",
        resource_kind="HostSystem",
        metric_key="mem|usage",
        metric_name="Memory Usage",
        timestamp_ms=1728000000000,
        time_utc="2024-10-03T20:00:00Z",
        value=78.2,
        unit="%",
    )
    s3 = MetricSample(
        group_id="g1",
        group_name="Group 1",
        resource_id="res-01",
        resource_name="=MALICIOUS_FORMULA",
        resource_kind="HostSystem",
        metric_key="cpu|usage",
        metric_name="CPU Usage",
        timestamp_ms=1728000300000,
        time_utc="2024-10-03T20:05:00Z",
        value=50.0,
        unit="%",
    )
    return CollectionResult(
        job_name="Test Job",
        started_at_utc="2024-10-03T20:00:00Z",
        completed_at_utc="2024-10-03T20:05:00Z",
        status="success",
        samples=[s1, s2, s3],
        resolved_resources=[{"resourceId": "res-01", "name": "esx-01"}],
        errors=[],
        warnings=[],
        stats={"objects_processed": 1, "samples_retrieved": 3},
    )


def test_sanitize_formula_injection():
    assert sanitize_formula_injection("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert sanitize_formula_injection("+12345") == "'+12345"
    assert sanitize_formula_injection("-5+5") == "'-5+5"
    assert sanitize_formula_injection("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_formula_injection("Normal Text") == "Normal Text"
    assert sanitize_formula_injection(123.45) == 123.45


def test_csv_long_export(sample_result):
    buf = io.StringIO()
    export_csv_long(sample_result, stream=buf)
    content = buf.getvalue()
    lines = content.strip().splitlines()
    assert len(lines) == 4  # header + 3 samples
    assert "Group,ResourceKind,Name,ResourceId,MetricKey" in lines[0]
    # Check formula protection
    assert "'=MALICIOUS_FORMULA" in content


def test_csv_wide_export(sample_result):
    buf = io.StringIO()
    export_csv_wide(sample_result, stream=buf)
    content = buf.getvalue()
    lines = content.strip().splitlines()
    assert len(lines) == 3  # header + 2 timestamp rows
    headers = lines[0].split(",")
    assert "CPU Usage (%)" in headers[6]
    assert "Memory Usage (%)" in headers[7]


def test_json_export(sample_result):
    buf = io.StringIO()
    export_json(sample_result, stream=buf)
    data = json.loads(buf.getvalue())
    assert data["job_name"] == "Test Job"
    assert len(data["samples"]) == 3
    assert data["stats"]["objects_processed"] == 1


def test_xlsx_export(sample_result):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        tmp_path = tf.name

    try:
        export_xlsx(sample_result, tmp_path)
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 1000

        # Validate that output is a valid OpenXML ZipFile
        with zipfile.ZipFile(tmp_path, "r") as zf:
            namelist = zf.namelist()
            assert "[Content_Types].xml" in namelist
            assert "xl/workbook.xml" in namelist
            assert "xl/styles.xml" in namelist
            assert "xl/worksheets/sheet1.xml" in namelist  # Summary
            assert "xl/worksheets/sheet2.xml" in namelist  # Wide
            assert "xl/worksheets/sheet3.xml" in namelist  # Long
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_table_export(sample_result):
    buf = io.StringIO()
    export_table(sample_result, stream=buf)
    out = buf.getvalue()
    assert "esx-01" in out
    assert "TimeLocal" in out
