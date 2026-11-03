"""Shared collection engine for VCF Operations Metrics Explorer."""

from __future__ import annotations

import csv
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ops_metric_harvest.client import OpsClient
from ops_metric_harvest.models import (
    CollectionGroup,
    CollectionJob,
    CollectionResult,
    MetricSample,
    iso_utc_from_ms,
)

logger = logging.getLogger("ops_metric_harvest.engine")


class EngineError(Exception):
    """Exception raised by collection engine."""


class CollectionEngine:
    """Coordinates inventory discovery, metric resolution, batched collection, and alignment."""

    def __init__(
        self,
        client: OpsClient,
        max_workers: int = 4,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ):
        self.client = client
        self.max_workers = max(1, max_workers)
        self.progress_cb = progress_cb or (lambda msg, done, total: None)
        self.should_stop = should_stop or (lambda: False)

    def _log(self, msg: str, done: int = 0, total: int = 0) -> None:
        self.progress_cb(msg, done, total)

    def resolve_group_objects(
        self,
        group: CollectionGroup,
        all_inventory_cache: Dict[Tuple[str, str], List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        """Resolve target objects for a collection group.

        Returns:
            Tuple of (resolved_objects, warnings, errors)
        """
        kind = group.resource_kind
        selector = group.selector
        mode = selector.selection_mode
        adapter = selector.adapter_kind or "VMWARE"
        cache_key = (adapter, kind)
        warnings: List[str] = []
        errors: List[Dict[str, Any]] = []

        # Populate inventory for kind
        inventory: List[Dict[str, Any]] = []

        if mode == "explicit" and selector.resource_ids and not selector.names:
            try:
                for offset in range(0, len(selector.resource_ids), 50):
                    if self.should_stop():
                        raise EngineError("Collection cancelled by user")
                    inventory.extend(self.client.search_resources(
                        kind, adapter_kind=adapter, resource_ids=selector.resource_ids[offset:offset + 50],
                        should_stop=self.should_stop))
            except Exception as exc:
                errors.append({"group": group.name, "error": str(exc)})
        elif mode == "search" and selector.search_query:
            self._log(f"Searching inventory for '{selector.search_query}' in kind '{kind}'...")
            try:
                inventory = self.client.search_resources(kind, name_query=selector.search_query, adapter_kind=adapter, should_stop=self.should_stop)
            except Exception as e:
                msg = f"Failed to search inventory for {kind}: {e}"
                errors.append({"group": group.name, "resource_kind": kind, "error": msg})
                return [], warnings, errors
        elif mode == "explicit" and selector.names and len(selector.names) <= 10 and not selector.resource_ids:
            if cache_key in all_inventory_cache:
                inventory = all_inventory_cache[cache_key]
            else:
                self._log(f"Resolving {len(selector.names)} explicit object(s) for kind '{kind}'...")
                targeted: List[Dict[str, Any]] = []
                for n in selector.names:
                    try:
                        matches = self.client.search_resources(kind, name_query=n.strip(), adapter_kind=adapter, should_stop=self.should_stop)
                        targeted.extend(matches)
                    except Exception as e:
                        logger.debug("Targeted lookup failed for %s: %s", n, e)
                # Deduplicate targeted matches by resourceId
                seen_target_ids: Set[str] = set()
                deduped_targeted: List[Dict[str, Any]] = []
                for r in targeted:
                    rid = r.get("resourceId")
                    if rid and rid not in seen_target_ids:
                        seen_target_ids.add(rid)
                        deduped_targeted.append(r)
                    elif not rid:
                        deduped_targeted.append(r)
                targeted = deduped_targeted

                # If all found, use targeted list; otherwise fall back to full discovery
                found_names = {r["name"].lower() for r in targeted}
                if all(n.strip().lower() in found_names for n in selector.names):
                    inventory = targeted
                else:
                    self._log(f"Discovering full inventory for resource kind '{kind}'...")
                    try:
                        all_inventory_cache[cache_key] = self.client.search_resources(kind, adapter_kind=adapter, should_stop=self.should_stop)
                        inventory = all_inventory_cache[cache_key]
                    except Exception as e:
                        msg = f"Failed to list inventory for {kind}: {e}"
                        errors.append({"group": group.name, "resource_kind": kind, "error": msg})
                        return [], warnings, errors
        else:
            if cache_key not in all_inventory_cache:
                self._log(f"Discovering inventory for resource kind '{kind}'...")
                try:
                    all_inventory_cache[cache_key] = self.client.search_resources(kind, adapter_kind=adapter, should_stop=self.should_stop)
                except Exception as e:
                    msg = f"Failed to list inventory for {kind}: {e}"
                    errors.append({"group": group.name, "resource_kind": kind, "error": msg})
                    return [], warnings, errors
            inventory = all_inventory_cache[cache_key]
        # Deduplicate inventory by resourceId
        deduped_inventory: List[Dict[str, Any]] = []
        seen_inv_ids: Set[str] = set()
        for r in inventory:
            if r.get("adapterKind") != adapter or r.get("resourceKind") != kind:
                continue
            rid = r.get("resourceId")
            if rid and rid not in seen_inv_ids:
                seen_inv_ids.add(rid)
                deduped_inventory.append(r)
            elif not rid:
                deduped_inventory.append(r)
        inventory = deduped_inventory

        name_to_resources: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        id_to_resource: Dict[str, Dict[str, Any]] = {}
        for res in inventory:
            name_to_resources[res["name"].lower()].append(res)
            id_to_resource[res["resourceId"]] = res

        resolved: List[Dict[str, Any]] = []

        if mode == "all":
            resolved = list(inventory)

        elif mode == "search":
            query = (selector.search_query or "").strip().lower()
            if not query:
                resolved = list(inventory)
            else:
                resolved = [r for r in inventory if query in r["name"].lower()]

        elif mode == "explicit":
            # Match by resource IDs first
            for rid in selector.resource_ids:
                if rid in id_to_resource:
                    resolved.append(id_to_resource[rid])
                else:
                    msg = f"Resource ID '{rid}' not found in {kind} inventory"
                    warnings.append(msg)
                    errors.append({"group": group.name, "resourceId": rid, "error": msg})

            # Match by object names or resource IDs
            for name in selector.names:
                clean_name = name.strip()
                if clean_name in id_to_resource:
                    if id_to_resource[clean_name] not in resolved:
                        resolved.append(id_to_resource[clean_name])
                    continue

                matches = name_to_resources.get(clean_name.lower(), [])
                if len(matches) == 1:
                    if matches[0] not in resolved:
                        resolved.append(matches[0])
                elif len(matches) > 1:
                    msg = f"Ambiguous name match: multiple objects named '{clean_name}' exist for kind '{kind}'"
                    warnings.append(msg)
                    errors.append({"group": group.name, "name": clean_name, "error": msg})
                else:
                    msg = f"Resource '{clean_name}' not found by name or ID in {kind} inventory"
                    warnings.append(msg)
                    errors.append({"group": group.name, "name": clean_name, "error": msg})

        elif mode == "imported":
            # Import from CSV content or file
            csv_lines: List[str] = []
            if selector.csv_content:
                csv_lines = selector.csv_content.strip().splitlines()
            elif selector.csv_path and os.path.exists(selector.csv_path):
                with open(selector.csv_path, "r", encoding="utf-8-sig") as f:
                    csv_lines = f.read().strip().splitlines()
            else:
                msg = f"Imported selection requested but no CSV content or file provided for group '{group.name}'"
                warnings.append(msg)
                errors.append({"group": group.name, "error": msg})
                return [], warnings, errors

            # Parse CSV robustly
            reader = csv.reader(csv_lines)
            raw_rows = [row for row in reader if row and any(cell.strip() for cell in row)]
            if not raw_rows:
                warnings.append(f"Imported CSV for group '{group.name}' is empty")
                return [], warnings, errors

            # Determine headers
            import re
            norm_header = [re.sub(r"[\s_\-\.\:]+", "", c.strip().lower()) for c in raw_rows[0]]
            data_start = 0
            name_idx = 0
            kind_idx = -1

            name_aliases = ("objectname", "name", "object", "vmname", "hostname", "resourcename", "resourceid", "id")
            kind_aliases = ("resourcekind", "kind", "objecttype", "resourcetype", "type")

            for alias in name_aliases:
                if alias in norm_header:
                    data_start = 1
                    name_idx = norm_header.index(alias)
                    break

            for alias in kind_aliases:
                if alias in norm_header:
                    kind_idx = norm_header.index(alias)
                    break

            for row in raw_rows[data_start:]:
                if not row or len(row) <= name_idx:
                    continue
                req_name = row[name_idx].strip()
                if not req_name:
                    continue

                req_kind = row[kind_idx].strip() if kind_idx >= 0 and len(row) > kind_idx else kind
                if req_kind.lower() != kind.lower():
                    continue

                # Check id_to_resource first (for UUID or resourceId columns)
                if req_name in id_to_resource:
                    if id_to_resource[req_name] not in resolved:
                        resolved.append(id_to_resource[req_name])
                    continue

                matches = name_to_resources.get(req_name.lower(), [])
                if len(matches) == 1:
                    if matches[0] not in resolved:
                        resolved.append(matches[0])
                elif len(matches) > 1:
                    msg = f"Ambiguous name match in CSV import: multiple objects named '{req_name}'"
                    warnings.append(msg)
                    errors.append({"group": group.name, "name": req_name, "error": msg})
                else:
                    msg = f"Imported resource '{req_name}' not found by name or ID in {kind} inventory"
                    warnings.append(msg)
                    errors.append({"group": group.name, "name": req_name, "error": msg})

        # Deduplicate resolved objects preserving order
        unique_resolved: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for r in resolved:
            rid = r["resourceId"]
            if rid not in seen_ids:
                seen_ids.add(rid)
                unique_resolved.append(r)

        return unique_resolved, warnings, errors

    def execute(self, job: CollectionJob) -> CollectionResult:
        """Execute a complete collection job across all groups."""
        start_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        start_mono = time.monotonic()
        all_warnings: List[str] = []
        all_errors: List[Dict[str, Any]] = []
        all_inventory_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        metric_catalogues: Dict[str, Dict[str, Dict[str, str]]] = {}

        if not job.groups:
            raise EngineError("Job contains no collection groups")

        self._log(f"Starting collection job '{job.name}' with {len(job.groups)} group(s)...")

        # Step 1: Resolve objects for each group
        group_objects: Dict[str, List[Dict[str, Any]]] = {}
        all_resolved_resources: Dict[str, Dict[str, Any]] = {}

        for group in job.groups:
            if self.should_stop():
                raise EngineError("Collection cancelled by user")

            objs, warns, errs = self.resolve_group_objects(group, all_inventory_cache)
            group_objects[group.group_id] = objs
            all_warnings.extend(warns)
            all_errors.extend(errs)

            for o in objs:
                all_resolved_resources[o["resourceId"]] = o

            self._log(f"Group '{group.name}' resolved {len(objs)} {group.resource_kind} object(s).")

        # Step 2: Resolve metric catalogues
        for group in job.groups:
            kind = group.resource_kind
            adapter = group.selector.adapter_kind or "VMWARE"
            cat_key = f"{adapter}:{kind}"
            if cat_key not in metric_catalogues:
                try:
                    cat = self.client.get_stat_keys(adapter, kind)
                    metric_catalogues[cat_key] = cat
                except Exception as e:
                    self._log(f"Could not load metric catalogue for {cat_key}: {e}")
                    metric_catalogues[cat_key] = {}

            cat = metric_catalogues[cat_key]
            # Update group metric_set metadata
            for sk in group.metric_set.stat_keys:
                if sk in cat:
                    group.metric_set.metadata[sk] = cat[sk]
                else:
                    if sk not in group.metric_set.metadata:
                        group.metric_set.metadata[sk] = {"name": sk, "unit": "", "description": ""}
                    all_warnings.append(f"Metric key '{sk}' not found in catalogue for {cat_key}")

        # Step 3: Build unified execution plan (deduplicating queries for resources shared across groups)
        # Map: resource_id -> set of all stat_keys needed for this resource
        resource_stats_needed: Dict[str, Set[str]] = defaultdict(set)
        for group in job.groups:
            stat_keys = set(group.metric_set.stat_keys)
            for obj in group_objects[group.group_id]:
                resource_stats_needed[obj["resourceId"]].update(stat_keys)

        total_resources = len(resource_stats_needed)
        if total_resources == 0:
            self._log("No resources to collect.")
            completed_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return CollectionResult(
                job_name=job.name,
                started_at_utc=start_time_utc,
                completed_at_utc=completed_at_utc,
                status="error" if all_errors else "success",
                samples=[],
                resolved_resources=list(all_resolved_resources.values()),
                errors=all_errors,
                warnings=all_warnings,
                stats={
                    "api_calls": self.client.api_call_count,
                    "elapsed_seconds": round(time.monotonic() - start_mono, 2),
                    "objects_processed": 0,
                    "metrics_processed": 0,
                    "samples_retrieved": 0,
                    "retry_count": self.client.retry_count,
                },
                metric_catalogues=metric_catalogues,
            )

        self._log(f"Constructed execution plan: {total_resources} unique resource(s) to query.")

        # Step 4: Execute metric collection
        # Calculate time range
        time_range = job.time_range
        begin_ms, end_ms = time_range.calculate_bounds()

        # Group resources by their set of stat keys to batch together where possible
        # Or partition by batch of resource IDs with the union of stat keys
        raw_stats_by_resource: Dict[str, Dict[str, Dict[int, Optional[float]]]] = defaultdict(lambda: defaultdict(dict))

        # We partition resources into batches of up to 40 resources
        batch_size = 40
        all_rids = list(resource_stats_needed.keys())

        total_batches = (len(all_rids) + batch_size - 1) // batch_size
        completed_resources = 0

        for b_idx in range(total_batches):
            if self.should_stop():
                self._log("Collection cancelled.")
                raise EngineError("Collection cancelled by user")

            chunk_rids = all_rids[b_idx * batch_size : (b_idx + 1) * batch_size]
            # Union of stat keys for this chunk
            chunk_stat_keys: Set[str] = set()
            for rid in chunk_rids:
                chunk_stat_keys.update(resource_stats_needed[rid])

            stat_keys_list = sorted(list(chunk_stat_keys))
            self._log(f"Fetching batch [{b_idx + 1}/{total_batches}] ({len(chunk_rids)} resources, {len(stat_keys_list)} metrics)...",
                      completed_resources, total_resources)

            try:
                if not stat_keys_list:
                    batch_res = {}
                elif time_range.max_samples and time_range.mode == "relative":
                    batch_res = self.client.get_resources_stats_latest(
                        chunk_rids, stat_keys_list, max_samples=time_range.max_samples
                    )
                else:
                    batch_res = self.client.get_resources_stats(
                        chunk_rids,
                        stat_keys_list,
                        begin_ms=begin_ms,
                        end_ms=end_ms,
                        interval_type=time_range.interval_type,
                        rollup_type=time_range.rollup_type,
                    )

                for rid, sdict in batch_res.items():
                    for sk, ts_dict in sdict.items():
                        raw_stats_by_resource[rid][sk].update(ts_dict)

            except Exception as e:
                msg = f"Failed to retrieve stats for batch {b_idx + 1}: {e}"
                all_errors.append({"batch": b_idx + 1, "error": msg})
                self._log(f"Batch error: {msg}")

            completed_resources += len(chunk_rids)
            self._log(f"Processed {completed_resources}/{total_resources} resources", completed_resources, total_resources)

        # Step 5: Normalize and build samples per group
        samples: List[MetricSample] = []
        total_samples_count = 0

        for group in job.groups:
            group_id = group.group_id
            group_name = group.name
            group_kind = group.resource_kind
            objs = group_objects.get(group_id, [])
            stat_keys = group.metric_set.stat_keys

            for obj in objs:
                rid = obj["resourceId"]
                rname = obj["name"]
                res_series = raw_stats_by_resource.get(rid, {})

                # Find all distinct timestamps across all requested stat keys for this resource
                all_ts = sorted({ts for sk in stat_keys for ts in res_series.get(sk, {})})

                # If no timestamps found, record that no data returned
                if stat_keys and not all_ts:
                    all_warnings.append(f"No metric data returned for resource '{rname}' in group '{group_name}'")

                for ts in all_ts:
                    iso_time = iso_utc_from_ms(ts)
                    for sk in stat_keys:
                        meta = group.metric_set.metadata.get(sk, {})
                        val = res_series.get(sk, {}).get(ts)
                        sample = MetricSample(
                            group_id=group_id,
                            group_name=group_name,
                            resource_id=rid,
                            resource_name=rname,
                            resource_kind=group_kind,
                            metric_key=sk,
                            metric_name=meta.get("name", sk),
                            timestamp_ms=ts,
                            time_utc=iso_time,
                            value=val,
                            unit=meta.get("unit", ""),
                        )
                        samples.append(sample)
                        total_samples_count += 1

        # Properties are current strings, independent of the historical metric range.
        property_values = {}
        for group in job.groups:
            keys = group.metric_set.property_keys
            if not keys:
                continue
            for obj in group_objects[group.group_id]:
                if self.should_stop():
                    raise EngineError("Collection cancelled by user")
                rid = obj["resourceId"]
                if rid not in property_values:
                    try:
                        values = self.client.get_resource_properties(rid)
                        property_values[rid] = (values, int(time.time() * 1000))
                    except Exception as exc:
                        all_errors.append({"resourceId": rid, "error": f"Properties: {exc}"})
                        property_values[rid] = ({}, int(time.time() * 1000))
                values, collected_ms = property_values[rid]
                for key in keys:
                    meta = group.metric_set.property_metadata.get(key, {})
                    if key not in values:
                        all_warnings.append(f"Missing property '{key}' for '{obj['name']}'")
                    samples.append(MetricSample(
                        group.group_id, group.name, rid, obj["name"], group.resource_kind,
                        key, meta.get("name", key), collected_ms, iso_utc_from_ms(collected_ms),
                        values.get(key), meta.get("unit", ""), "property", "collection"))
                self._log(f"Collected latest properties for {obj['name']}")
        missing = sum(sample.value is None for sample in samples)
        if missing:
            all_warnings.append(f"{missing} requested field values are missing")
        total_samples_count = len(samples)
        elapsed = round(time.monotonic() - start_mono, 2)
        status = "success"
        if all_errors and not samples:
            status = "error"
        elif all_errors or all_warnings:
            status = "partial"
        else:
            status = "success"

        self._log(f"Collection complete: {total_samples_count} sample(s) collected in {elapsed}s.")
        completed_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return CollectionResult(
            job_name=job.name,
            started_at_utc=start_time_utc,
            completed_at_utc=completed_at_utc,
            status=status,
            samples=samples,
            resolved_resources=list(all_resolved_resources.values()),
            errors=all_errors,
            warnings=all_warnings,
            stats={
                "api_calls": self.client.api_call_count,
                "elapsed_seconds": elapsed,
                "objects_processed": total_resources,
                "metrics_processed": len({sk for g in job.groups for sk in g.metric_set.stat_keys}),
                "samples_retrieved": total_samples_count,
                "retry_count": self.client.retry_count,
            },
            metric_catalogues=metric_catalogues,
        )
