"""Excel (.xlsx) exporter using Python standard library only (no openpyxl dependency)."""

from __future__ import annotations

import math
import re
import zipfile
from collections.abc import Iterable
from typing import Any, List, Tuple
from xml.sax.saxutils import escape

from ops_metric_harvest.exporters.base import (
    format_local_time,
    sanitize_formula_injection,
    to_wide_rows,
)
from ops_metric_harvest.models import CollectionResult

EXCEL_MAX_ROWS = 1_048_575  # Excel row limit minus header


class FastXlsxWriter:
    """Minimal, streaming OpenXML .xlsx generator with zero third-party dependencies."""

    STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2">
  <numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm:ss"/>
  <numFmt numFmtId="165" formatCode="#,##0.00"/>
</numFmts>
<fonts count="2">
  <font><sz val="10"/><name val="Segoe UI"/></font>
  <font><b/><sz val="10"/><name val="Segoe UI"/><color rgb="FF000000"/></font>
</fonts>
<fills count="3">
  <fill><patternFill patternType="none"/></fill>
  <fill><patternFill patternType="gray125"/></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFE2E8F0"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
  <border><left/><right/><top/><bottom/><diagonal/></border>
  <border>
    <left style="thin"><color rgb="FFCBD5E1"/></left>
    <right style="thin"><color rgb="FFCBD5E1"/></right>
    <top style="thin"><color rgb="FFCBD5E1"/></top>
    <bottom style="thin"><color rgb="FFCBD5E1"/></bottom>
    <diagonal/>
  </border>
</borders>
<cellStyleXfs count="1">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
</cellStyleXfs>
<cellXfs count="5">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>
  <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
  <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
  <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
  <xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
</cellXfs>
<cellStyles count="1">
  <cellStyle name="Normal" xfId="0" builtinId="0"/>
</cellStyles>
</styleSheet>"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.zf = zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED)
        self.sheets: List[str] = []
        self.filters: List[Tuple[str, str]] = []

    @staticmethod
    def col_to_letter(col_idx: int) -> str:
        """Convert 1-based column index to Excel column letters (A, B, ..., AA)."""
        letters = ""
        while col_idx > 0:
            col_idx, remainder = divmod(col_idx - 1, 26)
            letters = chr(65 + remainder) + letters
        return letters

    def add_sheet(
        self,
        name: str,
        headers: List[str],
        rows: Iterable[List[Any]],
        styles: List[int],
        widths: List[int],
    ) -> None:
        """Stream a worksheet into the zip file."""
        sheet_idx = len(self.sheets) + 1
        safe_name = name[:31].replace(":", "_").replace("/", "_").replace("\\", "_")
        self.sheets.append(safe_name)
        last_col = self.col_to_letter(len(headers))

        sheet_path = f"xl/worksheets/sheet{sheet_idx}.xml"
        with self.zf.open(sheet_path, "w") as f:
            def write(s: str) -> None:
                f.write(s.encode("utf-8"))

            write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
                  'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>')

            for i, width in enumerate(widths, 1):
                write(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
            write('</cols><sheetData>')

            # Header row (style 1 = bold, grey fill)
            write(self._format_row(1, headers, [1] * len(headers)))

            row_num = 1
            for row_num, row_data in enumerate(rows, 2):
                write(self._format_row(row_num, row_data, styles))

            ref = f"A1:{last_col}{max(row_num, 1)}"
            write(f'</sheetData><autoFilter ref="{ref}"/></worksheet>')

        abs_ref = re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", ref)
        self.filters.append((safe_name, abs_ref))

    def _format_row(self, row_idx: int, values: List[Any], styles: List[int]) -> str:
        parts = [f'<row r="{row_idx}">']
        for col_idx, (val, style_id) in enumerate(zip(values, styles), 1):
            cell_ref = f"{self.col_to_letter(col_idx)}{row_idx}"
            if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
                parts.append(f'<c r="{cell_ref}" s="{style_id}"/>')
                continue

            if isinstance(val, (int, float)) and not isinstance(val, bool):
                parts.append(f'<c r="{cell_ref}" s="{style_id}"><v>{val}</v></c>')
            else:
                # Text value with formula injection sanitization
                sanitized = sanitize_formula_injection(str(val))
                escaped = escape(str(sanitized))
                parts.append(f'<c r="{cell_ref}" s="{style_id}" t="inlineStr"><is><t>{escaped}</t></is></c>')

        parts.append("</row>")
        return "".join(parts)

    def close(self) -> None:
        """Write workbook manifests and close zip container."""
        n = len(self.sheets)
        z = self.zf

        # [Content_Types].xml
        content_types = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        ]
        for i in range(1, n + 1):
            content_types.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        content_types.append('</Types>')
        z.writestr("[Content_Types].xml", "".join(content_types))

        # _rels/.rels
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )

        # xl/workbook.xml
        wb_parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>',
        ]
        for i, sheet_name in enumerate(self.sheets, 1):
            wb_parts.append(f'<sheet name="{escape(sheet_name)}" sheetId="{i}" r:id="rId{i}"/>')
        wb_parts.append('</sheets><definedNames>')
        for i, (nm, ref) in enumerate(self.filters, 1):
            wb_parts.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i - 1}" hidden="1">\'{escape(nm)}\'!{ref}</definedName>')
        wb_parts.append('</definedNames></workbook>')
        z.writestr("xl/workbook.xml", "".join(wb_parts))

        # xl/_rels/workbook.xml.rels
        rels_parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        for i in range(1, n + 1):
            rels_parts.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        rels_parts.append(f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        rels_parts.append('</Relationships>')
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels_parts))

        # xl/styles.xml
        z.writestr("xl/styles.xml", self.STYLES_XML)
        z.close()


def export_xlsx(
    result: CollectionResult,
    file_path: str,
    tz_name: str = "America/Chicago",
) -> str:
    """Export collection result to multi-sheet Excel workbook."""
    writer = FastXlsxWriter(file_path)

    # 1. Summary sheet
    summary_headers = ["Property", "Value"]
    summary_rows = [
        ["Job Name", result.job_name],
        ["Status", result.status],
        ["Started (UTC)", result.started_at_utc],
        ["Completed (UTC)", result.completed_at_utc],
        ["Total Samples", len(result.samples)],
        ["Objects Processed", result.stats.get("objects_processed", 0)],
        ["API Calls", result.stats.get("api_calls", 0)],
        ["Elapsed (seconds)", result.stats.get("elapsed_seconds", 0.0)],
        ["Retry Count", result.stats.get("retry_count", 0)],
        ["Errors Count", len(result.errors)],
        ["Warnings Count", len(result.warnings)],
    ]
    writer.add_sheet("Summary", summary_headers, summary_rows, [0, 0], [25, 45])

    # 2. Wide format sheet
    wide_headers, wide_data = to_wide_rows(result.samples, tz_name)
    if wide_headers and wide_data:
        # Style 0 for text, 2 for dates, 3 for decimals/numbers
        styles = [0, 0, 0, 0, 0, 0] + [3] * (len(wide_headers) - 6)
        widths = [20, 20, 30, 38, 22, 22] + [min(35, max(15, len(h) + 2)) for h in wide_headers[6:]]
        if len(wide_data) <= EXCEL_MAX_ROWS:
            writer.add_sheet("Metrics_Wide", wide_headers, wide_data, styles, widths)
        else:
            # Sheet splitting if wide rows exceed max
            chunks = math.ceil(len(wide_data) / EXCEL_MAX_ROWS)
            for i in range(chunks):
                chunk = wide_data[i * EXCEL_MAX_ROWS : (i + 1) * EXCEL_MAX_ROWS]
                writer.add_sheet(f"Metrics_Wide_{i + 1}", wide_headers, chunk, styles, widths)

    # 3. Canonical Long format sheet
    long_headers = [
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
    long_styles = [0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0]
    long_widths = [20, 20, 30, 38, 30, 30, 22, 22, 16, 12, 12, 18]

    def long_row_generator():
        for s in result.samples:
            loc_time = format_local_time(s.timestamp_ms, tz_name)
            yield [
                s.group_name,
                s.resource_kind,
                s.resource_name,
                s.resource_id,
                s.metric_key,
                s.metric_name,
                s.time_utc,
                loc_time,
                s.value,
                s.unit,
                s.field_type,
                s.timestamp_basis,
            ]

    total_samples = len(result.samples)
    if total_samples <= EXCEL_MAX_ROWS:
        writer.add_sheet("Metrics_Long", long_headers, long_row_generator(), long_styles, long_widths)
    else:
        # Split into multiple sheets
        gen = long_row_generator()
        num_sheets = math.ceil(total_samples / EXCEL_MAX_ROWS)
        for i in range(1, num_sheets + 1):
            chunk = [next(gen) for _ in range(min(EXCEL_MAX_ROWS, total_samples - (i - 1) * EXCEL_MAX_ROWS))]
            writer.add_sheet(f"Metrics_Long_{i}", long_headers, chunk, long_styles, long_widths)

    writer.close()
    return file_path
