"""Unit tests for OpsClient."""

import io
import urllib.error
from unittest.mock import patch

import pytest

from ops_metric_harvest.client import OpsAuthError, OpsClient
from tests.conftest import MockHTTPResponse


def test_client_init_and_url_normalization():
    c1 = OpsClient("vcf-ops.example.com")
    assert c1.base_url == "https://vcf-ops.example.com/suite-api/api"

    c2 = OpsClient("https://vcf-ops.example.com/suite-api/api/")
    assert c2.base_url == "https://vcf-ops.example.com/suite-api/api"

    with pytest.raises(ValueError):
        OpsClient("")


def test_client_login_success(mock_client):
    token = mock_client.login("admin", "correctpassword")
    assert token == "mock-opstoken-xyz-1234567890"
    assert "Authorization" in mock_client.headers
    assert "OpsToken mock-opstoken-xyz-1234567890" in mock_client.headers["Authorization"]


def test_client_login_failure_unauthorized(mock_urlopen_handler):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        client = OpsClient(server="vcf-ops.example.com", verify=False)
        with pytest.raises(OpsAuthError) as exc_info:
            client.login("baduser", "badpass")
        assert "401" in str(exc_info.value)
        assert "Unauthorized" in str(exc_info.value)


def test_client_secret_redaction():
    client = OpsClient(server="vcf-ops.example.com", token="super-secret-token-12345", verify=False)
    raw = 'Error: Authorization: OpsToken super-secret-token-12345 failed with password="mySecretPassword"'
    redacted = client._redact(raw)
    assert "super-secret-token-12345" not in redacted
    assert "mySecretPassword" not in redacted
    assert "[REDACTED]" in redacted


def test_client_pagination(mock_client):
    # HostSystem is configured across 2 pages of 2 items each
    hosts = mock_client.search_resources("HostSystem", page_size=2)
    assert len(hosts) == 4
    names = [h["name"] for h in hosts]
    assert "esx-prod-01.int.sentania.net" in names
    assert "esx-prod-04.int.sentania.net" in names


def test_client_get_stat_keys(mock_client):
    cat = mock_client.get_stat_keys("VMWARE", "HostSystem")
    assert "cpu|capacity_usagepct_average" in cat
    assert cat["cpu|capacity_usagepct_average"]["name"] == "CPU Usage (%)"
    assert cat["cpu|capacity_usagepct_average"]["unit"] == "%"


def test_client_retries_on_503():
    attempts = 0

    def mock_503(req, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            fp = io.BytesIO(b'{"message":"Service Unavailable"}')
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, fp)
        return MockHTTPResponse({"status": "recovered"})

    with patch("urllib.request.urlopen", side_effect=mock_503):
        with patch("time.sleep"):  # Avoid actual sleep during tests
            client = OpsClient("vcf-ops.example.com", token="tok", retries=3, verify=False)
            res = client._request("GET", "/test")
            assert res["status"] == "recovered"
            assert client.retry_count == 2
