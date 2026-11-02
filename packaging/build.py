#!/usr/bin/env python3
"""Build and packaging script for ops-metric-harvest with checksums and signing hooks."""

import hashlib
import json
import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def sha256_file(path: str) -> str:
    """Compute hex SHA-256 digest of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sign_windows_binary(binary_path: str) -> bool:
    """Windows Authenticode signing hook using SignTool."""
    cert_path = os.environ.get("WINDOWS_SIGNING_CERT")
    cert_pass = os.environ.get("WINDOWS_SIGNING_PASSWORD")
    timestamp_url = os.environ.get("TIMESTAMP_SERVER", "http://timestamp.digicert.com")

    if not cert_path or not os.path.exists(cert_path):
        print("Notice: WINDOWS_SIGNING_CERT not set or not found. Output binary is unsigned.", file=sys.stderr)
        return False

    cmd = [
        "signtool.exe", "sign",
        "/f", cert_path,
        "/tr", timestamp_url,
        "/td", "sha256",
        "/fd", "sha256",
    ]
    if cert_pass:
        cmd.extend(["/p", cert_pass])
    cmd.append(binary_path)

    print(f"Signing {binary_path} with Windows Authenticode...", file=sys.stderr)
    res = subprocess.run(cmd)
    return res.returncode == 0


def sign_and_notarize_macos(binary_path: str) -> bool:
    """macOS Developer ID signing and Apple notarization hook."""
    identity = os.environ.get("MACOS_CERTIFICATE_IDENTITY")
    apple_id = os.environ.get("APPLE_ID")
    team_id = os.environ.get("APPLE_TEAM_ID")
    password = os.environ.get("APPLE_APP_SPECIFIC_PASSWORD")

    if not identity:
        print("Notice: MACOS_CERTIFICATE_IDENTITY not set. Output binary is unsigned.", file=sys.stderr)
        return False

    print(f"Signing {binary_path} with Developer ID...", file=sys.stderr)
    sign_cmd = [
        "codesign", "--deep", "--force", "--options", "runtime",
        "--sign", identity,
        binary_path,
    ]
    if subprocess.run(sign_cmd).returncode != 0:
        return False

    if apple_id and team_id and password:
        print(f"Submitting {binary_path} for Apple notarization...", file=sys.stderr)
        notarize_cmd = [
            "xcrun", "notarytool", "submit", binary_path,
            "--apple-id", apple_id,
            "--team-id", team_id,
            "--password", password,
            "--wait",
        ]
        return subprocess.run(notarize_cmd).returncode == 0
    else:
        print("Notice: Apple notarization credentials missing. Binary signed without notarization.", file=sys.stderr)
        return True


def sign_linux_binary(binary_path: str) -> bool:
    """Linux GPG detached signature hook."""
    gpg_key = os.environ.get("GPG_KEY_ID")
    gpg_passphrase = os.environ.get("GPG_PASSPHRASE")

    if not gpg_key:
        print("Notice: GPG_KEY_ID not set. Linux binary not GPG-signed (SHA-256 integrity only).", file=sys.stderr)
        return False

    sig_file = f"{binary_path}.asc"
    if os.path.exists(sig_file):
        os.remove(sig_file)

    cmd = ["gpg", "--batch", "--yes", "--detach-sign", "--armor", "-u", gpg_key]
    if gpg_passphrase:
        cmd.extend(["--pinentry-mode", "loopback", "--passphrase", gpg_passphrase])
    cmd.extend(["-o", sig_file, binary_path])

    print(f"Signing {binary_path} with GPG ({gpg_key})...", file=sys.stderr)
    res = subprocess.run(cmd)
    return res.returncode == 0


def main() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    spec_path = os.path.join(HERE, "ops-metric-harvest.spec")

    print(f"Building ops-metric-harvest for {system} ({machine})...")
    res = subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        spec_path,
    ], cwd=ROOT)

    if res.returncode != 0:
        print("PyInstaller build failed.", file=sys.stderr)
        return 1

    dist_dir = os.path.join(ROOT, "dist")
    binary_name = "ops-metric-harvest.exe" if system == "windows" else "ops-metric-harvest"
    binary_path = os.path.join(dist_dir, binary_name)

    if not os.path.exists(binary_path):
        print(f"Expected binary {binary_path} not found.", file=sys.stderr)
        return 1

    # Apply platform signing if credentials exist
    signed = False
    if system == "windows":
        signed = sign_windows_binary(binary_path)
    elif system == "darwin":
        signed = sign_and_notarize_macos(binary_path)
    elif system == "linux":
        signed = sign_linux_binary(binary_path)
    else:
        print(f"Platform {system} ready at {binary_path}. Generating integrity hashes...", file=sys.stderr)

    # Compute checksum
    checksum = sha256_file(binary_path)
    checksum_file = f"{binary_path}.sha256"
    with open(checksum_file, "w") as f:
        f.write(f"{checksum}  {os.path.basename(binary_path)}\n")

    manifest = {
        "artifact": os.path.basename(binary_path),
        "platform": system,
        "arch": machine,
        "sha256": checksum,
        "signed": signed,
        "production_ready": signed if system in ("windows", "darwin") else True,
    }

    manifest_path = os.path.join(dist_dir, f"manifest-{system}-{machine}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Build completed successfully:")
    print(f"  Artifact: {binary_path}")
    print(f"  SHA-256:  {checksum}")
    print(f"  Signed:   {signed}")
    print(f"  Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
