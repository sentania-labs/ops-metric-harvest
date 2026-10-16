"""Collection profile persistence and schema validation."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from ops_metric_harvest.models import CollectionJob

CURRENT_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


class ProfileValidationError(Exception):
    """Exception raised when a profile fails validation."""


def validate_profile_dict(data: Dict[str, Any]) -> List[str]:
    """Validate a raw profile dictionary against schema rules.

    Returns:
        List of warning messages (if any). Raises ProfileValidationError on fatal errors.
    """
    warnings: List[str] = []

    # 1. Schema version check
    version = str(data.get("schema_version", ""))
    if not version:
        raise ProfileValidationError("Profile is missing 'schema_version' (expected '1.0')")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ProfileValidationError(f"Unsupported schema_version '{version}'. Supported: {sorted(list(SUPPORTED_SCHEMA_VERSIONS))}")

    # 2. Check for leaked secrets
    conn = data.get("connection", {})
    leaked = [k for k in ("password", "token", "Authorization") if k in conn or k in data]
    if leaked:
        warnings.append(f"Security warning: Profile contained secret keys ({', '.join(leaked)}). They will be stripped.")

    # 3. Check groups
    groups = data.get("groups", [])
    if not groups or not isinstance(groups, list):
        raise ProfileValidationError("Profile must define at least one collection group in 'groups'")

    for idx, grp in enumerate(groups):
        if not isinstance(grp, dict):
            raise ProfileValidationError(f"Group #{idx + 1} must be an object")

        grp_name = grp.get("name")
        if not grp_name:
            raise ProfileValidationError(f"Group #{idx + 1} is missing required 'name'")

        kind = grp.get("resource_kind")
        if not kind:
            raise ProfileValidationError(f"Group '{grp_name}' is missing required 'resource_kind'")

        selector = grp.get("selector", {})
        mode = selector.get("selection_mode", "all")
        if mode not in ("all", "search", "explicit", "imported"):
            raise ProfileValidationError(f"Group '{grp_name}' has invalid selection_mode '{mode}'")

        if mode == "explicit":
            rids = selector.get("resource_ids", [])
            names = selector.get("names", [])
            if not rids and not names:
                warnings.append(f"Group '{grp_name}' has explicit mode but no resource_ids or names specified")
        elif mode == "imported":
            csv_path = selector.get("csv_path")
            csv_content = selector.get("csv_content")
            if not csv_path and not csv_content:
                warnings.append(f"Group '{grp_name}' has imported mode but neither csv_path nor csv_content is provided")

        metric_set = grp.get("metric_set", {})
        stat_keys = metric_set.get("stat_keys", [])
        if not stat_keys:
            raise ProfileValidationError(f"Group '{grp_name}' must specify at least one stat key in metric_set.stat_keys")

    # 4. Check time range
    tr = data.get("time_range", {})
    mode = tr.get("mode", "relative")
    if mode not in ("relative", "absolute"):
        raise ProfileValidationError(f"Invalid time_range mode '{mode}'")

    if mode == "absolute":
        if not tr.get("start_time") or not tr.get("end_time"):
            raise ProfileValidationError("Absolute time_range requires 'start_time' and 'end_time'")

    return warnings


def load_profile(file_path: str) -> Tuple[CollectionJob, List[str]]:
    """Load and validate a collection job profile from a JSON or YAML file.

    Returns:
        Tuple of (CollectionJob, List of warnings)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Profile file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        if file_path.endswith((".yaml", ".yml")):
            try:
                import yaml
                data = yaml.safe_load(f)
            except ImportError:
                raise ProfileValidationError(
                    "PyYAML package is required to read YAML profiles. Install pyyaml or use JSON format."
                ) from None
            except Exception as e:
                raise ProfileValidationError(f"Malformed YAML in profile '{file_path}': {e}") from None
        else:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ProfileValidationError(f"Malformed JSON in profile '{file_path}': {e}") from None

    if not isinstance(data, dict):
        raise ProfileValidationError(f"Profile file '{file_path}' must contain a JSON/YAML object")

    warnings = validate_profile_dict(data)

    # Sanitize connection dict in data
    if "connection" in data:
        data["connection"] = {
            k: v for k, v in data["connection"].items()
            if k not in ("password", "token", "Authorization")
        }

    job = CollectionJob.from_dict(data)
    return job, warnings


def save_profile(job: CollectionJob, file_path: str) -> str:
    """Save a collection job profile to a JSON or YAML file, ensuring no secrets are stored."""
    payload = job.to_dict()
    # Enforce current schema version
    payload["schema_version"] = CURRENT_SCHEMA_VERSION

    # Write securely
    with open(file_path, "w", encoding="utf-8") as f:
        if file_path.endswith((".yaml", ".yml")):
            try:
                import yaml
                yaml.safe_dump(payload, f, sort_keys=False)
            except ImportError:
                raise ProfileValidationError(
                    "PyYAML package is required to write YAML profiles. Install pyyaml or use JSON format."
                ) from None
        else:
            json.dump(payload, f, indent=2)
            f.write("\n")

    return file_path
