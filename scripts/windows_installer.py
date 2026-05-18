from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


APP_NAME = "BabelDOC UI"
INSTALL_DIR_NAME = "BabelDOC-UI"
PAYLOAD_NAME = "BabelDOC-UI.zip"


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def _default_install_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / INSTALL_DIR_NAME


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _run_setup(install_dir: Path) -> None:
    setup_script = install_dir / "scripts" / "setup_windows.ps1"
    if not setup_script.exists():
        raise FileNotFoundError(f"Setup script not found: {setup_script}")

    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(setup_script),
    ]
    completed = subprocess.run(command, cwd=str(install_dir), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Setup failed with exit code {completed.returncode}")


def install() -> None:
    payload = _resource_dir() / PAYLOAD_NAME
    if not payload.exists():
        raise FileNotFoundError(f"Installer payload not found: {payload}")

    install_dir = _default_install_dir()
    print(f"{APP_NAME} installer")
    print(f"Install location: {install_dir}")
    print()

    with tempfile.TemporaryDirectory(prefix="BabelDOC-UI-") as temp_text:
        temp_dir = Path(temp_text)
        print("Extracting application files...")
        with zipfile.ZipFile(payload) as archive:
            archive.extractall(temp_dir)

        source = temp_dir / INSTALL_DIR_NAME
        if not source.exists():
            raise FileNotFoundError("Payload root folder was not found after extraction.")

        print("Copying application files...")
        _copy_tree(source, install_dir)

    print("Installing runtime dependencies and creating shortcuts...")
    print("This can take several minutes on the first run.")
    _run_setup(install_dir)

    print()
    print(f"{APP_NAME} is installed.")
    print("Launch it from the desktop or Start Menu shortcut.")


def main() -> int:
    try:
        install()
        return 0
    except Exception as exc:
        print()
        print(f"Installation failed: {exc}")
        return 1
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("Press Enter to exit...")


if __name__ == "__main__":
    raise SystemExit(main())
