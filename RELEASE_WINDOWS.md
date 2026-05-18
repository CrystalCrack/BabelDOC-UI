# BabelDOC UI Windows Release

## Install

1. Extract the release zip to a local folder, for example `C:\BabelDOC-UI`.
2. Double-click `Install-BabelDOC-UI.bat`.
3. Wait for setup to finish. The first install can take a while because Python packages and BabelDOC assets may be downloaded.
4. Launch `BabelDOC UI` from the desktop or Start Menu shortcut.

## Notes

- API settings are saved locally under `%APPDATA%\BabelDOC\ui_config.json`.
- The API key is protected with Windows DPAPI on Windows.
- The release uses a local virtual environment in `.venv` inside the extracted folder.
- If Python 3.10-3.13 is missing, the installer tries to install Python 3.12 with `winget`.
- If `winget` is unavailable, install Python 3.12 manually and run the installer again.

## Manual Launch

After installation, you can also start the UI by double-clicking `run_babeldoc_ui.bat`.
