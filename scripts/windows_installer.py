from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Callable


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


def _run_setup(install_dir: Path, log: Callable[[str], None]) -> None:
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
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(install_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line)
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Setup failed with exit code {return_code}")


def install_to(install_dir: Path, log: Callable[[str], None]) -> None:
    payload = _resource_dir() / PAYLOAD_NAME
    if not payload.exists():
        raise FileNotFoundError(f"Installer payload not found: {payload}")

    log(f"{APP_NAME} installer")
    log(f"Install location: {install_dir}")

    with tempfile.TemporaryDirectory(prefix="BabelDOC-UI-") as temp_text:
        temp_dir = Path(temp_text)
        log("Extracting application files...")
        with zipfile.ZipFile(payload) as archive:
            archive.extractall(temp_dir)

        source = temp_dir / INSTALL_DIR_NAME
        if not source.exists():
            raise FileNotFoundError("Payload root folder was not found after extraction.")

        log("Copying application files...")
        _copy_tree(source, install_dir)

    log("Installing runtime dependencies and creating shortcuts...")
    log("This can take several minutes on the first run.")
    _run_setup(install_dir, log)
    log(f"{APP_NAME} is installed.")
    log("Launch it from the desktop or Start Menu shortcut.")


def _console_main() -> int:
    try:
        install_to(_default_install_dir(), print)
        return 0
    except Exception as exc:
        print(f"Installation failed: {exc}")
        return 1


if os.name == "nt":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    comctl32 = ctypes.windll.comctl32
    gdi32 = ctypes.windll.gdi32

    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
    HGDIOBJ = getattr(wintypes, "HGDIOBJ", wintypes.HANDLE)
    HMODULE = getattr(wintypes, "HMODULE", wintypes.HANDLE)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    class INITCOMMONCONTROLSEX(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("dwICC", wintypes.DWORD),
        ]

    WS_OVERLAPPEDWINDOW = 0x00CF0000
    WS_THICKFRAME = 0x00040000
    WS_MAXIMIZEBOX = 0x00010000
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_TABSTOP = 0x00010000
    WS_BORDER = 0x00800000
    WS_VSCROLL = 0x00200000
    ES_AUTOHSCROLL = 0x0080
    ES_MULTILINE = 0x0004
    ES_AUTOVSCROLL = 0x0040
    ES_READONLY = 0x0800
    BS_DEFPUSHBUTTON = 0x0001
    PBS_MARQUEE = 0x0008
    CW_USEDEFAULT = 0x80000000
    SW_SHOW = 5
    WM_COMMAND = 0x0111
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_SETFONT = 0x0030
    WM_USER = 0x0400
    WM_APP = 0x8000
    EM_SETSEL = 0x00B1
    EM_REPLACESEL = 0x00C2
    PBM_SETMARQUEE = WM_USER + 10
    COLOR_BTNFACE = 15
    DEFAULT_GUI_FONT = 17
    IDC_ARROW = 32512
    IDI_APPLICATION = 32512
    ICC_PROGRESS_CLASS = 0x00000020
    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE = 0x00000040
    BIF_USENEWUI = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
    MAX_PATH = 260

    ID_BROWSE = 1001
    ID_INSTALL = 1002
    ID_CLOSE = 1003
    MSG_INSTALL_DONE = WM_APP + 1
    MSG_LOG = WM_APP + 2

    kernel32.GetModuleHandleW.restype = HMODULE
    user32.LoadCursorW.restype = HCURSOR
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.restype = LRESULT
    gdi32.GetStockObject.restype = HGDIOBJ
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p

    class WindowsInstallerGui:
        def __init__(self) -> None:
            self.hinstance = kernel32.GetModuleHandleW(None)
            self.class_name = "BabelDocUiInstallerWindow"
            self.wndproc = WNDPROC(self._wnd_proc)
            self.hwnd = None
            self.path_edit = None
            self.log_edit = None
            self.progress = None
            self.status_label = None
            self.browse_button = None
            self.install_button = None
            self.close_button = None
            self.installing = False
            self.install_succeeded = False
            self.log_queue: queue.Queue[str] = queue.Queue()

        def run(self) -> int:
            self._init_common_controls()
            self._register_class()
            self._create_window()
            self._message_loop()
            return 0 if self.install_succeeded else 1

        def _init_common_controls(self) -> None:
            try:
                data = INITCOMMONCONTROLSEX(
                    ctypes.sizeof(INITCOMMONCONTROLSEX), ICC_PROGRESS_CLASS
                )
                comctl32.InitCommonControlsEx(ctypes.byref(data))
            except Exception:
                pass

        def _register_class(self) -> None:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self.wndproc
            wc.hInstance = self.hinstance
            wc.hIcon = user32.LoadIconW(None, IDI_APPLICATION)
            wc.hIconSm = wc.hIcon
            wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
            wc.hbrBackground = wintypes.HBRUSH(COLOR_BTNFACE + 1)
            wc.lpszClassName = self.class_name
            user32.RegisterClassExW(ctypes.byref(wc))

        def _create_window(self) -> None:
            width = 720
            height = 480
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            x = max(0, int((screen_w - width) / 2))
            y = max(0, int((screen_h - height) / 2))
            style = WS_OVERLAPPEDWINDOW & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX
            self.hwnd = user32.CreateWindowExW(
                0,
                self.class_name,
                "BabelDOC UI Setup",
                style,
                x,
                y,
                width,
                height,
                None,
                None,
                self.hinstance,
                None,
            )
            if not self.hwnd:
                raise ctypes.WinError()
            self._create_controls()
            user32.ShowWindow(self.hwnd, SW_SHOW)
            user32.UpdateWindow(self.hwnd)

        def _create_controls(self) -> None:
            font = gdi32.GetStockObject(DEFAULT_GUI_FONT)
            controls = [
                self._control(
                    "STATIC",
                    "BabelDOC UI Setup",
                    24,
                    20,
                    660,
                    24,
                    0,
                ),
                self._control(
                    "STATIC",
                    "Choose an installation folder, then click Install. The first install downloads Python packages and BabelDOC assets.",
                    24,
                    52,
                    660,
                    34,
                    0,
                ),
                self._control("STATIC", "Installation folder", 24, 98, 220, 20, 0),
            ]
            self.path_edit = self._control(
                "EDIT",
                str(_default_install_dir()),
                24,
                122,
                540,
                25,
                WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
            )
            self.browse_button = self._control(
                "BUTTON", "Browse...", 574, 120, 110, 29, WS_TABSTOP, ID_BROWSE
            )
            self.progress = self._control(
                "msctls_progress32", "", 24, 166, 660, 18, PBS_MARQUEE
            )
            self.status_label = self._control(
                "STATIC", "Ready to install.", 24, 190, 660, 20, 0
            )
            self.log_edit = self._control(
                "EDIT",
                "",
                24,
                218,
                660,
                150,
                WS_BORDER
                | WS_VSCROLL
                | ES_MULTILINE
                | ES_AUTOVSCROLL
                | ES_READONLY,
            )
            self.install_button = self._control(
                "BUTTON",
                "Install",
                454,
                392,
                110,
                32,
                WS_TABSTOP | BS_DEFPUSHBUTTON,
                ID_INSTALL,
            )
            self.close_button = self._control(
                "BUTTON", "Close", 574, 392, 110, 32, WS_TABSTOP, ID_CLOSE
            )
            controls.extend(
                [
                    self.path_edit,
                    self.browse_button,
                    self.progress,
                    self.status_label,
                    self.log_edit,
                    self.install_button,
                    self.close_button,
                ]
            )
            for control in controls:
                user32.SendMessageW(control, WM_SETFONT, font, True)

        def _control(
            self,
            class_name: str,
            text: str,
            x: int,
            y: int,
            width: int,
            height: int,
            style: int,
            control_id: int = 0,
        ) -> wintypes.HWND:
            hwnd = user32.CreateWindowExW(
                0,
                class_name,
                text,
                WS_CHILD | WS_VISIBLE | style,
                x,
                y,
                width,
                height,
                self.hwnd,
                wintypes.HMENU(control_id),
                self.hinstance,
                None,
            )
            if not hwnd:
                raise ctypes.WinError()
            return hwnd

        def _message_loop(self) -> None:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        def _wnd_proc(self, hwnd, msg, wparam, lparam):
            if msg == WM_COMMAND:
                control_id = int(wparam) & 0xFFFF
                if control_id == ID_BROWSE:
                    self._choose_folder()
                    return 0
                if control_id == ID_INSTALL:
                    self._start_install()
                    return 0
                if control_id == ID_CLOSE:
                    self._close()
                    return 0
            if msg == MSG_INSTALL_DONE:
                self._drain_log_queue()
                self._finish_install(bool(wparam))
                return 0
            if msg == MSG_LOG:
                self._drain_log_queue()
                return 0
            if msg == WM_CLOSE:
                self._close()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _choose_folder(self) -> None:
            if self.installing:
                return
            display = ctypes.create_unicode_buffer(MAX_PATH)
            browse = BROWSEINFO()
            browse.hwndOwner = self.hwnd
            browse.pszDisplayName = display
            browse.lpszTitle = "Choose the BabelDOC UI installation folder"
            browse.ulFlags = BIF_USENEWUI
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(browse))
            if pidl:
                path_buffer = ctypes.create_unicode_buffer(MAX_PATH)
                if shell32.SHGetPathFromIDListW(pidl, path_buffer):
                    user32.SetWindowTextW(self.path_edit, path_buffer.value)
                ole32.CoTaskMemFree(pidl)

        def _start_install(self) -> None:
            if self.installing:
                return
            install_dir = self._get_window_text(self.path_edit).strip()
            if not install_dir:
                self._message("Please choose an installation folder.", "Missing folder")
                return
            self._set_installing(True)
            self.append_log(f"Selected folder: {install_dir}")
            thread = threading.Thread(
                target=self._install_worker,
                args=(Path(install_dir),),
                daemon=True,
            )
            thread.start()

        def _install_worker(self, install_dir: Path) -> None:
            success = False
            try:
                install_to(install_dir, self.queue_log)
                success = True
            except Exception as exc:
                self.queue_log(f"Installation failed: {exc}")
            finally:
                user32.PostMessageW(self.hwnd, MSG_INSTALL_DONE, int(success), 0)

        def _finish_install(self, success: bool) -> None:
            self.install_succeeded = success
            self._set_installing(False)
            if success:
                user32.SetWindowTextW(self.status_label, "Installation complete.")
                user32.SetWindowTextW(self.install_button, "Reinstall")
                self._message(
                    "BabelDOC UI has been installed. Launch it from the desktop or Start Menu shortcut.",
                    "Installation complete",
                )
            else:
                user32.SetWindowTextW(self.status_label, "Installation failed.")
                self._message(
                    "Installation failed. Check the log in the installer window.",
                    "Installation failed",
                )

        def _set_installing(self, installing: bool) -> None:
            self.installing = installing
            user32.EnableWindow(self.path_edit, not installing)
            user32.EnableWindow(self.browse_button, not installing)
            user32.EnableWindow(self.install_button, not installing)
            user32.SendMessageW(self.progress, PBM_SETMARQUEE, int(installing), 50)
            status = "Installing..." if installing else "Ready."
            user32.SetWindowTextW(self.status_label, status)

        def queue_log(self, text: str) -> None:
            if not text:
                return
            self.log_queue.put(text)
            user32.PostMessageW(self.hwnd, MSG_LOG, 0, 0)

        def _drain_log_queue(self) -> None:
            while True:
                try:
                    text = self.log_queue.get_nowait()
                except queue.Empty:
                    break
                self.append_log(text)

        def append_log(self, text: str) -> None:
            clean = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
            if not clean.endswith("\r\n"):
                clean += "\r\n"
            user32.SendMessageW(self.log_edit, EM_SETSEL, -1, -1)
            user32.SendMessageW(self.log_edit, EM_REPLACESEL, False, clean)

        def _get_window_text(self, hwnd) -> str:
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            return buffer.value

        def _close(self) -> None:
            if self.installing:
                self._message("Please wait for installation to finish.", "Installing")
                return
            user32.DestroyWindow(self.hwnd)

        def _message(self, text: str, title: str) -> None:
            user32.MessageBoxW(self.hwnd, text, title, 0)


def main() -> int:
    if os.name == "nt":
        try:
            return WindowsInstallerGui().run()
        except Exception as exc:
            user32.MessageBoxW(None, f"Installer failed to start: {exc}", APP_NAME, 0)
            return 1
    return _console_main()


if __name__ == "__main__":
    raise SystemExit(main())
