"""Terminal ASCII table exporter for CLI display."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from ops_metric_harvest.exporters.base import to_wide_rows
from ops_metric_harvest.models import CollectionResult


def export_table(
    result: CollectionResult,
    stream: Optional[TextIO] = None,
    tz_name: str = "America/Chicago",
    max_rows: int = 100,
) -> None:
    """Print a clean formatted terminal table of wide-format metrics."""
    headers, rows = to_wide_rows(result.samples, tz_name)
    out = stream or sys.stdout

    if not headers or not rows:
        out.write("No metric data to display.\n")
        return

    # Compact columns for terminal: Name, TimeLocal, <Metrics>
    # Drop Group, ResourceKind, ResourceId, TimestampUTC if wide
    display_headers = ["Name", headers[5], *headers[6:]]
    display_rows = []
    for r in rows[:max_rows]:
        name = str(r[2])
        time_local = str(r[5])
        metric_vals = []
        for val in r[6:]:
            if val is None:
                metric_vals.append("")
            elif isinstance(val, float):
                metric_vals.append(f"{val:.2f}" if not val.is_integer() else f"{int(val):,}")
            else:
                metric_vals.append(str(val))
        display_rows.append([name, time_local, *metric_vals])

    # Calculate column widths
    col_widths = [len(h) for h in display_headers]
    for r in display_rows:
        for i, cell in enumerate(r):
            col_widths[i] = max(col_widths[i], len(cell))

    # Build border line
    sep = "  ".join("-" * w for w in col_widths)

    # Print header
    header_line = "  ".join(
        h.ljust(col_widths[i]) if i < 2 else h.rjust(col_widths[i])
        for i, h in enumerate(display_headers)
    )
    out.write(header_line + "\n")
    out.write(sep + "\n")

    for r in display_rows:
        row_line = "  ".join(
            cell.ljust(col_widths[i]) if i < 2 else cell.rjust(col_widths[i])
            for i, cell in enumerate(r)
        )
        out.write(row_line + "\n")

    if len(rows) > max_rows:
        out.write(f"\n... and {len(rows) - max_rows} more row(s). Export to CSV or XLSX to view full data.\n")
