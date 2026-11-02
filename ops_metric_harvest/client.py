"""VCF Operations Suite API client with robust authentication, pagination, and retry logic."""

from __future__ import annotations

import json
import logging
import math
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops_metric_harvest.client")


def safe_float(val: Any) -> Optional[float]:
    """Safely convert value to float, returning None for blanks, nulls, or invalid data."""
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            f = float(val)
        else:
            s = str(val).strip()
            if not s or s.lower() in ("n/a", "null", "none", "nan", "inf", "-inf", "infinity", "-infinity"):
                return None
            f = float(s)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


class OpsClientError(Exception):
    """Base exception for OpsClient errors."""


class OpsAuthError(OpsClientError):
    """Authentication or authorization failure."""


class OpsClient:
    """HTTP client for VMware Cloud Foundation Operations (formerly Aria Operations / vROps)."""

    def __init__(
        self,
        server: str,
        token: Optional[str] = None,
        verify: bool = True,
        timeout: int = 120,
        retries: int = 3,
        token_prefix: str = "OpsToken",
    ):
        if not server:
            raise ValueError("Server FQDN or IP is required")

        server_clean = server.strip().rstrip("/")
        if server_clean.endswith("/suite-api/api"):
            server_clean = server_clean[:-len("/suite-api/api")].rstrip("/")
        if not server_clean.startswith(("http://", "https://")):
            server_clean = "https://" + server_clean
        self.server = server_clean
        self.base_url = server_clean.rstrip("/") + "/suite-api/api"
        self.verify = verify
        self.timeout = timeout
        self.retries = retries
        self.token_prefix = token_prefix
        self.token = token

        # Statistics
        self.api_call_count = 0
        self.retry_count = 0

        # SSL context
        self.ctx = ssl.create_default_context()
        if not verify:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
            sys.stderr.write("WARNING: TLS certificate verification is disabled. Connection is insecure.\n")
            sys.stderr.flush()

        self.headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-vRealizeOps-API-use-unsupported": "true",
        }
        if token:
            self.set_token(token)

    def set_token(self, token: str) -> None:
        """Set or update the authorization token."""
        self.token = token.strip()
        self.headers["Authorization"] = f"{self.token_prefix} {self.token}"

    def _redact(self, text: str) -> str:
        """Redact tokens, passwords, and sensitive headers from strings."""
        if not text:
            return ""
        redacted = text
        if self.token:
            redacted = redacted.replace(self.token, "[REDACTED_TOKEN]")
        # Redact password patterns
        redacted = re.sub(r'(["\']?password["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\1[REDACTED]\3', redacted, flags=re.IGNORECASE)
        redacted = re.sub(r'(Authorization:\s*(?:OpsToken|vRealizeOpsToken|Bearer|Basic)\s+)([^\r\n]+)', r'\1[REDACTED]', redacted, flags=re.IGNORECASE)
        return redacted

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
    ) -> Any:
        """Perform an HTTP request with retry logic and error sanitization."""
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"

        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(1, self.retries + 1):
            self.api_call_count += 1
            req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
            try:
                kw: Dict[str, Any] = {"timeout": self.timeout}
                if url.startswith("https://"):
                    kw["context"] = self.ctx

                with urllib.request.urlopen(req, **kw) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    resp_bytes = response.read()
                    if not resp_bytes:
                        return {}
                    return json.loads(resp_bytes.decode(charset))

            except urllib.error.HTTPError as e:
                # Do not retry 401 or 403 auth errors
                if e.code in (401, 403):
                    raw = e.read().decode("utf-8", "replace")[:300]
                    clean = self._redact(raw)
                    msg = "Unauthorized: Invalid credentials or expired token" if e.code == 401 else "Forbidden: Access denied"
                    raise OpsAuthError(f"HTTP {e.code} on {method} {path}: {msg}. Details: {clean}") from None

                # Retry on 429 (rate limiting) or 5xx server errors
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    self.retry_count += 1
                    retry_after = e.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = min(float(retry_after), 30.0)
                    else:
                        sleep_time = (2.0 ** attempt) + random.uniform(0.1, 0.5)
                    time.sleep(sleep_time)
                    continue

                raw = e.read().decode("utf-8", "replace")[:400]
                clean = self._redact(raw)
                raise OpsClientError(f"HTTP {e.code} on {method} {path}: {clean}") from None

            except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as e:
                if isinstance(e, ssl.SSLCertVerificationError) or "certificate verify failed" in str(e):
                    raise OpsClientError(f"TLS certificate verification failed connecting to {self.server}. Use --insecure to bypass.") from None

                if attempt == self.retries:
                    clean = self._redact(str(e))
                    raise OpsClientError(f"Network error on {method} {path} after {self.retries} attempts: {clean}") from None

                self.retry_count += 1
                time.sleep((2.0 ** attempt) + random.uniform(0.1, 0.5))

        raise OpsClientError(f"Request failed on {method} {path}")

    def login(self, username: str, password: str, auth_source: Optional[str] = None) -> str:
        """Authenticate with username and password, returning and caching OpsToken."""
        if not username or not password:
            raise ValueError("Username and password are required for login")

        body: Dict[str, Any] = {"username": username, "password": password}
        if auth_source:
            body["authSource"] = auth_source

        # Request token
        data = self._request("POST", "/auth/token/acquire", body=body)
        token = data.get("token")
        if not token:
            raise OpsAuthError("Server response did not contain an authentication token")

        self.set_token(token)
        return token

    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity and authentication status."""
        try:
            data = self._request("GET", "/versions")
            return {"status": "ok", "version_info": data}
        except Exception:
            # Fallback to checking resources endpoint
            data = self._request("GET", "/resources", params={"pageSize": 1, "_no_links": "true"})
            return {"status": "ok", "sample_resources": data}

    def list_resource_kinds(self, adapter_kind: str = "VMWARE") -> List[str]:
        """Discover resource kinds supported by the server."""
        try:
            path = f"/adapterkinds/{urllib.parse.quote(adapter_kind, safe='')}/resourcekinds"
            data = self._request("GET", path, params={"_no_links": "true"})
            kinds = []
            for item in data.get("resourceKind", []) or []:
                k = item.get("resourceKindKey") or item.get("key")
                if k:
                    kinds.append(k)
            if kinds:
                return sorted(kinds)
        except Exception as e:
            logger.debug("Failed to list resource kinds from adapter: %s", e)

        # Fallback to common standard resource kinds
        return ["ClusterComputeResource", "Datastore", "HostSystem", "VirtualMachine"]

    def search_resources(
        self,
        resource_kind: str,
        name_query: Optional[str] = None,
        page_size: int = 1000,
        max_resources: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Paginated resource discovery for a specific resource kind."""
        resources: List[Dict[str, Any]] = []
        page = 0

        while True:
            params: Dict[str, Any] = {
                "resourceKind": resource_kind,
                "page": page,
                "pageSize": page_size,
                "_no_links": "true",
            }
            if name_query:
                params["name"] = name_query

            data = self._request("GET", "/resources", params=params)
            batch = data.get("resourceList", []) or []

            for res in batch:
                identifier = res.get("identifier")
                res_key = res.get("resourceKey", {})
                name = res_key.get("name") or identifier
                adapter_kind = res_key.get("adapterKindKey")
                res_kind_key = res_key.get("resourceKindKey") or resource_kind

                # Filter client-side if name_query provided (in case API doesn't filter exactly)
                if name_query and name_query.lower() not in name.lower():
                    continue

                resources.append({
                    "resourceId": identifier,
                    "name": name,
                    "adapterKind": adapter_kind,
                    "resourceKind": res_kind_key,
                })

                if max_resources and len(resources) >= max_resources:
                    return resources

            page_info = data.get("pageInfo", {})
            total_count = page_info.get("totalCount", len(resources))

            page += 1
            if len(resources) >= total_count or not batch:
                break

        return resources

    def get_stat_keys(self, adapter_kind: str, resource_kind: str) -> Dict[str, Dict[str, str]]:
        """Retrieve metric catalogue for an adapter and resource kind."""
        path = (
            f"/adapterkinds/{urllib.parse.quote(adapter_kind, safe='')}"
            f"/resourcekinds/{urllib.parse.quote(resource_kind, safe='')}/statkeys"
        )
        try:
            data = self._request("GET", path, params={"_no_links": "true"})
        except Exception as e:
            logger.warning("Could not load stat keys for %s/%s: %s", adapter_kind, resource_kind, e)
            return {}

        catalogue: Dict[str, Dict[str, str]] = {}
        for attr in data.get("resourceTypeAttributes", []) or []:
            key = attr.get("key")
            if key:
                catalogue[key] = {
                    "name": attr.get("name") or key,
                    "unit": attr.get("unit") or "",
                    "description": attr.get("description") or "",
                }
        return catalogue

    def get_resources_stats(
        self,
        resource_ids: List[str],
        stat_keys: List[str],
        begin_ms: int,
        end_ms: int,
        interval_type: str = "MINUTES",
        rollup_type: str = "AVG",
        chunk_size: int = 50,
    ) -> Dict[str, Dict[str, Dict[int, Optional[float]]]]:
        """Retrieve historical batched metrics for multiple resources.

        Returns:
            Dict[resource_id, Dict[stat_key, Dict[timestamp_ms, value]]]
        """
        if not resource_ids or not stat_keys:
            return {}

        results: Dict[str, Dict[str, Dict[int, Optional[float]]]] = {rid: {} for rid in resource_ids}

        # Chunk resource IDs to avoid HTTP 414 URL length limits
        for i in range(0, len(resource_ids), chunk_size):
            chunk_rids = resource_ids[i : i + chunk_size]
            params: Dict[str, Any] = {
                "begin": begin_ms,
                "end": end_ms,
                "intervalType": interval_type.upper(),
                "rollUpType": rollup_type.upper(),
                "resourceId": chunk_rids,
                "statKey": stat_keys,
                "_no_links": "true",
            }

            try:
                data = self._request("GET", "/resources/stats", params=params)
                self._parse_stats_response(data, results)
            except Exception as e:
                logger.warning(
                    "Batched stats failed for chunk of %d resources (%s). Falling back to per-resource queries.",
                    len(chunk_rids),
                    e,
                )
                failed_rids: List[str] = []
                last_err = e
                # Fallback to single-resource queries for this chunk
                for single_rid in chunk_rids:
                    single_params: Dict[str, Any] = {
                        "begin": begin_ms,
                        "end": end_ms,
                        "intervalType": interval_type.upper(),
                        "rollUpType": rollup_type.upper(),
                        "resourceId": [single_rid],
                        "statKey": stat_keys,
                        "_no_links": "true",
                    }
                    try:
                        s_data = self._request("GET", "/resources/stats", params=single_params)
                        self._parse_stats_response(s_data, results)
                    except Exception as s_err:
                        logger.error("Failed to retrieve stats for single resource %s: %s", single_rid, s_err)
                        failed_rids.append(single_rid)
                        last_err = s_err

                if len(failed_rids) == len(chunk_rids):
                    raise OpsClientError(
                        f"Failed to retrieve stats for all {len(chunk_rids)} resources in chunk: {last_err}"
                    ) from last_err

        return results

    def get_resources_stats_latest(
        self,
        resource_ids: List[str],
        stat_keys: List[str],
        max_samples: int = 288,
        chunk_size: int = 50,
    ) -> Dict[str, Dict[str, Dict[int, Optional[float]]]]:
        """Retrieve latest N samples for multiple resources using /resources/stats/latest."""
        if not resource_ids or not stat_keys:
            return {}

        results: Dict[str, Dict[str, Dict[int, Optional[float]]]] = {rid: {} for rid in resource_ids}

        for i in range(0, len(resource_ids), chunk_size):
            chunk_rids = resource_ids[i : i + chunk_size]
            params: Dict[str, Any] = {
                "resourceId": chunk_rids,
                "statKey": stat_keys,
                "maxSamples": max_samples,
                "_no_links": "true",
            }

            try:
                data = self._request("GET", "/resources/stats/latest", params=params)
                self._parse_stats_response(data, results)
            except Exception as e:
                logger.warning("Batched stats/latest failed (%s), falling back to single resource requests.", e)
                failed_rids = []
                last_err = e
                for single_rid in chunk_rids:
                    s_params: Dict[str, Any] = {
                        "resourceId": [single_rid],
                        "statKey": stat_keys,
                        "maxSamples": max_samples,
                        "_no_links": "true",
                    }
                    try:
                        s_data = self._request("GET", "/resources/stats/latest", params=s_params)
                        self._parse_stats_response(s_data, results)
                    except Exception as s_err:
                        logger.error("Failed to retrieve latest stats for %s: %s", single_rid, s_err)
                        failed_rids.append(single_rid)
                        last_err = s_err

                if len(failed_rids) == len(chunk_rids):
                    raise OpsClientError(
                        f"Failed to retrieve latest stats for all {len(chunk_rids)} resources in chunk: {last_err}"
                    ) from last_err

        return results

    def _parse_stats_response(
        self,
        data: Dict[str, Any],
        results: Dict[str, Dict[str, Dict[int, Optional[float]]]],
    ) -> None:
        """Parse stats response into results mapping."""
        values = data.get("values", []) or []
        for val_entry in values:
            rid = val_entry.get("resourceId")
            if not rid:
                continue
            if rid not in results:
                results[rid] = {}

            stat_list = val_entry.get("stat-list", {}).get("stat", []) or []
            for st in stat_list:
                stat_key = st.get("statKey", {}).get("key")
                if not stat_key:
                    continue

                timestamps = st.get("timestamps", []) or []
                data_points = st.get("data", []) or []

                if stat_key not in results[rid]:
                    results[rid][stat_key] = {}

                for ts, val in zip(timestamps, data_points):
                    try:
                        results[rid][stat_key][int(ts)] = safe_float(val)
                    except (ValueError, TypeError):
                        results[rid][stat_key][int(ts)] = None
