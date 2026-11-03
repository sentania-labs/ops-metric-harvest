"""Pytest configuration and shared test fixtures."""

import io
import json
import re
import urllib.error
import urllib.parse
from unittest.mock import patch

import pytest

from ops_metric_harvest.client import OpsClient
from tests.fixtures.auth_responses import AUTH_TOKEN_SUCCESS
from tests.fixtures.inventory_responses import (
    DUPLICATE_NAME_INVENTORY,
    HOSTS_INVENTORY_PAGE_0,
    HOSTS_INVENTORY_PAGE_1,
    VMS_INVENTORY,
)
from tests.fixtures.metric_responses import (
    HOST_STAT_KEYS_CATALOGUE,
    VM_STAT_KEYS_CATALOGUE,
)
from tests.fixtures.stats_responses import (
    MOCK_MISALIGNED_STATS,
    create_mock_hosts_stats,
)


class MockHTTPResponse:
    """Mock urllib HTTP response object."""

    def __init__(self, data: dict, status_code: int = 200, headers: dict = None):
        self.data_bytes = json.dumps(data).encode("utf-8")
        self.status = status_code
        self.code = status_code
        self.headers_dict = headers or {"Content-Type": "application/json"}

    def read(self):
        return self.data_bytes

    def getcode(self):
        return self.code

    @property
    def headers(self):
        class HeaderWrapper:
            def __init__(self, h):
                self.h = h

            def get_content_charset(self):
                return "utf-8"

            def get(self, k, default=None):
                return self.h.get(k, default)

        return HeaderWrapper(self.headers_dict)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


_original_urlopen = urllib.request.urlopen


@pytest.fixture
def mock_urlopen_handler():
    """Smart mock handler that responds appropriately based on URL and query params."""
    def handler(req, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "127.0.0.1" in url or "localhost" in url:
            return _original_urlopen(req, **kwargs)

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        # 1. Auth acquire
        if "/auth/token/acquire" in parsed.path:
            body = json.loads(req.data.decode("utf-8")) if req.data else {}
            if body.get("username") == "baduser" or body.get("password") == "badpass":
                fp = io.BytesIO(b'{"message":"Unauthorized","httpStatusCode":401}')
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, fp)
            return MockHTTPResponse(AUTH_TOKEN_SUCCESS)

        # 2. Versions
        if "/versions" in parsed.path:
            return MockHTTPResponse({"releaseVersion": "8.18.0", "buildNumber": "12345678"})

        if parsed.path.endswith("/adapterkinds"):
            return MockHTTPResponse({"adapter-kind": [{"key": "VMWARE"}]})
        if parsed.path.endswith("/resourcekinds"):
            return MockHTTPResponse({"resourceKind": [{"key": "HostSystem"}, {"key": "VirtualMachine"}]})
        # Model server filtering and pagination, including ID filters and regex.
        if parsed.path.endswith("/resources"):
            rk = params.get("resourceKind", [""])[0]
            page = int(params.get("page", ["0"])[0])
            size = int(params.get("pageSize", ["1000"])[0])
            inventory = (HOSTS_INVENTORY_PAGE_0["resourceList"] + HOSTS_INVENTORY_PAGE_1["resourceList"]
                         if rk == "HostSystem" else VMS_INVENTORY["resourceList"] if rk == "VirtualMachine" else [])
            pattern = params.get("regex", [""])[0]
            if "duplicate" in pattern:
                inventory = DUPLICATE_NAME_INVENTORY["resourceList"]
            if pattern:
                inventory = [r for r in inventory if re.fullmatch(pattern, r["resourceKey"]["name"]) is not None]
            if "resourceId" in params:
                inventory = [r for r in inventory if r["identifier"] in params["resourceId"]]
            inventory = [r for r in inventory if r["resourceKey"]["adapterKindKey"] in params.get("adapterKind", ["VMWARE"])]
            return MockHTTPResponse({"resourceList": inventory[page * size:(page + 1) * size],
                                     "pageInfo": {"page": page, "pageSize": size, "totalCount": len(inventory)}})

        # 4. Stat keys catalogue
        if "/statkeys" in parsed.path:
            if "HostSystem" in parsed.path:
                return MockHTTPResponse(HOST_STAT_KEYS_CATALOGUE)
            elif "VirtualMachine" in parsed.path:
                return MockHTTPResponse(VM_STAT_KEYS_CATALOGUE)
            return MockHTTPResponse({"resourceTypeAttributes": []})

        # 5. Resources stats (historical)
        if "/resources/stats" in parsed.path and not parsed.path.endswith("/latest"):
            rids = params.get("resourceId", [])
            skeys = params.get("statKey", [])
            if "vm-uneven-01" in rids:
                return MockHTTPResponse(MOCK_MISALIGNED_STATS)
            return MockHTTPResponse(create_mock_hosts_stats(rids, skeys))

        # 6. Resources stats latest
        if "/resources/stats/latest" in parsed.path:
            rids = params.get("resourceId", [])
            skeys = params.get("statKey", [])
            return MockHTTPResponse(create_mock_hosts_stats(rids, skeys))

        return MockHTTPResponse({})

    return handler


@pytest.fixture
def mock_client(mock_urlopen_handler):
    """Pre-configured OpsClient pointing to mock server."""
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        client = OpsClient(server="vcf-ops.example.com", token="mock-test-token", verify=False)
        yield client
