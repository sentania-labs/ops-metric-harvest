"""Base export utilities, formula sanitization, and time zone helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula_injection(value: Any) -> Any:
    """Protect spreadsheet cells against formula injection attacks."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(FORMULA_PREFIXES):
            # Prepend a single quote to force spreadsheet programs to treat it as plain text
            return "'" + value
    return value


def get_timezone(tz_name: str = "America/Chicago") -> Tuple[Any, str]:
    """Retrieve ZoneInfo object or fall back to UTC."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name), tz_name
    except Exception:
        return timezone.utc, "UTC"


def format_local_time(timestamp_ms: int, tz_name: str = "America/Chicago") -> str:
    """Format millisecond epoch timestamp in specified local time zone."""
    tz, _ = get_timezone(tz_name)
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def to_wide_rows(
    samples: List[Any],
    tz_name: str = "America/Chicago",
) -> Tuple[List[str], List[List[Any]]]:
    """Convert a list of MetricSample objects into wide format rows.

    Returns:
        Tuple of (headers, rows)
    """
    if not samples:
        return [], []

    def field_key(sample):
        return (sample.field_type, sample.metric_key)

    # Collect distinct metric keys preserving first-seen order
    metric_keys: List[str] = []
    metric_labels: Dict[str, str] = {}
    for s in samples:
        if field_key(s) not in metric_keys:
            metric_keys.append(field_key(s))
            if s.metric_name and s.metric_name != s.metric_key:
                lbl = f"{s.metric_key} | {s.metric_name} ({s.unit})" if s.unit else f"{s.metric_key} | {s.metric_name}"
            else:
                lbl = f"{s.metric_key} ({s.unit})" if s.unit else s.metric_key
            metric_labels[field_key(s)] = ("Property (latest, collected at): " if s.field_type == "property" else "") + lbl

    headers = [
        "Group",
        "ResourceKind",
        "Name",
        "ResourceId",
        "TimestampUTC",
        f"TimeLocal ({tz_name})",
        *[metric_labels[k] for k in metric_keys],
    ]

    # Group samples by (group_id, resource_id, timestamp_ms)
    row_map: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    row_meta: Dict[Tuple[str, str, int], Tuple[str, str, str, str, str, str]] = {}

    for s in samples:
        key = (s.group_id, s.resource_id, s.timestamp_ms)
        if key not in row_map:
            row_map[key] = {}
            loc_time = format_local_time(s.timestamp_ms, tz_name)
            row_meta[key] = (s.group_name, s.resource_kind, s.resource_name, s.resource_id, s.time_utc, loc_time)
        row_map[key][field_key(s)] = s.value

    # Build rows sorted by group_name, resource_name, timestamp_ms
    sorted_keys = sorted(row_map.keys(), key=lambda k: (row_meta[k][0], row_meta[k][2], k[2]))
    rows: List[List[Any]] = []
    for k in sorted_keys:
        meta = row_meta[k]
        values = [row_map[k].get(mkey) for mkey in metric_keys]
        rows.append([*meta, *values])

    return headers, rows
