"""Unit tests for CLI commands."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from ops_metric_harvest.cli import build_parser


def test_cli_parser_help(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "VCF Operations Metrics Explorer" in captured.out


def test_cli_connect_test(mock_urlopen_handler, capsys):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        parser = build_parser()
        args = parser.parse_args(["connect", "test", "--server", "vcf-ops.example.com", "--token", "tok", "-q"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "ok"


def test_cli_objects_kinds(mock_urlopen_handler, capsys):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        parser = build_parser()
        args = parser.parse_args(["objects", "kinds", "--server", "vcf-ops.example.com", "--token", "tok", "-q"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "HostSystem" in captured.out
        assert "VirtualMachine" in captured.out


def test_cli_objects_search(mock_urlopen_handler, capsys):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        parser = build_parser()
        args = parser.parse_args(["objects", "search", "--server", "vcf-ops.example.com", "--token", "tok", "--kind", "VirtualMachine", "--format", "json", "-q"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 6
        assert data[0]["name"] == "app-vm-01"


def test_cli_metrics_list(mock_urlopen_handler, capsys):
    with patch("urllib.request.urlopen", side_effect=mock_urlopen_handler):
        parser = build_parser()
        args = parser.parse_args(["metrics", "list", "--server", "vcf-ops.example.com", "--token", "tok", "--kind", "HostSystem", "--format", "json", "-q"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "cpu|capacity_usagepct_average" in data


def test_cli_profiles_validate(capsys):
    profile_content = {
        "schema_version": "1.0",
        "name": "CLI Val Test",
        "connection": {"server": "vcf-ops.example.com"},
        "time_range": {"mode": "relative", "relative_preset": "7d"},
        "groups": [
            {
                "name": "G1",
                "resource_kind": "HostSystem",
                "selector": {"selection_mode": "all", "resource_kind": "HostSystem"},
                "metric_set": {"stat_keys": ["cpu|usage"]},
            }
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(profile_content, tf)
        tf_name = tf.name

    try:
        parser = build_parser()
        args = parser.parse_args(["profiles", "validate", tf_name])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "valid" in captured.err.lower()
    finally:
        if os.path.exists(tf_name):
            os.remove(tf_name)


def test_cli_collect_mismatched_dates(capsys):
    parser = build_parser()
    args = parser.parse_args([
        "collect",
        "--server", "vcf-ops.example.com",
        "--token", "tok",
        "--kind", "HostSystem",
        "--stat-keys", "cpu|usage",
        "--start", "2026-10-01T00:00:00Z",
    ])
    ret = args.func(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "Both --start and --end must be provided" in captured.err


def test_cli_collect_latest_samples_conflict(capsys):
    parser = build_parser()
    args = parser.parse_args([
        "collect",
        "--server", "vcf-ops.example.com",
        "--token", "tok",
        "--kind", "HostSystem",
        "--stat-keys", "cpu|usage",
        "--max-samples", "10",
        "--start", "2026-10-01T00:00:00Z",
        "--end", "2026-10-02T00:00:00Z",
    ])
    ret = args.func(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "Cannot combine --max-samples with --start/--end" in captured.err


def test_cli_profiles_run_nonexistent(capsys):
    parser = build_parser()
    args = parser.parse_args(["profiles", "run", "nonexistent_profile.json"])
    ret = args.func(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "Could not load profile" in captured.err



@pytest.mark.parametrize("bundle_kind", ["missing", "malformed"])
def test_cli_profiles_run_bad_ca_bundle(tmp_path, capsys, bundle_kind):
    bundle = tmp_path / "ca.pem"
    if bundle_kind == "malformed":
        bundle.write_text("not a certificate")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": "1.0",
        "name": "CA Test",
        "connection": {"server": "vcf-ops.example.com", "verify_ssl": True, "ca_bundle": str(bundle)},
        "time_range": {"mode": "relative", "relative_preset": "7d"},
        "groups": [
            {
                "name": "G1",
                "resource_kind": "HostSystem",
                "selector": {"selection_mode": "all", "resource_kind": "HostSystem"},
                "metric_set": {"stat_keys": ["cpu|usage"]},
            }
        ],
    }))
    parser = build_parser()
    args = parser.parse_args(["profiles", "run", str(profile), "--token", "t"])
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "trusted CA bundle" in err
    assert "Traceback" not in err
