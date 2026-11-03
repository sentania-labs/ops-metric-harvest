"""CSV exporter for VCF Operations metrics in long and wide formats."""

from __future__ import annotations

import csv
import io
from typing import Optional, TextIO

from ops_metric_harvest.exporters.base import (
    format_local_time,
    sanitize_formula_injection,
    to_wide_rows,
)
from ops_metric_harvest.models import CollectionResult


def export_csv_long(
    result: CollectionResult,
    stream: Optional[TextIO] = None,
    tz_name: str = "America/Chicago",
    file_path: Optional[str] = None,
) -> str:
    """Export metrics in canonical long format: one metric value per row."""
    headers = [
        "Group",
        "ResourceKind",
        "Name",
        "ResourceId",
        "MetricKey",
        "MetricName",
        "TimestampUTC",
        f"TimeLocal ({tz_name})",
        "Value",
        "Unit",
        "FieldType",
        "TimestampBasis",
    ]

    dest = stream
    close_stream = False
    if file_path:
        dest = open(file_path, "w", newline="", encoding="utf-8")
        close_stream = True
    elif dest is None:
        dest = io.StringIO()

    writer = csv.writer(dest)
    writer.writerow(headers)

    for s in result.samples:
        loc_time = format_local_time(s.timestamp_ms, tz_name)
        val_str = "" if s.value is None else s.value
        row = [
            sanitize_formula_injection(s.group_name),
            sanitize_formula_injection(s.resource_kind),
            sanitize_formula_injection(s.resource_name),
            sanitize_formula_injection(s.resource_id),
            sanitize_formula_injection(s.metric_key),
            sanitize_formula_injection(s.metric_name),
            s.time_utc,
            loc_time,
            sanitize_formula_injection(val_str),
            sanitize_formula_injection(s.unit),
            s.field_type,
            s.timestamp_basis,
        ]
        writer.writerow(row)

    if close_stream:
        dest.close()
        return file_path or ""
    elif isinstance(dest, io.StringIO):
        return dest.getvalue()
    return ""


def export_csv_wide(
    result: CollectionResult,
    stream: Optional[TextIO] = None,
    tz_name: str = "America/Chicago",
    file_path: Optional[str] = None,
) -> str:
    """Export metrics in wide format: one object/timestamp per row with metrics as columns."""
    headers, rows = to_wide_rows(result.samples, tz_name)

    dest = stream
    close_stream = False
    if file_path:
        dest = open(file_path, "w", newline="", encoding="utf-8")
        close_stream = True
    elif dest is None:
        dest = io.StringIO()

    writer = csv.writer(dest)
    writer.writerow(headers)

    for r in rows:
        cleaned_row = []
        for cell in r:
            if cell is None:
                cleaned_row.append("")
            else:
                cleaned_row.append(sanitize_formula_injection(cell))
        writer.writerow(cleaned_row)

    if close_stream:
        dest.close()
        return file_path or ""
    elif isinstance(dest, io.StringIO):
        return dest.getvalue()
    return ""
