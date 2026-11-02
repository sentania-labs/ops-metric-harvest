# Packaging and Release Engineering

## Architecture

`ops-metric-harvest` is packaged as a standalone executable using PyInstaller onefile, bundling Python, PySide6, Qt platform/image plugins, and the Lattice theme assets. Linux still needs the host graphical libraries described below.

Users on Windows, macOS, and Linux do not need Python, PowerShell, Node.js, or any package managers installed to run the application.

## Build targets

- **Linux x64**: Standalone ELF binary (`ops-metric-harvest`), with SHA-256 integrity checksums.
- **Windows x64**: Standalone PE executable (`ops-metric-harvest.exe`), signed with Authenticode.
- **macOS (Apple Silicon arm64 & Intel x86_64)**: Standalone Mach-O binary (`ops-metric-harvest`), Developer ID signed and Apple notarized.

## Local compilation

To build a standalone executable on the current host:

```bash
python3 -m pip install -e ".[yaml]" pyinstaller
python3 packaging/build.py
```

Outputs are placed in `dist/`:
- `dist/ops-metric-harvest` (or `.exe` on Windows)
- `dist/ops-metric-harvest.sha256`
- `dist/manifest-<platform>-<arch>.json`

## Native UI assets and smoke

The spec resolves paths from its own directory, so the Makefile and `packaging/build.py` use the same build on Windows and the existing Linux/macOS targets. `make build-windows PYTHON=python` builds the Windows onefile executable on Windows. PyInstaller's QtWidgets/QtGui hooks collect platform plugins; package data includes both QSS files and the palette JSON. QtWebEngine is not included. The executable retains console support for CLI commands. Native launches hide a console created for the executable itself, while leaving an existing caller terminal visible.

Vendored Lattice distribution: `sentania-labs/lattice` commit `cc4804b7da1e03875fa7452864601fd75de2be0d`. Assets are copied unchanged from `dist/` to `ops_metric_harvest/gui/assets/`. The app uses Fusion and reapplies QPalette and QSS together when changing themes.

On Linux, install `xvfb`, `libegl1`, `libopengl0`, `libxcb-cursor0`, and `libxkbcommon-x11-0` for the Xvfb smoke. Run:

```bash
xvfb-run -a ./dist/ops-metric-harvest gui --screenshot /tmp/connection.png
```

On Windows, run `dist\ops-metric-harvest.exe gui --screenshot connection.png`. CI captures the native connection screen for each existing build target, including an Xvfb launch on Linux. The screenshot option exits after rendering and needs no server credentials.

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
