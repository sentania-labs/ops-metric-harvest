"""Localhost browser-based GUI server for VCF Operations Metrics Explorer."""

from __future__ import annotations

import csv
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from ops_metric_harvest.client import OpsClient
from ops_metric_harvest.engine import CollectionEngine
from ops_metric_harvest.exporters import (
    export_csv_long,
    export_csv_wide,
    export_json,
    export_xlsx,
)
from ops_metric_harvest.exporters.base import to_wide_rows
from ops_metric_harvest.models import (
    CollectionJob,
    CollectionResult,
)
from ops_metric_harvest.profiles import validate_profile_dict
from ops_metric_harvest.starter_metrics import STARTER_METRIC_SETS
from ops_metric_harvest.version import __app_name__, __version__

logger = logging.getLogger("ops_metric_harvest.gui")


class ActiveJob:
    """Thread-safe state container for running GUI collection job."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "lock", threading.Lock()):
            self.status = "idle"  # idle | running | done | error | cancelled
            self.log: List[str] = []
            self.done = 0
            self.total = 0
            self.error: Optional[str] = None
            self.result: Optional[CollectionResult] = None
            self.job: Optional[CollectionJob] = None
            self.cancel_flag = False
            self.started: Optional[float] = None
            self.finished: Optional[float] = None

    def add_log(self, msg: str, done: int = 0, total: int = 0) -> None:
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log.append(f"{ts}  {msg}")
            if total > 0:
                self.done = done
                self.total = total

    def should_stop(self) -> bool:
        return self.cancel_flag


GUI_JOB = ActiveJob()
SERVER_SESSION = secrets.token_urlsafe(24)


class GuiRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for localhost GUI."""

    server_version = f"{__app_name__}/{__version__}"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP access logging to keep terminal clean."""

    def _send_response(
        self,
        code: int,
        body: Any,
        content_type: str = "application/json",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = body

        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _is_authed(self, query_params: Optional[Dict[str, List[str]]] = None) -> bool:
        """Check session token against CSRF attacks."""
        tok = self.headers.get("X-Session") or (query_params or {}).get("s", [None])[0]
        if not tok:
            return False
        return secrets.compare_digest(tok, SERVER_SESSION)

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(url.query)

        if url.path == "/":
            html = HTML_PAGE.replace("__SESSION__", SERVER_SESSION)
            html = html.replace("__VERSION__", __version__)
            html = html.replace("__STARTER_SETS__", json.dumps(STARTER_METRIC_SETS))
            return self._send_response(200, html, "text/html; charset=utf-8")

        if not self._is_authed(params):
            return self._send_response(403, {"error": "Unauthorized session token"})

        if url.path == "/api/status":
            since = int(params.get("since", ["0"])[0])
            with GUI_JOB.lock:
                status_data: Dict[str, Any] = {
                    "status": GUI_JOB.status,
                    "log": GUI_JOB.log[since:],
                    "log_len": len(GUI_JOB.log),
                    "done": GUI_JOB.done,
                    "total": GUI_JOB.total,
                    "error": GUI_JOB.error,
                    "elapsed": round((GUI_JOB.finished or time.time()) - (GUI_JOB.started or time.time()), 1)
                    if GUI_JOB.started
                    else 0,
                }
                if GUI_JOB.status == "done" and GUI_JOB.result is not None:
                    # Provide preview rows
                    res = GUI_JOB.result
                    headers, rows = to_wide_rows(res.samples[:1000], "America/Chicago")
                    status_data["result"] = {
                        "job_name": res.job_name,
                        "total_samples": len(res.samples),
                        "total_rows": len(rows),
                        "columns": headers,
                        "preview_rows": rows[:200],
                        "errors": res.errors,
                        "warnings": res.warnings,
                        "stats": res.stats,
                    }
            return self._send_response(200, status_data)

        if url.path == "/api/download":
            fmt = params.get("fmt", ["csv_long"])[0]
            if GUI_JOB.status != "done" or not GUI_JOB.result:
                return self._send_response(400, {"error": "No completed collection to download"})

            res = GUI_JOB.result
            base_filename = f"{res.job_name.lower().replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}"

            if fmt == "csv_long":
                content = export_csv_long(res)
                filename = f"{base_filename}_long.csv"
                return self._send_response(
                    200,
                    content,
                    "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            elif fmt == "csv_wide":
                content = export_csv_wide(res)
                filename = f"{base_filename}_wide.csv"
                return self._send_response(
                    200,
                    content,
                    "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            elif fmt == "json":
                content = export_json(res)
                filename = f"{base_filename}.json"
                return self._send_response(
                    200,
                    content,
                    "application/json; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            elif fmt == "xlsx":
                fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                os.close(fd)
                try:
                    export_xlsx(res, tmp_path)
                    with open(tmp_path, "rb") as f:
                        data = f.read()
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                filename = f"{base_filename}.xlsx"
                return self._send_response(
                    200,
                    data,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            else:
                return self._send_response(400, {"error": f"Unknown format '{fmt}'"})

        return self._send_response(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if not self._is_authed():
            return self._send_response(403, {"error": "Unauthorized session token"})

        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return self._send_response(400, {"error": "Invalid JSON body"})

        if self.path == "/api/test-connect":
            server = body.get("server", "").strip()
            if not server:
                return self._send_response(400, {"error": "Server address is required"})
            verify = bool(body.get("verify_ssl", True))
            client = OpsClient(server=server, token=body.get("token") or None, verify=verify)
            if not body.get("token"):
                user = body.get("username", "").strip()
                pwd = body.get("password", "")
                src = body.get("auth_source")
                if not user or not pwd:
                    return self._send_response(400, {"error": "Username and password required"})
                try:
                    client.login(user, pwd, src)
                except Exception as e:
                    return self._send_response(401, {"error": f"Authentication failed: {e}"})
            try:
                res = client.test_connection()
                return self._send_response(200, {"status": "ok", "info": res})
            except Exception as e:
                return self._send_response(500, {"error": f"Connection test error: {e}"})

        elif self.path == "/api/kinds":
            try:
                client = self._create_client_from_body(body)
                kinds = client.list_resource_kinds(body.get("adapter_kind", "VMWARE"))
                return self._send_response(200, {"kinds": kinds})
            except Exception as e:
                return self._send_response(400, {"error": str(e)})

        elif self.path == "/api/search-objects":
            try:
                client = self._create_client_from_body(body)
                kind = body.get("resource_kind", "VirtualMachine")
                query = body.get("query")
                limit = int(body.get("limit", 100))
                objs = client.search_resources(resource_kind=kind, name_query=query, max_resources=limit)
                return self._send_response(200, {"objects": objs})
            except Exception as e:
                return self._send_response(400, {"error": str(e)})

        elif self.path == "/api/list-metrics":
            try:
                client = self._create_client_from_body(body)
                kind = body.get("resource_kind", "VirtualMachine")
                adapter = body.get("adapter_kind", "VMWARE")
                cat = client.get_stat_keys(adapter, kind)
                return self._send_response(200, {"metrics": cat})
            except Exception as e:
                return self._send_response(400, {"error": str(e)})

        elif self.path == "/api/parse-csv":
            try:
                csv_text = body.get("csv_content", "")
                lines = csv_text.strip().splitlines()
                reader = csv.reader(lines)
                rows = [r for r in reader if r and any(c.strip() for c in r)]
                return self._send_response(200, {"rows": rows, "count": len(rows)})
            except Exception as e:
                return self._send_response(400, {"error": str(e)})

        elif self.path == "/api/run":
            if GUI_JOB.status == "running":
                return self._send_response(409, {"error": "A collection job is already running"})

            try:
                job_data = body.get("job", {})
                validate_profile_dict(job_data)
                job = CollectionJob.from_dict(job_data)
                client = self._create_client_from_body(body.get("auth", {}))
            except Exception as e:
                return self._send_response(400, {"error": f"Failed to initialize collection: {e}"})

            GUI_JOB.reset()
            GUI_JOB.status = "running"
            GUI_JOB.job = job
            GUI_JOB.started = time.time()

            # Start thread
            def worker():
                try:
                    engine = CollectionEngine(
                        client=client,
                        max_workers=int(body.get("workers", 4)),
                        progress_cb=GUI_JOB.add_log,
                        should_stop=GUI_JOB.should_stop,
                    )
                    GUI_JOB.result = engine.execute(job)
                    GUI_JOB.status = "done"
                except Exception as ex:
                    GUI_JOB.error = str(ex)
                    GUI_JOB.status = "cancelled" if "cancelled" in str(ex).lower() else "error"
                    GUI_JOB.add_log(f"Job failed: {ex}")
                finally:
                    GUI_JOB.finished = time.time()

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            return self._send_response(200, {"status": "started"})

        elif self.path == "/api/cancel":
            if GUI_JOB.status == "running":
                GUI_JOB.cancel_flag = True
                GUI_JOB.add_log("Cancel requested by user...")
                return self._send_response(200, {"status": "cancelling"})
            return self._send_response(200, {"status": "not_running"})

        elif self.path == "/api/shutdown":
            self._send_response(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        return self._send_response(404, {"error": "Not found"})

    def _create_client_from_body(self, data: Dict[str, Any]) -> OpsClient:
        server = data.get("server", "").strip()
        if not server:
            raise ValueError("VCF Operations server address is required")
        verify = bool(data.get("verify_ssl", True))
        token = data.get("token") or None
        client = OpsClient(server=server, token=token, verify=verify)
        if not token:
            user = data.get("username", "").strip()
            if not user:
                raise ValueError("Username is required when no token is provided")
            pwd = data.get("password", "")
            if not pwd:
                raise ValueError("Password is required when no token is provided")
            client.login(user, pwd, data.get("auth_source"))
        return client


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VCF Operations Metrics Explorer</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 24px; font-size: 14px; line-height: 1.5; }
    .container { max-width: 1200px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--card-border); }
    h1 { font-size: 20px; font-weight: 600; }
    .badge { background: var(--primary); color: white; padding: 2px 8px; border-radius: 9999px; font-size: 12px; margin-left: 8px; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
    .card-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 16px; }
    label { display: block; font-size: 12px; font-weight: 500; color: var(--text-muted); margin-bottom: 6px; }
    input[type="text"], input[type="password"], input[type="number"], select, textarea {
      width: 100%; background: #0f172a; border: 1px solid var(--card-border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 13px; outline: none;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--primary); }
    button { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500; cursor: pointer; transition: background 0.15s ease; }
    button:hover { background: var(--primary-hover); }
    button.secondary { background: #334155; }
    button.secondary:hover { background: #475569; }
    button.danger { background: var(--danger); }
    button.danger:hover { background: #dc2626; }
    button.success { background: var(--accent); }
    button.success:hover { background: #059669; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-row { display: flex; gap: 8px; align-items: center; }
    .group-item { background: #131d2e; border: 1px solid var(--card-border); border-radius: 6px; padding: 16px; margin-bottom: 16px; }
    .group-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600; }
    .stat-list { max-height: 200px; overflow-y: auto; background: #0f172a; border: 1px solid var(--card-border); border-radius: 6px; padding: 8px; }
    .stat-item { display: flex; align-items: center; padding: 4px 6px; gap: 8px; font-size: 12px; }
    .stat-item:hover { background: #1e293b; }
    .progress-bar-bg { width: 100%; height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; margin-top: 12px; }
    .progress-bar-fill { height: 100%; background: var(--accent); width: 0%; transition: width 0.3s ease; }
    .log-box { background: #090d16; border: 1px solid var(--card-border); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 12px; height: 180px; overflow-y: auto; white-space: pre-wrap; margin-top: 12px; color: #a5b4fc; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
    th, td { border: 1px solid var(--card-border); padding: 6px 10px; text-align: left; }
    th { background: #131d2e; font-weight: 600; }
    tr:nth-child(even) { background: #162032; }
    .table-container { max-height: 350px; overflow-x: auto; overflow-y: auto; border: 1px solid var(--card-border); border-radius: 6px; }
    .flex-between { display: flex; justify-content: space-between; align-items: center; }
    .mt-2 { margin-top: 8px; }
    .mt-4 { margin-top: 16px; }
    .tag { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 500; background: #334155; margin-right: 4px; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <span style="font-size: 20px; font-weight: 600;">VCF Operations Metrics Explorer</span>
        <span class="badge">v__VERSION__</span>
      </div>
      <div class="btn-row">
        <button class="secondary" onclick="exportProfileJson()">Export Profile</button>
        <button class="secondary" onclick="document.getElementById('profileFile').click()">Import Profile</button>
        <input type="file" id="profileFile" style="display:none" accept=".json" onchange="importProfileJson(event)">
        <button class="danger" onclick="shutdownServer()">Exit App</button>
      </div>
    </header>

    <!-- 1. Connection Card -->
    <div class="card">
      <div class="card-title">1. Connection & Authentication</div>
      <div class="grid">
        <div>
          <label>VCF Operations Server (FQDN or IP)</label>
          <input type="text" id="server" placeholder="vcf-ops.example.com">
        </div>
        <div>
          <label>Authentication Mode</label>
          <select id="authMode" onchange="toggleAuthFields()">
            <option value="basic">Username & Password</option>
            <option value="token">OpsToken</option>
          </select>
        </div>
        <div id="userGroup">
          <label>Username</label>
          <input type="text" id="username" placeholder="admin">
        </div>
        <div id="passGroup">
          <label>Password</label>
          <input type="password" id="password" placeholder="Password">
        </div>
        <div id="sourceGroup">
          <label>Auth Source (Optional)</label>
          <input type="text" id="authSource" placeholder="System Domain / AD Source">
        </div>
        <div id="tokenGroup" style="display:none;">
          <label>OpsToken</label>
          <input type="password" id="token" placeholder="Paste existing OpsToken">
        </div>
      </div>
      <div class="flex-between">
        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
          <input type="checkbox" id="verifySsl" checked>
          <span>Verify TLS certificate (recommended; uncheck for self-signed lab certs)</span>
        </label>
        <div class="btn-row">
          <span id="connStatus" style="font-size: 13px; color: var(--text-muted);"></span>
          <button class="secondary" onclick="testConnection()">Test Connection</button>
        </div>
      </div>
    </div>

    <!-- 2. Time Range & Collection Settings -->
    <div class="card">
      <div class="card-title">2. Time Range & Rollup</div>
      <div class="grid">
        <div>
          <label>Mode</label>
          <select id="timeMode" onchange="toggleTimeFields()">
            <option value="relative">Relative Range</option>
            <option value="absolute">Explicit Absolute Range (UTC)</option>
          </select>
        </div>
        <div id="relativeGroup">
          <label>Relative Preset</label>
          <select id="relPreset">
            <option value="1h">Last 1 Hour</option>
            <option value="12h">Last 12 Hours</option>
            <option value="1d">Last 1 Day</option>
            <option value="7d" selected>Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
          </select>
        </div>
        <div id="absStartGroup" style="display:none;">
          <label>Start Time (ISO 8601 UTC)</label>
          <input type="text" id="startTime" placeholder="2026-10-01T00:00:00Z">
        </div>
        <div id="absEndGroup" style="display:none;">
          <label>End Time (ISO 8601 UTC)</label>
          <input type="text" id="endTime" placeholder="2026-10-08T00:00:00Z">
        </div>
        <div>
          <label>Rollup Interval</label>
          <select id="intervalType">
            <option value="MINUTES" selected>Minutes</option>
            <option value="HOURS">Hours</option>
            <option value="DAYS">Days</option>
            <option value="NONE">None (Raw)</option>
          </select>
        </div>
        <div>
          <label>Rollup Type</label>
          <select id="rollupType">
            <option value="AVG" selected>Average (AVG)</option>
            <option value="SUM">Sum (SUM)</option>
            <option value="MIN">Minimum (MIN)</option>
            <option value="MAX">Maximum (MAX)</option>
            <option value="LATEST">Latest</option>
            <option value="COUNT">Count</option>
            <option value="NONE">None</option>
          </select>
        </div>
      </div>
    </div>

    <!-- 3. Collection Groups -->
    <div class="card">
      <div class="card-title">
        <span>3. Collection Groups</span>
        <button class="secondary" onclick="addGroup()">+ Add Group</button>
      </div>
      <div id="groupsContainer"></div>
    </div>

    <!-- 4. Execution & Actions -->
    <div class="card">
      <div class="card-title">4. Run Collection & Export</div>
      <div class="flex-between">
        <div>
          <span id="preflightSummary" style="font-weight: 500;">Configure groups and click Start Collection.</span>
        </div>
        <div class="btn-row">
          <button id="btnCancel" class="danger" style="display:none;" onclick="cancelJob()">Cancel Collection</button>
          <button id="btnStart" class="success" onclick="startJob()">Start Collection</button>
        </div>
      </div>
      <div class="progress-bar-bg" id="progressBg" style="display:none;">
        <div class="progress-bar-fill" id="progressFill"></div>
      </div>
      <div class="log-box" id="logBox" style="display:none;"></div>
    </div>

    <!-- 5. Results & Downloads -->
    <div class="card" id="resultsCard" style="display:none;">
      <div class="card-title">
        <span>5. Results Preview</span>
        <div class="btn-row">
          <button class="secondary" onclick="downloadExport('csv_long')">Download CSV (Long)</button>
          <button class="secondary" onclick="downloadExport('csv_wide')">Download CSV (Wide)</button>
          <button class="secondary" onclick="downloadExport('xlsx')">Download Excel (.xlsx)</button>
          <button class="secondary" onclick="downloadExport('json')">Download JSON</button>
        </div>
      </div>
      <div id="resultsStats" style="margin-bottom: 12px; font-size: 13px;"></div>
      <div class="table-container">
        <table id="previewTable">
          <thead id="previewHead"></thead>
          <tbody id="previewBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    const SESSION = "__SESSION__";
    const STARTER_SETS = __STARTER_SETS__;
    let groups = [];
    let pollInterval = null;

    function toggleAuthFields() {
      const mode = document.getElementById("authMode").value;
      const isToken = mode === "token";
      document.getElementById("userGroup").style.display = isToken ? "none" : "block";
      document.getElementById("passGroup").style.display = isToken ? "none" : "block";
      document.getElementById("sourceGroup").style.display = isToken ? "none" : "block";
      document.getElementById("tokenGroup").style.display = isToken ? "block" : "none";
    }

    function toggleTimeFields() {
      const mode = document.getElementById("timeMode").value;
      const isRel = mode === "relative";
      document.getElementById("relativeGroup").style.display = isRel ? "block" : "none";
      document.getElementById("absStartGroup").style.display = isRel ? "none" : "block";
      document.getElementById("absEndGroup").style.display = isRel ? "none" : "block";
    }

    function addGroup(initialData = null) {
      const gid = initialData ? initialData.group_id : "grp_" + Math.random().toString(36).substring(2, 8);
      const defaultKind = initialData ? initialData.resource_kind : "VirtualMachine";
      const sel = initialData && initialData.selector ? initialData.selector : {};
      const g = {
        group_id: gid,
        name: initialData ? initialData.name : "Group " + (groups.length + 1),
        resource_kind: defaultKind,
        selection_mode: sel.selection_mode || "all",
        search_query: sel.search_query || "",
        names: sel.names ? [...sel.names] : [],
        resource_ids: sel.resource_ids ? [...sel.resource_ids] : [],
        csv_content: sel.csv_content || "",
        stat_keys: initialData && initialData.metric_set ? initialData.metric_set.stat_keys : (STARTER_SETS[defaultKind] ? STARTER_SETS[defaultKind].map(s => s.key) : []),
      };
      groups.push(g);
      renderGroups();
    }

    function removeGroup(idx) {
      if (groups.length <= 1) {
        alert("Must have at least one collection group.");
        return;
      }
      groups.splice(idx, 1);
      renderGroups();
    }

    function renderGroups() {
      const cont = document.getElementById("groupsContainer");
      cont.innerHTML = "";
      groups.forEach((g, idx) => {
        const div = document.createElement("div");
        div.className = "group-item";
        div.innerHTML = `
          <div class="group-header">
            <span>Group #${idx + 1}: <input type="text" value="${g.name}" style="width:200px; display:inline;" onchange="groups[${idx}].name=this.value"></span>
            <button class="danger" onclick="removeGroup(${idx})">Remove Group</button>
          </div>
          <div class="grid">
            <div>
              <label>Resource Kind</label>
              <select onchange="onKindChange(${idx}, this.value)">
                <option value="VirtualMachine" ${g.resource_kind === "VirtualMachine" ? "selected" : ""}>VirtualMachine</option>
                <option value="HostSystem" ${g.resource_kind === "HostSystem" ? "selected" : ""}>HostSystem</option>
                <option value="ClusterComputeResource" ${g.resource_kind === "ClusterComputeResource" ? "selected" : ""}>ClusterComputeResource</option>
                <option value="Datastore" ${g.resource_kind === "Datastore" ? "selected" : ""}>Datastore</option>
              </select>
            </div>
            <div>
              <label>Object Selection Mode</label>
              <select onchange="groups[${idx}].selection_mode=this.value; renderGroups();">
                <option value="all" ${g.selection_mode === "all" ? "selected" : ""}>All Objects of Kind</option>
                <option value="search" ${g.selection_mode === "search" ? "selected" : ""}>Filter by Name</option>
                <option value="explicit" ${g.selection_mode === "explicit" ? "selected" : ""}>Explicit Names/IDs</option>
                <option value="imported" ${g.selection_mode === "imported" ? "selected" : ""}>Import Object Names (CSV)</option>
              </select>
            </div>
            ${g.selection_mode === 'search' ? `
            <div>
              <label>Name Contains Filter</label>
              <input type="text" value="${g.search_query}" placeholder="e.g. prod-esx" onchange="groups[${idx}].search_query=this.value">
            </div>` : ''}
            ${g.selection_mode === 'explicit' ? `
            <div style="grid-column: 1 / -1;">
              <label>Explicit Object Names or IDs (comma-separated or one per line)</label>
              <textarea rows="2" placeholder="e.g. app-vm-01, app-vm-02" onchange="updateGroupExplicitObjects(${idx}, this.value)">${(g.names && g.names.length > 0 ? g.names : (g.resource_ids || [])).join(', ')}</textarea>
            </div>` : ''}
            ${g.selection_mode === 'imported' ? `
            <div style="grid-column: 1 / -1;">
              <label>Paste CSV or Upload (columns: ObjectName, ResourceKind)</label>
              <textarea rows="3" placeholder="ObjectName,ResourceKind\\nesx-01,HostSystem" onchange="groups[${idx}].csv_content=this.value">${g.csv_content}</textarea>
            </div>` : ''}
          </div>
          <div style="margin-top: 12px;">
            <div class="flex-between" style="margin-bottom: 6px;">
              <label>Selected Stat Keys (${g.stat_keys.length})</label>
              <div class="btn-row">
                <button class="secondary" style="font-size:11px; padding:2px 8px;" onclick="loadPreset(${idx})">Reset to Starter Preset</button>
              </div>
            </div>
            <textarea rows="2" style="font-family:monospace; font-size:12px;" onchange="updateGroupStatKeys(${idx}, this.value)">${g.stat_keys.join(", ")}</textarea>
          </div>
        `;
        cont.appendChild(div);
      });
      updatePreflight();
    }

    function onKindChange(idx, newKind) {
      groups[idx].resource_kind = newKind;
      if (STARTER_SETS[newKind]) {
        groups[idx].stat_keys = STARTER_SETS[newKind].map(s => s.key);
      }
      renderGroups();
    }

    function loadPreset(idx) {
      const k = groups[idx].resource_kind;
      if (STARTER_SETS[k]) {
        groups[idx].stat_keys = STARTER_SETS[k].map(s => s.key);
        renderGroups();
      }
    }

    function updateGroupExplicitObjects(idx, rawText) {
      const items = rawText.split(/[,\\r\\n]+/).map(s => s.trim()).filter(s => s.length > 0);
      const uuidRe = /^[0-9a-fA-F-]{32,38}$/;
      groups[idx].names = items.filter(i => !uuidRe.test(i));
      groups[idx].resource_ids = items.filter(i => uuidRe.test(i));
      if (groups[idx].names.length === 0 && items.length > 0) {
        groups[idx].names = items;
      }
    }

    function updateGroupStatKeys(idx, rawText) {
      const keys = rawText.split(/[,\\r\\n]+/).map(s => s.trim()).filter(s => s.length > 0);
      groups[idx].stat_keys = keys;
      updatePreflight();
    }

    function updatePreflight() {
      const sum = document.getElementById("preflightSummary");
      let totalMetrics = 0;
      groups.forEach(g => totalMetrics += g.stat_keys.length);
      sum.textContent = `Ready to collect ${groups.length} group(s) with ${totalMetrics} total metric key(s).`;
    }

    function getAuthPayload() {
      return {
        server: document.getElementById("server").value.trim(),
        username: document.getElementById("username").value.trim(),
        password: document.getElementById("password").value,
        token: document.getElementById("token").value.trim() || null,
        auth_source: document.getElementById("authSource").value.trim() || null,
        verify_ssl: document.getElementById("verifySsl").checked,
      };
    }

    async function testConnection() {
      const st = document.getElementById("connStatus");
      st.textContent = "Connecting...";
      st.style.color = "var(--text-muted)";
      try {
        const res = await fetch("/api/test-connect", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Session": SESSION },
          body: JSON.stringify(getAuthPayload())
        });
        const data = await res.json();
        if (res.ok) {
          st.textContent = "Connected successfully!";
          st.style.color = "var(--accent)";
        } else {
          st.textContent = "Error: " + (data.error || "Connection failed");
          st.style.color = "var(--danger)";
        }
      } catch (e) {
        st.textContent = "Error: " + e.message;
        st.style.color = "var(--danger)";
      }
    }

    function buildJobPayload() {
      const timeMode = document.getElementById("timeMode").value;
      const jobGroups = groups.map(g => ({
        group_id: g.group_id,
        name: g.name,
        resource_kind: g.resource_kind,
        selector: {
          resource_kind: g.resource_kind,
          selection_mode: g.selection_mode,
          adapter_kind: "VMWARE",
          search_query: g.search_query,
          names: g.names || [],
          resource_ids: g.resource_ids || [],
          csv_content: g.csv_content || "",
        },
        metric_set: {
          stat_keys: g.stat_keys,
        }
      }));

      return {
        schema_version: "1.0",
        name: "Web GUI Collection",
        connection: {
          server: document.getElementById("server").value.trim(),
          verify_ssl: document.getElementById("verifySsl").checked,
        },
        time_range: {
          mode: timeMode,
          relative_preset: document.getElementById("relPreset").value,
          start_time: timeMode === "absolute" ? document.getElementById("startTime").value.trim() : null,
          end_time: timeMode === "absolute" ? document.getElementById("endTime").value.trim() : null,
          interval_type: document.getElementById("intervalType").value,
          rollup_type: document.getElementById("rollupType").value,
        },
        groups: jobGroups,
      };
    }

    async function startJob() {
      const auth = getAuthPayload();
      if (!auth.server) {
        alert("Please enter VCF Operations server address.");
        return;
      }
      const job = buildJobPayload();
      document.getElementById("btnStart").disabled = true;
      document.getElementById("btnCancel").style.display = "inline-block";
      document.getElementById("progressBg").style.display = "block";
      document.getElementById("logBox").style.display = "block";
      document.getElementById("logBox").textContent = "Submitting job...\\n";
      document.getElementById("resultsCard").style.display = "none";

      try {
        const res = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Session": SESSION },
          body: JSON.stringify({ auth: auth, job: job, workers: 4 })
        });
        const data = await res.json();
        if (!res.ok) {
          alert("Error: " + data.error);
          document.getElementById("btnStart").disabled = false;
          document.getElementById("btnCancel").style.display = "none";
          return;
        }
        pollStatus();
      } catch (e) {
        alert("Error launching job: " + e.message);
        document.getElementById("btnStart").disabled = false;
        document.getElementById("btnCancel").style.display = "none";
      }
    }

    function pollStatus() {
      if (pollInterval) clearInterval(pollInterval);
      let lastLogIdx = 0;
      pollInterval = setInterval(async () => {
        try {
          const res = await fetch(`/api/status?since=${lastLogIdx}`, {
            headers: { "X-Session": SESSION }
          });
          const data = await res.json();
          if (data.log && data.log.length > 0) {
            const box = document.getElementById("logBox");
            data.log.forEach(line => box.textContent += line + "\\n");
            box.scrollTop = box.scrollHeight;
            lastLogIdx = data.log_len;
          }
          if (data.total > 0) {
            const pct = Math.round((data.done / data.total) * 100);
            document.getElementById("progressFill").style.width = pct + "%";
          }
          if (data.status === "done" || data.status === "error" || data.status === "cancelled") {
            clearInterval(pollInterval);
            document.getElementById("btnStart").disabled = false;
            document.getElementById("btnCancel").style.display = "none";
            if (data.status === "done" && data.result) {
              renderResults(data.result);
            }
          }
        } catch (e) {
          console.error("Poll error", e);
        }
      }, 800);
    }

    async function cancelJob() {
      await fetch("/api/cancel", {
        method: "POST",
        headers: { "X-Session": SESSION }
      });
    }

    function renderResults(res) {
      const card = document.getElementById("resultsCard");
      card.style.display = "block";
      const stats = document.getElementById("resultsStats");
      stats.innerHTML = `<strong>Collection Finished:</strong> Retrieved <strong>${res.total_samples.toLocaleString()}</strong> metric samples across <strong>${res.total_rows.toLocaleString()}</strong> rows in ${res.stats.elapsed_seconds || 0}s (${res.stats.api_calls || 0} API calls).`;

      const thead = document.getElementById("previewHead");
      thead.innerHTML = "";
      const trH = document.createElement("tr");
      res.columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        trH.appendChild(th);
      });
      thead.appendChild(trH);

      const tbody = document.getElementById("previewBody");
      tbody.innerHTML = "";
      res.preview_rows.forEach(r => {
        const tr = document.createElement("tr");
        r.forEach(val => {
          const td = document.createElement("td");
          td.textContent = (val === null || val === undefined) ? "" : val;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }

    function downloadExport(fmt) {
      window.location = `/api/download?fmt=${fmt}&s=${SESSION}`;
    }

    function exportProfileJson() {
      const payload = buildJobPayload();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "vcf_metrics_profile.json";
      a.click();
    }

    function importProfileJson(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const data = JSON.parse(e.target.result);
          if (data.connection && data.connection.server) {
            document.getElementById("server").value = data.connection.server;
          }
          if (data.connection && data.connection.verify_ssl !== undefined) {
            document.getElementById("verifySsl").checked = data.connection.verify_ssl;
          }
          if (data.time_range) {
            document.getElementById("timeMode").value = data.time_range.mode || "relative";
            if (data.time_range.relative_preset) document.getElementById("relPreset").value = data.time_range.relative_preset;
            if (data.time_range.start_time) document.getElementById("startTime").value = data.time_range.start_time;
            if (data.time_range.end_time) document.getElementById("endTime").value = data.time_range.end_time;
            if (data.time_range.interval_type) document.getElementById("intervalType").value = data.time_range.interval_type;
            if (data.time_range.rollup_type) document.getElementById("rollupType").value = data.time_range.rollup_type;
            toggleTimeFields();
          }
          if (data.groups && Array.isArray(data.groups) && data.groups.length > 0) {
            groups = [];
            data.groups.forEach(grp => addGroup(grp));
          }
          alert("Profile loaded successfully.");
        } catch (err) {
          alert("Failed to parse profile JSON: " + err.message);
        }
      };
      reader.readAsText(file);
    }

    async function shutdownServer() {
      if (confirm("Shut down the application server and close?")) {
        await fetch("/api/shutdown", { method: "POST", headers: { "X-Session": SESSION } });
        document.body.innerHTML = "<div style='text-align:center; padding:100px;'><h2>Application Stopped</h2><p>You can close this browser tab.</p></div>";
      }
    }

    // Initialize with 1 default group
    addGroup();
  </script>
</body>
</html>
"""


def run_gui_server(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> int:
    """Run loopback ThreadingHTTPServer and optionally open default browser."""
    # Ensure strictly loopback binding for security
    if host not in ("127.0.0.1", "localhost", "::1"):
        sys.stderr.write(f"WARNING: GUI host '{host}' forced to '127.0.0.1' for security.\n")
        host = "127.0.0.1"

    server = ThreadingHTTPServer((host, port), GuiRequestHandler)
    actual_port = server.server_port
    url = f"http://127.0.0.1:{actual_port}"

    sys.stderr.write(f"VCF Operations Metrics Explorer GUI started at {url}\n")
    sys.stderr.write("Press Ctrl+C to stop.\n")
    sys.stderr.flush()

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            sys.stderr.write(f"Notice: Could not automatically open browser ({e}). Navigate manually to {url}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nShutting down GUI server...\n")
    finally:
        server.server_close()

    return 0
