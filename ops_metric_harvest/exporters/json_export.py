"""JSON exporter for VCF Operations metrics."""

from __future__ import annotations

import json
from typing import Optional, TextIO

from ops_metric_harvest.models import CollectionResult


def export_json(
    result: CollectionResult,
    stream: Optional[TextIO] = None,
    file_path: Optional[str] = None,
    indent: int = 2,
) -> str:
    """Export collection result as structured JSON."""
    payload = result.to_dict()

    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=indent)
            f.write("\n")
        return file_path

    if stream is not None:
        json.dump(payload, stream, indent=indent)
        stream.write("\n")
        return ""

    return json.dumps(payload, indent=indent) + "\n"
