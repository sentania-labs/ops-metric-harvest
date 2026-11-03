"""Command-line interface for VCF Operations Metrics Explorer."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime
from typing import Any, List, Optional

from ops_metric_harvest.client import OpsAuthError, OpsClient, OpsClientError
from ops_metric_harvest.engine import CollectionEngine, EngineError
from ops_metric_harvest.exporters import (
    export_csv_long,
    export_csv_wide,
    export_json,
    export_table,
    export_xlsx,
)
from ops_metric_harvest.models import (
    CollectionGroup,
    CollectionJob,
    MetricSet,
    ObjectSelector,
    TimeRange,
)
from ops_metric_harvest.profiles import ProfileValidationError, load_profile
from ops_metric_harvest.starter_metrics import STARTER_METRIC_SETS
from ops_metric_harvest.version import __app_name__, __version__


def eprint(*args: Any, **kwargs: Any) -> None:
    """Print to stderr."""
    print(*args, file=sys.stderr, flush=True, **kwargs)


def get_client(
    server: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    token: Optional[str] = None,
    auth_source: Optional[str] = None,
    insecure: bool = False,
    timeout: int = 120,
    quiet: bool = False,
    ca_bundle: Optional[str] = None,
) -> OpsClient:
    if not server or not str(server).strip():
        eprint("Error: VCF Operations server address is required. Use --server or specify in profile.")
        sys.exit(1)

    tok = token or os.environ.get("VCFOPS_TOKEN")
    verify = not insecure

    try:
        client = OpsClient(server=server, token=tok, verify=verify, timeout=timeout, ca_bundle=ca_bundle)
    except OSError as e:
        eprint(f"Error: could not load trusted CA bundle '{ca_bundle}': {e}")
        sys.exit(1)

    if not tok:
        username = user or os.environ.get("VCFOPS_USER")
        if not username:
            if sys.stdin.isatty():
                username = input("VCF Operations Username: ").strip()
            else:
                eprint("Error: Username or token required. Set VCFOPS_USER/VCFOPS_TOKEN or use --user/--token.")
                sys.exit(1)

        pwd = password or os.environ.get("VCFOPS_PASSWORD")
        if not pwd:
            if sys.stdin.isatty():
                pwd = getpass.getpass(f"Password for {username}: ")
            else:
                eprint("Error: Password required. Set VCFOPS_PASSWORD or provide interactively.")
                sys.exit(1)

        source = auth_source or os.environ.get("VCFOPS_AUTH_SOURCE")
        if not quiet:
            eprint(f"Authenticating as '{username}' against {server}...")
        try:
            client.login(username, pwd, source)
            if not quiet:
                eprint("Authentication successful.")
        except (OpsAuthError, OpsClientError) as e:
            eprint(f"Authentication failed: {e}")
            sys.exit(1)

    return client


def cmd_connect_test(args: argparse.Namespace) -> int:
    """Test connection and authentication to VCF Operations server."""
    client = get_client(
        server=args.server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source,
        insecure=args.insecure,
        timeout=args.timeout,
        quiet=args.quiet,
    )
    try:
        res = client.test_connection()
        if not args.quiet:
            eprint(f"Connected successfully to {args.server}")
        print(json.dumps(res, indent=2))
        return 0
    except Exception as e:
        eprint(f"Connection test failed: {e}")
        return 1


def cmd_objects_kinds(args: argparse.Namespace) -> int:
    """List available resource kinds."""
    client = get_client(
        server=args.server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source,
        insecure=args.insecure,
        timeout=args.timeout,
        quiet=args.quiet,
    )
    try:
        kinds = client.list_resource_kinds(args.adapter)
        for k in kinds:
            print(k)
        return 0
    except Exception as e:
        eprint(f"Failed to list resource kinds: {e}")
        return 1


def cmd_objects_search(args: argparse.Namespace) -> int:
    """Search for resources of a specified kind."""
    client = get_client(
        server=args.server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source,
        insecure=args.insecure,
        timeout=args.timeout,
        quiet=args.quiet,
    )
    try:
        results = client.search_resources(
            resource_kind=args.kind,
            name_query=args.query,
            max_resources=args.limit,
            adapter_kind=args.adapter,
        )
        if args.format == "json":
            print(json.dumps(results, indent=2))
        else:
            print(f"{'Name':<35}  {'Resource ID':<38}  {'Resource Kind'}")
            print(f"{'-' * 35}  {'-' * 38}  {'-' * 15}")
            for r in results:
                print(f"{r['name']:<35}  {r['resourceId']:<38}  {r['resourceKind']}")
        return 0
    except Exception as e:
        eprint(f"Object search failed: {e}")
        return 1


def cmd_metrics_list(args: argparse.Namespace) -> int:
    """List metric keys available for a resource kind."""
    client = get_client(
        server=args.server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source,
        insecure=args.insecure,
        timeout=args.timeout,
        quiet=args.quiet,
    )
    try:
        cat = client.get_stat_keys(adapter_kind=args.adapter, resource_kind=args.kind)
        keys = sorted(cat.keys())
        if args.filter:
            filt = args.filter.lower()
            keys = [k for k in keys if filt in k.lower() or filt in cat[k].get("name", "").lower()]

        if args.format == "json":
            filtered_dict = {k: cat[k] for k in keys}
            print(json.dumps(filtered_dict, indent=2))
        else:
            print(f"{'Stat Key':<45}  {'Display Name':<35}  {'Unit'}")
            print(f"{'-' * 45}  {'-' * 35}  {'-' * 8}")
            for k in keys:
                item = cat[k]
                print(f"{k:<45}  {item.get('name', k):<35}  {item.get('unit', '')}")
        return 0
    except Exception as e:
        eprint(f"Metric catalogue lookup failed: {e}")
        return 1


def cmd_profiles_validate(args: argparse.Namespace) -> int:
    """Validate a collection profile file."""
    try:
        job, warnings = load_profile(args.profile_path)
        for w in warnings:
            eprint(f"WARNING: {w}")
        eprint(f"Profile '{args.profile_path}' is valid.")
        eprint(f"Job Name: {job.name} (Groups: {len(job.groups)}, Mode: {job.time_range.mode})")
        return 0
    except (FileNotFoundError, ProfileValidationError) as e:
        eprint(f"Profile validation failed: {e}")
        return 1


def run_collection_and_export(
    job: CollectionJob,
    client: OpsClient,
    formats: List[str],
    output_base: Optional[str],
    timezone_name: str = "America/Chicago",
    wide: bool = False,
    quiet: bool = False,
    workers: int = 4,
) -> int:
    """Execute collection and export results to requested formats."""
    def progress_callback(msg: str, done: int, total: int) -> None:
        if not quiet:
            if total > 0:
                eprint(f"[{done}/{total}] {msg}")
            else:
                eprint(f"[*] {msg}")

    engine = CollectionEngine(client=client, max_workers=workers, progress_cb=progress_callback)
    try:
        result = engine.execute(job)
    except EngineError as e:
        eprint(f"Collection aborted: {e}")
        return 1
    except Exception as e:
        eprint(f"Unexpected collection error: {e}")
        return 1

    if not quiet:
        eprint(f"Completed with status '{result.status}'. Total samples: {len(result.samples)}")
        for w in result.warnings:
            eprint(f"WARNING: {w}")
        for err in result.errors:
            eprint(f"ERROR: {err}")

    # Export
    default_base = f"{job.name.lower().replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}"
    base_path = output_base or default_base

    # If output_base is '-', handle stdout for single format
    if output_base == "-":
        fmt = formats[0] if formats else "table"
        if fmt == "json":
            export_json(result, stream=sys.stdout)
        elif fmt == "csv":
            if wide:
                export_csv_wide(result, stream=sys.stdout, tz_name=timezone_name)
            else:
                export_csv_long(result, stream=sys.stdout, tz_name=timezone_name)
        elif fmt == "table":
            export_table(result, stream=sys.stdout, tz_name=timezone_name)
        return 0 if result.status == "success" else 2

    for fmt in formats:
        f = fmt.strip().lower()
        if f == "csv":
            csv_path = f"{base_path}.csv"
            if wide:
                export_csv_wide(result, file_path=csv_path, tz_name=timezone_name)
            else:
                export_csv_long(result, file_path=csv_path, tz_name=timezone_name)
            if not quiet:
                eprint(f"Exported CSV: {csv_path}")
        elif f == "csv_wide":
            csv_path = f"{base_path}.wide.csv"
            export_csv_wide(result, file_path=csv_path, tz_name=timezone_name)
            if not quiet:
                eprint(f"Exported wide CSV: {csv_path}")
        elif f == "xlsx":
            xlsx_path = f"{base_path}.xlsx"
            export_xlsx(result, file_path=xlsx_path, tz_name=timezone_name)
            if not quiet:
                eprint(f"Exported Excel: {xlsx_path}")
        elif f == "json":
            json_path = f"{base_path}.json"
            export_json(result, file_path=json_path)
            if not quiet:
                eprint(f"Exported JSON: {json_path}")
        elif f == "table":
            export_table(result, stream=sys.stdout, tz_name=timezone_name)

    if result.status == "error":
        return 1
    elif result.status == "partial":
        return 2
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Run an ad-hoc collection job from command-line options."""
    client = get_client(
        server=args.server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source,
        insecure=args.insecure,
        timeout=args.timeout,
        quiet=args.quiet,
    )

    # Parse stat keys
    raw_keys: List[str] = []
    if args.stat_keys:
        for item in args.stat_keys:
            raw_keys.extend([k.strip() for k in item.split(",") if k.strip()])
    if not raw_keys:
        raw_keys = [k["key"] for k in STARTER_METRIC_SETS.get(args.kind, STARTER_METRIC_SETS["HostSystem"][:4])]

    # Determine object selection mode
    selector = ObjectSelector(resource_kind=args.kind, adapter_kind=args.adapter)
    if args.objects == "all" or not args.objects:
        selector.selection_mode = "all"
    elif os.path.exists(args.objects) and args.objects.endswith(".csv"):
        selector.selection_mode = "imported"
        selector.csv_path = args.objects
    else:
        # Comma-separated list of IDs or names
        import re
        items = [i.strip() for i in args.objects.split(",") if i.strip()]
        selector.selection_mode = "explicit"
        selector.names = items
        selector.resource_ids = [i for i in items if re.match(r"^[0-9a-fA-F-]{32,38}$", i)]

    group = CollectionGroup(
        name=f"CLI {args.kind} Group",
        resource_kind=args.kind,
        selector=selector,
        metric_set=MetricSet(stat_keys=raw_keys),
    )

    # Build time range
    if args.max_samples and (args.start or args.end):
        eprint("Error: Cannot combine --max-samples with --start/--end absolute time range.")
        return 1

    if bool(args.start) != bool(args.end):
        eprint("Error: Both --start and --end must be provided for an absolute time range.")
        return 1

    if args.start and args.end:
        time_range = TimeRange(
            mode="absolute",
            start_time=args.start,
            end_time=args.end,
            interval_minutes=args.interval,
            interval_type=args.interval_type,
            rollup_type=args.rollup,
        )
    else:
        time_range = TimeRange(
            mode="relative",
            relative_preset=args.sample_size or "7d",
            interval_minutes=args.interval,
            interval_type=args.interval_type,
            rollup_type=args.rollup,
            max_samples=args.max_samples,
        )

    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    job = CollectionJob(
        name=f"{args.kind}_Collection",
        groups=[group],
        time_range=time_range,
        connection={"server": args.server, "verify_ssl": not args.insecure},
    )

    return run_collection_and_export(
        job=job,
        client=client,
        formats=formats,
        output_base=args.output,
        timezone_name=args.timezone,
        wide=args.wide,
        quiet=args.quiet,
        workers=args.workers,
    )


def cmd_profiles_run(args: argparse.Namespace) -> int:
    """Execute a collection job from a saved profile."""
    try:
        job, warnings = load_profile(args.profile_path)
        if not args.quiet:
            for w in warnings:
                eprint(f"WARNING: {w}")
    except (FileNotFoundError, ProfileValidationError) as e:
        eprint(f"Could not load profile: {e}")
        return 1

    server = args.server or job.connection.get("server")
    if not server:
        eprint("Error: Server address must be specified in the profile or with --server.")
        return 1

    insecure = args.insecure if args.insecure is not None else (not job.connection.get("verify_ssl", True))
    client = get_client(
        server=server,
        user=args.user,
        password=args.password,
        token=args.token,
        auth_source=args.auth_source or job.connection.get("auth_source"),
        insecure=insecure,
        quiet=args.quiet,
        ca_bundle=job.connection.get("ca_bundle") or None,
    )

    formats = [f.strip() for f in args.format.split(",") if f.strip()] if args.format else job.export_config.get("formats", ["csv", "xlsx"])
    output_base = args.output or job.export_config.get("output_path")
    if not output_base and job.export_config.get("output_dir"):
        import tempfile
        from pathlib import Path
        folder = Path(job.export_config["output_dir"]).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        output_base = str(Path(tempfile.mkdtemp(prefix="harvest-", dir=folder)) / "metrics")
    tz = args.timezone or job.export_config.get("timezone", "America/Chicago")
    wide = args.wide or job.export_config.get("wide_format", False)

    return run_collection_and_export(
        job=job,
        client=client,
        formats=formats,
        output_base=output_base,
        timezone_name=tz,
        wide=wide,
        quiet=args.quiet,
        workers=args.workers,
    )


def cmd_gui(args: argparse.Namespace) -> int:
    """Launch the native Qt desktop application."""
    from ops_metric_harvest.gui.app import run_gui
    return run_gui(theme=args.theme, screenshot=args.screenshot)


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog=__app_name__,
        description="VCF Operations Metrics Explorer: discover objects, pick metrics, and export historical performance data.",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Common connection options
    conn_parent = argparse.ArgumentParser(add_help=False)
    conn_parent.add_argument("--server", help="VCF Operations server FQDN or IP (or set in profile)")
    conn_parent.add_argument("--user", help="Username for authentication (or set VCFOPS_USER)")
    conn_parent.add_argument("--password", help="Password for authentication (or set VCFOPS_PASSWORD)")
    conn_parent.add_argument("--token", help="Existing OpsToken (or set VCFOPS_TOKEN)")
    conn_parent.add_argument("--auth-source", dest="auth_source", help="Authentication source (e.g. AD/vIDM domain)")
    conn_parent.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification (lab use only)")
    conn_parent.add_argument("--timeout", type=int, default=120, help="HTTP request timeout in seconds (default 120)")
    conn_parent.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error progress output")

    # 1. connect test
    p_conn = subparsers.add_parser("connect", help="Connection utilities")
    conn_sub = p_conn.add_subparsers(dest="connect_subcommand", required=True)
    p_test = conn_sub.add_parser("test", parents=[conn_parent], help="Test connection to VCF Operations server")
    p_test.set_defaults(func=cmd_connect_test)

    # 2. objects
    p_objs = subparsers.add_parser("objects", help="Discover and search inventory objects")
    objs_sub = p_objs.add_subparsers(dest="objects_subcommand", required=True)

    p_kinds = objs_sub.add_parser("kinds", parents=[conn_parent], help="List supported resource kinds")
    p_kinds.add_argument("--adapter", default="VMWARE", help="Adapter kind (default: VMWARE)")
    p_kinds.set_defaults(func=cmd_objects_kinds)

    p_search = objs_sub.add_parser("search", parents=[conn_parent], help="Search objects by kind and name")
    p_search.add_argument("--kind", default="VirtualMachine", help="Resource kind (default: VirtualMachine)")
    p_search.add_argument("--adapter", default="VMWARE", help="Adapter kind (default: VMWARE)")
    p_search.add_argument("--query", help="Substring filter on object name")
    p_search.add_argument("--limit", type=int, default=50, help="Maximum objects to return")
    p_search.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    p_search.set_defaults(func=cmd_objects_search)

    # 3. metrics
    p_metrics = subparsers.add_parser("metrics", help="Discover metric definitions")
    metrics_sub = p_metrics.add_subparsers(dest="metrics_subcommand", required=True)
    p_mlist = metrics_sub.add_parser("list", parents=[conn_parent], help="List metrics for a resource kind")
    p_mlist.add_argument("--kind", default="HostSystem", help="Resource kind (default: HostSystem)")
    p_mlist.add_argument("--adapter", default="VMWARE", help="Adapter kind (default: VMWARE)")
    p_mlist.add_argument("--filter", help="Search filter on metric key or display name")
    p_mlist.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    p_mlist.set_defaults(func=cmd_metrics_list)

    # 4. profiles
    p_profiles = subparsers.add_parser("profiles", help="Manage and run collection profiles")
    profiles_sub = p_profiles.add_subparsers(dest="profiles_subcommand", required=True)

    p_pval = profiles_sub.add_parser("validate", help="Validate a collection profile JSON")
    p_pval.add_argument("profile_path", help="Path to profile JSON file")
    p_pval.set_defaults(func=cmd_profiles_validate)

    p_prun = profiles_sub.add_parser("run", parents=[conn_parent], help="Execute a saved collection profile")
    p_prun.add_argument("profile_path", help="Path to profile JSON file")
    p_prun.add_argument("--format", help="Override output formats (comma-separated: csv,xlsx,json,table)")
    p_prun.add_argument("--output", help="Override output path base")
    p_prun.add_argument("--timezone", help="Timezone for local time column (default: America/Chicago)")
    p_prun.add_argument("--wide", action="store_true", help="Export wide format CSV")
    p_prun.add_argument("--workers", type=int, default=4, help="Worker concurrency")
    p_prun.set_defaults(func=cmd_profiles_run)

    # 5. collect (ad-hoc)
    p_collect = subparsers.add_parser("collect", parents=[conn_parent], help="Ad-hoc metric collection")
    p_collect.add_argument("--kind", default="HostSystem", help="Resource kind (default: HostSystem)")
    p_collect.add_argument("--adapter", default="VMWARE", help="Adapter kind (default: VMWARE)")
    p_collect.add_argument("--objects", default="all", help="'all', comma-separated names/IDs, or path to objects.csv")
    p_collect.add_argument("--stat-keys", "--stat_keys", nargs="+", help="Metric keys to retrieve")
    p_collect.add_argument("--sample-size", "--sample_size", default="7d", help="Relative range: 1h, 12h, 1d, 7d, 30d")
    p_collect.add_argument("--max-samples", "--max_samples", type=int, help="Exact latest N samples per metric")
    p_collect.add_argument("--start", help="Start time in ISO 8601 format (e.g. 2026-10-01T00:00:00Z)")
    p_collect.add_argument("--end", help="End time in ISO 8601 format")
    p_collect.add_argument("--interval", type=int, default=5, help="Interval in minutes (default: 5)")
    p_collect.add_argument("--interval-type", default="MINUTES", choices=["MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS", "YEARS", "NONE"])
    p_collect.add_argument("--rollup", default="AVG", choices=["AVG", "SUM", "MIN", "MAX", "NONE", "LATEST", "COUNT"])
    p_collect.add_argument("--format", default="both", help="Export format: csv, xlsx, json, table, both")
    p_collect.add_argument("--output", help="Base output file path or '-' for stdout")
    p_collect.add_argument("--wide", action="store_true", help="Export wide format CSV")
    p_collect.add_argument("--timezone", default="America/Chicago", help="Local timezone")
    p_collect.add_argument("--workers", type=int, default=4, help="Worker concurrency")
    p_collect.set_defaults(func=cmd_collect)

    # 6. gui
    p_gui = subparsers.add_parser("gui", help="Launch the native desktop application")
    p_gui.add_argument("--theme", choices=["light", "dark"], default="light", help="Lattice theme (default: light)")
    p_gui.add_argument("--screenshot", metavar="PNG", help="Capture the connection screen and exit (headless smoke)")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main() -> None:
    """Entry point for CLI."""
    parser = build_parser()
    # Default to GUI if no arguments provided
    if len(sys.argv) == 1:
        from ops_metric_harvest.gui.app import run_gui
        sys.exit(run_gui())

    args = parser.parse_args()
    if hasattr(args, "func"):
        # Map "both" format to "csv,xlsx"
        if hasattr(args, "format") and args.format == "both":
            args.format = "csv,xlsx"
        sys.exit(args.func(args))
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
