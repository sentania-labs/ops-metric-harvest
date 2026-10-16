"""Data models for VCF Operations Metrics Explorer."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def iso_utc_from_ms(timestamp_ms: int) -> str:
    """Format millisecond epoch timestamp as ISO UTC string."""
    return datetime.fromtimestamp(timestamp_ms / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_duration_to_minutes(value: str) -> int:
    """Convert duration string (e.g. '30m', '12h', '7d', '2w') or bare days to minutes."""
    v = value.strip().lower()
    units = {"m": 1, "h": 60, "d": 1440, "w": 10080}
    try:
        if v[-1] in units:
            qty = float(v[:-1])
            mult = units[v[-1]]
        else:
            qty = float(v)
            mult = 1440  # bare number = days
    except (ValueError, IndexError):
        raise ValueError(f"Invalid duration '{value}' (use e.g. 30m, 12h, 1d, 7d, 2w)")
    if qty <= 0:
        raise ValueError("Duration must be greater than zero")
    return int(qty * mult)


@dataclass
class ConnectionConfig:
    server: str
    auth_type: str = "basic"  # "basic" or "token"
    username: Optional[str] = None
    password: Optional[str] = None  # Runtime only
    auth_source: Optional[str] = None
    token: Optional[str] = None  # Runtime only
    verify_ssl: bool = True
    timeout: int = 120
    retries: int = 3

    def sanitized_dict(self) -> Dict[str, Any]:
        """Return safe representation without secrets."""
        return {
            "server": self.server,
            "auth_type": self.auth_type,
            "username": self.username,
            "auth_source": self.auth_source,
            "verify_ssl": self.verify_ssl,
            "timeout": self.timeout,
            "retries": self.retries,
        }


@dataclass
class ObjectSelector:
    resource_kind: str
    selection_mode: str = "all"  # "all", "search", "explicit", "imported"
    adapter_kind: Optional[str] = "VMWARE"
    search_query: Optional[str] = None
    resource_ids: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    csv_path: Optional[str] = None
    csv_content: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "resource_kind": self.resource_kind,
            "selection_mode": self.selection_mode,
            "adapter_kind": self.adapter_kind or "VMWARE",
        }
        if self.search_query:
            d["search_query"] = self.search_query
        if self.resource_ids:
            d["resource_ids"] = list(self.resource_ids)
        if self.names:
            d["names"] = list(self.names)
        if self.csv_path:
            d["csv_path"] = self.csv_path
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ObjectSelector:
        return cls(
            resource_kind=data.get("resource_kind", "VirtualMachine"),
            selection_mode=data.get("selection_mode", "all"),
            adapter_kind=data.get("adapter_kind", "VMWARE"),
            search_query=data.get("search_query"),
            resource_ids=list(data.get("resource_ids", [])),
            names=list(data.get("names", [])),
            csv_path=data.get("csv_path"),
        )


@dataclass
class MetricSet:
    stat_keys: List[str] = field(default_factory=list)
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stat_keys": list(self.stat_keys),
            "metadata": {k: dict(v) for k, v in self.metadata.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MetricSet:
        keys = data.get("stat_keys", [])
        meta = data.get("metadata", {})
        return cls(stat_keys=list(keys), metadata=dict(meta))


@dataclass
class CollectionGroup:
    name: str
    resource_kind: str
    selector: ObjectSelector
    metric_set: MetricSet
    group_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    query_overrides: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "resource_kind": self.resource_kind,
            "selector": self.selector.to_dict(),
            "metric_set": self.metric_set.to_dict(),
            "query_overrides": dict(self.query_overrides),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollectionGroup:
        selector = ObjectSelector.from_dict(data.get("selector", {"resource_kind": data.get("resource_kind", "VirtualMachine")}))
        metric_set = MetricSet.from_dict(data.get("metric_set", {}))
        return cls(
            group_id=data.get("group_id", str(uuid.uuid4())[:8]),
            name=data.get("name", "Default Group"),
            resource_kind=data.get("resource_kind", selector.resource_kind),
            selector=selector,
            metric_set=metric_set,
            query_overrides=dict(data.get("query_overrides", {})),
        )


@dataclass
class TimeRange:
    mode: str = "relative"  # "relative" or "absolute"
    relative_preset: str = "7d"
    start_time: Optional[str] = None  # ISO 8601 UTC
    end_time: Optional[str] = None  # ISO 8601 UTC
    interval_minutes: int = 5
    interval_type: str = "MINUTES"  # MINUTES, HOURS, DAYS, WEEKS, MONTHS, YEARS, NONE
    rollup_type: str = "AVG"  # AVG, SUM, MIN, MAX, NONE, LATEST, COUNT
    max_samples: Optional[int] = None

    def calculate_bounds(self, reference_time: Optional[datetime] = None) -> tuple[int, int]:
        """Calculate start and end timestamps in milliseconds since Unix epoch."""
        ref = reference_time or datetime.now(timezone.utc)
        if self.mode == "absolute":
            if not self.start_time or not self.end_time:
                raise ValueError("start_time and end_time required for absolute time range")
            dt_start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            dt_end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            start_ms = int(dt_start.timestamp() * 1000)
            end_ms = int(dt_end.timestamp() * 1000)
            if start_ms >= end_ms:
                raise ValueError(f"start_time ({self.start_time}) must be before end_time ({self.end_time})")
            return start_ms, end_ms

        # Relative range
        mins = parse_duration_to_minutes(self.relative_preset)
        end_ms = int(ref.timestamp() * 1000)
        start_ms = end_ms - (mins * 60 * 1000)
        return start_ms, end_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "relative_preset": self.relative_preset,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "interval_minutes": self.interval_minutes,
            "interval_type": self.interval_type,
            "rollup_type": self.rollup_type,
            "max_samples": self.max_samples,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimeRange:
        return cls(
            mode=data.get("mode", "relative"),
            relative_preset=data.get("relative_preset", "7d"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            interval_minutes=int(data.get("interval_minutes", 5)),
            interval_type=data.get("interval_type", "MINUTES"),
            rollup_type=data.get("rollup_type", "AVG"),
            max_samples=int(data["max_samples"]) if data.get("max_samples") is not None else None,
        )


@dataclass
class CollectionJob:
    name: str
    groups: List[CollectionGroup] = field(default_factory=list)
    time_range: TimeRange = field(default_factory=TimeRange)
    connection: Dict[str, Any] = field(default_factory=dict)
    export_config: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        # Strip any credentials if inadvertently present
        safe_conn = {
            k: v for k, v in self.connection.items()
            if k not in ("password", "token", "Authorization")
        }
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "connection": safe_conn,
            "time_range": self.time_range.to_dict(),
            "groups": [g.to_dict() for g in self.groups],
            "export_config": dict(self.export_config),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollectionJob:
        groups = [CollectionGroup.from_dict(g) for g in data.get("groups", [])]
        time_range = TimeRange.from_dict(data.get("time_range", {}))
        safe_conn = {
            k: v for k, v in data.get("connection", {}).items()
            if k not in ("password", "token", "Authorization")
        }
        return cls(
            name=data.get("name", "Default Collection Job"),
            schema_version=data.get("schema_version", "1.0"),
            connection=safe_conn,
            groups=groups,
            time_range=time_range,
            export_config=dict(data.get("export_config", {})),
        )


@dataclass
class MetricSample:
    group_id: str
    group_name: str
    resource_id: str
    resource_name: str
    resource_kind: str
    metric_key: str
    metric_name: str
    timestamp_ms: int
    time_utc: str
    value: Optional[float]
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "resource_kind": self.resource_kind,
            "metric_key": self.metric_key,
            "metric_name": self.metric_name,
            "timestamp_ms": self.timestamp_ms,
            "time_utc": self.time_utc,
            "value": self.value,
            "unit": self.unit,
        }


@dataclass
class CollectionResult:
    job_name: str
    started_at_utc: str
    completed_at_utc: str
    status: str  # "success", "partial", "cancelled", "error"
    samples: List[MetricSample] = field(default_factory=list)
    resolved_resources: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    metric_catalogues: Dict[str, Dict[str, Dict[str, str]]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_name": self.job_name,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "status": self.status,
            "stats": self.stats,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "resolved_resources": list(self.resolved_resources),
            "samples": [s.to_dict() for s in self.samples],
            "metric_catalogues": self.metric_catalogues,
        }
