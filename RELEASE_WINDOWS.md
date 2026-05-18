# BabelDOC UI Windows Release

## One-Click Install

1. Double-click `BabelDOC-UI-Setup-<version>.exe`.
2. Wait for setup to finish. The first install can take a while because Python packages and BabelDOC assets may be downloaded.
3. Launch `BabelDOC UI` from the desktop or Start Menu shortcut.

The installer copies the app to `%LOCALAPPDATA%\BabelDOC-UI`, installs the local Python environment there, and creates shortcuts.

## Zip Fallback

If you are using a source zip instead of the setup exe:

1. Extract the zip to a local folder, for example `C:\BabelDOC-UI`.
2. Double-click `Install-BabelDOC-UI.bat`.
3. Launch `BabelDOC UI` from the desktop or Start Menu shortcut.

## Notes

- API settings are saved locally under `%APPDATA%\BabelDOC\ui_config.json`.
- The API key is protected with Windows DPAPI on Windows.
- The release uses a local virtual environment in `.venv` inside the extracted folder.
- If Python 3.10-3.13 is missing, the installer tries to install Python 3.12 with `winget`.
- If `winget` is unavailable, install Python 3.12 manually and run the installer again.

## Manual Launch

After installation, you can also start the UI by double-clicking `run_babeldoc_ui.bat`.

## Build Installer

From a configured workspace, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

The generated setup exe is written to `releases\`.
