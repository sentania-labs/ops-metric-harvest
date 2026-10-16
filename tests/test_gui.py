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
