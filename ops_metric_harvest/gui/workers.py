"""Background operations. Only signals cross the Qt UI thread boundary."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from threading import Event
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, Signal
from ops_metric_harvest.client import OpsClient
from ops_metric_harvest.engine import CollectionEngine, EngineError
from ops_metric_harvest.models import CollectionResult
from ops_metric_harvest.exporters import export_csv_long, export_csv_wide, export_xlsx, export_json, export_table


def make_client(config, authenticate=True, client_type=OpsClient):
    server = config.get("server", "").strip()
    if not server:
        raise ValueError("Enter the VCF Operations URL.")
    parsed = urlsplit(server if "://" in server else "https://" + server)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTPS server URL without embedded credentials, query, or fragment.")
    client = client_type(server, verify=config.get("verify_ssl", True),
                         timeout=config.get("timeout", 120), retries=config.get("retries", 3),
                         ca_bundle=config.get("ca_bundle") or None)
    if authenticate:
        if config.get("auth_type") == "token":
            if not config.get("token"):
                raise ValueError("Enter an OpsToken.")
            client.set_token(config["token"])
        else:
            if not config.get("username") or not config.get("password"):
                raise ValueError("Enter a username and login password.")
            source = config.get("auth_source")
            client.login(config["username"], config["password"], None if source and source.lower() == "local" else source)
    return client


def collect(client, job, progress, should_stop):
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = CollectionEngine(client, progress_cb=progress, should_stop=should_stop).execute(job)
    except EngineError:
        if not should_stop():
            raise
        result = CollectionResult(job.name, started, datetime.now(timezone.utc).isoformat(), "cancelled")
    if should_stop():
        result.status = "cancelled"
    config = job.export_config
    files, errors = [], []
    if result.samples or result.status in ("success", "partial"):
        folder = Path(config["output_dir"]).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            destination = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("harvest-%Y%m%d-%H%M%S-"), dir=folder))
        except OSError as exc:
            return result, files, [f"Cannot create export folder: {exc}"]
        for fmt in config["formats"]:
            suffix = {"csv": "csv", "csv_wide": "wide.csv", "xlsx": "xlsx", "json": "json", "table": "txt"}[fmt]
            path = destination / f"metrics.{suffix}"
            try:
                progress(f"Exporting {fmt}…", 0, 0)
                tz = config.get("timezone", "America/Chicago")
                if fmt == "json":
                    export_json(result, file_path=str(path))
                elif fmt == "table":
                    with path.open("w", encoding="utf-8") as stream:
                        export_table(result, stream=stream, tz_name=tz, max_rows=len(result.samples))
                else:
                    {"csv": export_csv_long, "csv_wide": export_csv_wide, "xlsx": export_xlsx}[fmt](
                        result, file_path=str(path), tz_name=tz)
                files.append(str(path))
            except Exception as exc:
                errors.append(f"{fmt} export failed: {exc}")
    return result, files, errors


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)

    def __init__(self, operation, secrets=(), parent=None):
        super().__init__(parent)
        self.operation = operation
        self.secrets = [s for s in secrets if s]
        self.stop = Event()

    def redact(self, message):
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        return message

    def report(self, message, done, total):
        self.progress.emit(self.redact(message), done, total)

    def run(self):
        try:
            self.succeeded.emit(self.operation(self.report, self.stop.is_set))
        except Exception as exc:
            self.failed.emit(self.redact(str(exc)))
        finally:
            self.operation = None
            self.secrets.clear()
