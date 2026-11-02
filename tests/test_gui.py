"""Unit tests for localhost GUI server and endpoints."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from ops_metric_harvest.gui.server import (
    SERVER_SESSION,
    GuiRequestHandler,
)


@pytest.fixture
def gui_test_server(mock_urlopen_handler):
    """Run an ephemeral GUI server for API integration tests."""
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), GuiRequestHandler)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}"
        server.shutdown()
        server.server_close()


def test_gui_root_serves_html(gui_test_server):
    req = urllib.request.Request(gui_test_server)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "VCF Operations Metrics Explorer" in html
        assert SERVER_SESSION in html


def test_gui_csrf_protection(gui_test_server):
    # Request without X-Session header or s query param must return 403 Forbidden
    req = urllib.request.Request(f"{gui_test_server}/api/status")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403


def test_gui_status_endpoint_authed(gui_test_server):
    req = urllib.request.Request(
        f"{gui_test_server}/api/status",
        headers={"X-Session": SERVER_SESSION},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "status" in data
        assert "log" in data


def test_gui_test_connect(gui_test_server, mock_urlopen_handler):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        body = json.dumps({
            "server": "vcf-ops.example.com",
            "token": "valid-token",
            "verify_ssl": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{gui_test_server}/api/test-connect",
            data=body,
            headers={"Content-Type": "application/json", "X-Session": SERVER_SESSION},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"


def test_gui_html_script_syntax(gui_test_server):
    import re
    import shutil
    import subprocess
    import tempfile

    req = urllib.request.Request(gui_test_server)
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")

    m = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert m is not None
    js_code = m.group(1)

    # Ensure no raw unescaped newline inside regex literals
    assert "/[,\n]/" not in js_code

    if shutil.which("node"):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write(js_code)
            tf_path = tf.name
        try:
            res = subprocess.run(["node", "--check", tf_path], capture_output=True, text=True)
            assert res.returncode == 0, f"JS syntax check failed: {res.stderr}"
        finally:
            import os
            if os.path.exists(tf_path):
                os.remove(tf_path)


def test_gui_run_with_csv_content(gui_test_server, mock_urlopen_handler):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        payload = {
            "auth": {
                "server": "vcf-ops.example.com",
                "token": "tok",
                "verify_ssl": False,
            },
            "job": {
                "schema_version": "1.0",
                "name": "GUI CSV Job",
                "connection": {"server": "vcf-ops.example.com"},
                "time_range": {"mode": "relative", "relative_preset": "1h"},
                "groups": [
                    {
                        "name": "Imported Group",
                        "resource_kind": "VirtualMachine",
                        "selector": {
                            "resource_kind": "VirtualMachine",
                            "selection_mode": "imported",
                            "csv_content": "ObjectName,ResourceKind\napp-vm-01,VirtualMachine\n",
                        },
                        "metric_set": {
                            "stat_keys": ["cpu|usage_average"],
                        },
                    }
                ],
            },
            "workers": 2,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{gui_test_server}/api/run",
            data=body,
            headers={"Content-Type": "application/json", "X-Session": SERVER_SESSION},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "started"


def test_gui_run_with_explicit_objects(gui_test_server, mock_urlopen_handler):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        payload = {
            "auth": {
                "server": "vcf-ops.example.com",
                "token": "tok",
                "verify_ssl": False,
            },
            "job": {
                "schema_version": "1.0",
                "name": "GUI Explicit Job",
                "connection": {"server": "vcf-ops.example.com"},
                "time_range": {"mode": "relative", "relative_preset": "1h"},
                "groups": [
                    {
                        "name": "Explicit Group",
                        "resource_kind": "VirtualMachine",
                        "selector": {
                            "resource_kind": "VirtualMachine",
                            "selection_mode": "explicit",
                            "names": ["app-vm-01", "app-vm-02"],
                        },
                        "metric_set": {
                            "stat_keys": ["cpu|usage_average"],
                        },
                    }
                ],
            },
            "workers": 2,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{gui_test_server}/api/run",
            data=body,
            headers={"Content-Type": "application/json", "X-Session": SERVER_SESSION},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "started"

