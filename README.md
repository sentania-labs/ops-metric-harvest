# VCF Operations Metrics Explorer

VCF Operations Metrics Explorer is a lightweight, cross-platform utility that connects to VMware Cloud Foundation Operations (formerly Aria Operations / vRealize Operations) to discover inventory objects, select performance metrics, execute multi-group historical collection jobs, and export aligned results to CSV, Excel (.xlsx), and JSON.

The application includes both a localhost browser GUI and a fully scriptable CLI backed by the same collection engine. It packages into a single standalone executable on Windows, macOS, and Linux without requiring users to install Python or other runtime runtimes.

---

## Quick Start

### Standalone Executable

Download the precompiled release binary for your platform from GitHub Releases, or build locally:

```bash
# Launch the graphical query builder in your browser
./ops-metric-harvest gui

# Or run headless collection directly from the CLI
./ops-metric-harvest collect --server vcf-ops.example.com --user admin --kind HostSystem --sample-size 7d --format both
```

### From Python Source

Python 3.9 or newer is supported:

```bash
# Clone the repository
git clone https://github.com/sentania-labs/ops-metric-harvest.git
cd ops-metric-harvest

# Launch the browser GUI (default action when run without arguments)
python3 -m ops_metric_harvest.cli

# Run automated tests
pytest -v
```

---

## Comparison: Reference Implementation Heritage

This project combines the strengths and resolves the defects identified during source review of two reference implementations:

| Feature / Area | Reference A (vropsMetrics, PowerShell) | Reference B (vcf_operations_metric_picker, Python) | VCF Operations Metrics Explorer (This Project) |
|---|---|---|---|
| **Language & Runtime** | PowerShell script (Windows-centric) | Python standard library scripts | Pure Python core packaged as cross-platform native executables |
| **TLS Verification** | Broken: assignment bug `if ($ignoreSSL = $true)` unconditionally disabled TLS | Disabled by default | Enabled by default; explicit `--insecure` flag with clear warning |
| **CSV Object Import** | Broken: `-Header` parameter caused column titles to be parsed as inventory objects | Not supported | Flexible CSV parsing with automatic header detection and name resolution |
| **Inventory Pagination** | Single query with `pageSize=100000` (fails on large estates) | Iterative page loop (`pageSize=1000`) | Robust iterative pagination with client-side name/query filtering |
| **Collection Semantics** | Batched `/resources/stats` historical range queries | Per-resource `/resources/stats/latest` latest-N-samples queries | Both supported: historical range/rollup is canonical, with latest-N fallback |
| **Request Batching & Limits** | All IDs in a single GET query string (exceeds URL limits) | One HTTP request per object via thread pool | Bounded batching (up to 40 resources per query) with fallback to single queries |
| **Timestamp Alignment** | Assumed identical timestamps across all metrics (indexes corrupt on gaps) | Union of timestamps with `None` fill | Full timestamp union alignment across all metrics, objects, and groups |
| **Collection Groups** | Single resource kind per run | Single object type and single stat list | Multiple independent groups with deduplicated querying and clean attribution |
| **Export Formats** | CSV only (separated by kind) | Custom standard-library XLSX and JSON | Canonical long CSV, wide CSV, multi-sheet XLSX (with sheet splitting), JSON, and terminal table |
| **Formula Injection Protection** | None | None | Sanitizes values starting with `=`, `+`, `-`, `@`, `\t`, `\r` |
| **Profile Management** | None | Browser localStorage only | Versioned JSON profile schema (`schema_version: "1.0"`), shared between GUI and CLI |

---

## CLI Reference

The CLI separates structured data on stdout from operational progress on stderr, making it safe for automation pipelines.

### Subcommands

```bash
# Test server connectivity and authentication
./ops-metric-harvest connect test --server vcf-ops.example.com --user admin

# Discover supported resource kinds
./ops-metric-harvest objects kinds --server vcf-ops.example.com --token "$VCFOPS_TOKEN"

# Search for specific inventory objects
./ops-metric-harvest objects search --server vcf-ops.example.com --token "$VCFOPS_TOKEN" --kind VirtualMachine --query "db"

# List metric catalogue definitions and units
./ops-metric-harvest metrics list --server vcf-ops.example.com --token "$VCFOPS_TOKEN" --kind HostSystem --filter "cpu"

# Validate a saved collection profile JSON file
./ops-metric-harvest profiles validate examples/profiles/scenario_a_all_hosts.json

# Execute an ad-hoc collection
./ops-metric-harvest collect \
  --server vcf-ops.example.com \
  --token "$VCFOPS_TOKEN" \
  --kind HostSystem \
  --objects all \
  --stat-keys "cpu|capacity_usagepct_average,mem|active_average" \
  --sample-size 7d \
  --format csv,xlsx \
  --output ./esx_metrics

# Execute a saved collection profile
./ops-metric-harvest profiles run examples/profiles/scenario_c_two_vm_groups.json \
  --token "$VCFOPS_TOKEN" \
  --output ./vm_groups_output
```

### Exit Codes

- `0`: Success (all requested objects and metrics collected).
- `1`: Fatal error (authentication rejected, network failure, or invalid profile).
- `2`: Partial success (warnings recorded or subset of metrics/objects returned null).

---

## Browser GUI

Run `./ops-metric-harvest gui` (or launch the executable directly). The local browser opens automatically to `http://127.0.0.1:<port>`.

### Features
1. **Connection Screen**: Supports username/password with optional auth source, or existing OpsToken. TLS verification is toggled with visible security alerts.
2. **Multi-Group Builder**: Create independent collection groups. For each group, configure:
   - Resource kind (`VirtualMachine`, `HostSystem`, `ClusterComputeResource`, `Datastore`).
   - Object selector (`All`, `Filter by Name`, or `Import CSV`).
   - Metric picker with starter presets and manual stat key fallback.
3. **Time Range & Rollup**: Relative ranges (1h to 30d) or exact ISO UTC timestamps, with selectable rollup types (AVG, SUM, MIN, MAX, NONE).
4. **Preflight Summary**: Verifies selection scope before sending API requests.
5. **Live Progress & Cancellation**: Real-time progress bar, request log, and instant cancellation.
6. **Results & Downloads**: Preview table with 200 rows and one-click downloads for long CSV, wide CSV, multi-sheet Excel (.xlsx), and JSON.
7. **Profile Management**: Save configured jobs to versioned JSON or import existing profiles.

---

## Collection Profile Format

Profiles use schema version 1.0. Profiles define job selectors and output settings, and never store passwords or authentication tokens.

Example profile:

```json
{
  "schema_version": "1.0",
  "name": "Scenario A: All Host Systems",
  "connection": {
    "server": "vcf-ops.example.com",
    "verify_ssl": true
  },
  "time_range": {
    "mode": "relative",
    "relative_preset": "7d",
    "interval_minutes": 5,
    "interval_type": "MINUTES",
    "rollup_type": "AVG"
  },
  "groups": [
    {
      "group_id": "all-hosts",
      "name": "All ESXi Hosts",
      "resource_kind": "HostSystem",
      "selector": {
        "resource_kind": "HostSystem",
        "selection_mode": "all",
        "adapter_kind": "VMWARE"
      },
      "metric_set": {
        "stat_keys": [
          "cpu|capacity_usagepct_average",
          "cpu|coreUtilization_average",
          "mem|active_average"
        ]
      }
    }
  ],
  "export_config": {
    "formats": ["csv", "xlsx", "json"],
    "timezone": "America/Chicago"
  }
}
```

Pre-built profiles covering the three primary operational scenarios are included in `examples/profiles/`:
- `scenario_a_all_hosts.json`
- `scenario_b_selected_vms.json`
- `scenario_c_two_vm_groups.json`

---

## Operational & Security Considerations

- **Blast Radius**: `ops-metric-harvest` is read-only against the VCF Operations Suite API. It creates no objects, alters no configurations, and issues only GET requests for inventory and metric data.
- **Loopback Binding**: The web GUI binds strictly to `127.0.0.1` and generates a cryptographically random session token on startup. Remote hosts cannot connect to the GUI.
- **CSRF Protection**: State-changing API endpoints require the matching session token in the `X-Session` header.
- **Secrets Handling**: Authentication credentials and tokens are kept in memory only during collection and are immediately discarded. Profile files and export outputs strictly strip and redact credentials.
- **Formula Injection Defense**: All CSV and Excel string cells beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` are prefixed with a single quote to prevent code execution when opened in spreadsheet software.
- **Resource Exhaustion Prevention**: Historical queries are automatically chunked into batches of up to 40 resources to avoid HTTP 414 URL length errors and proxy buffer limits.

---

## Acceptance Criteria Checklist

| Requirement | Description | Status | Evidence |
|---|---|---|---|
| **AC1** | All hosts: Historical query across all `HostSystem`s with CSV and XLSX export | PASS | `tests/test_scenarios.py::test_scenario_a_all_hosts` |
| **AC2** | Selected VMs: Explicit selection of three VMs | PASS | `tests/test_scenarios.py::test_scenario_b_selected_vms` |
| **AC3** | Distinct VM groups: Multi-group collection with shared overlap and clean attribution | PASS | `tests/test_scenarios.py::test_scenario_c_distinct_vm_groups_with_overlap` |
| **AC4** | Profile reproducibility: Create profile, save JSON, execute identically via CLI | PASS | `tests/test_scenarios.py::test_scenario_d_profile_reuse` |
| **AC5** | Discovery: Paginated inventory discovery, name search, metric catalogue lookup | PASS | `tests/test_client.py::test_client_pagination`, `test_engine.py` |
| **AC6** | Failure behavior: Throttling, bad auth, duplicate names, cancellation | PASS | `tests/test_client.py`, `test_engine.py`, `test_scenarios.py` |
| **AC7** | Data integrity: Misaligned timestamps, null alignment, value preservation | PASS | `tests/test_scenarios.py::test_scenario_e_error_resilience` |
| **AC8** | Distribution: Packaged executables with signing and notarization hooks | PASS | PyInstaller spec, `packaging/build.py`, CI & Release workflows |
| **AC9** | Automation: Non-interactive execution, secure credentials, exit codes | PASS | `tests/test_cli.py`, `test_scenarios.py` |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
Attribution is preserved for reference works by Scott Robert Bowe (`vropsMetrics`) and Brock Peterson (`vcf_operations_metric_picker`).
