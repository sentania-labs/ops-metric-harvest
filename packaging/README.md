# Packaging and Release Engineering

## Architecture

`ops-metric-harvest` is packaged as a standalone executable with zero external runtime dependencies using PyInstaller.

Users on Windows, macOS, and Linux do not need Python, PowerShell, Node.js, or any package managers installed to run the application.

## Build targets

- **Linux x64**: Standalone ELF binary (`ops-metric-harvest`), with SHA-256 integrity checksums.
- **Windows x64**: Standalone PE executable (`ops-metric-harvest.exe`), signed with Authenticode.
- **macOS (Apple Silicon arm64 & Intel x86_64)**: Standalone Mach-O binary (`ops-metric-harvest`), Developer ID signed and Apple notarized.

## Local compilation

To build a standalone executable on the current host:

```bash
python3 packaging/build.py
```

Outputs are placed in `dist/`:
- `dist/ops-metric-harvest` (or `.exe` on Windows)
- `dist/ops-metric-harvest.sha256`
- `dist/manifest-<platform>-<arch>.json`

## Production signing requirements

Production releases require valid credentials supplied through secure CI environment secrets:

### Windows Authenticode
- `WINDOWS_SIGNING_CERT`: Path to PKCS#12 certificate (.pfx) or HSM key identifier.
- `WINDOWS_SIGNING_PASSWORD`: Certificate passphrase.
- `TIMESTAMP_SERVER`: Authenticode RFC 3161 timestamp authority (default: `http://timestamp.digicert.com`).

### macOS Developer ID & Notarization
- `MACOS_CERTIFICATE_IDENTITY`: Apple Developer ID Application certificate identity name.
- `APPLE_ID`: Developer account email.
- `APPLE_TEAM_ID`: 10-character Team ID.
- `APPLE_APP_SPECIFIC_PASSWORD`: App-specific password for `notarytool`.

### Separation of development and release builds

When signing credentials are not configured, `packaging/build.py` emits an unsigned development build and records `"signed": false`, `"production_ready": false` in the build manifest. Unsigned builds must not be promoted to production releases.
