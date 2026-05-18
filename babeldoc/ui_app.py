from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
import tkinter as tk

APP_NAME = "BabelDOC"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _app_data_dir() -> Path:
    root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / ".babeldoc"


APP_DATA_DIR = _app_data_dir()
SETTINGS_FILE = APP_DATA_DIR / "ui_config.json"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _protect_with_dpapi(secret: str) -> str:
    data = secret.encode("utf-8")
    in_blob, _buffer = _blob_from_bytes(data)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "BabelDOC UI",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect_with_dpapi(blob_text: str) -> str:
    protected = base64.b64decode(blob_text)
    in_blob, _buffer = _blob_from_bytes(protected)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return data.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def protect_secret(secret: str) -> tuple[str, str]:
    if not secret:
        return "none", ""
    if os.name == "nt":
        return "dpapi", _protect_with_dpapi(secret)
    return "base64", base64.b64encode(secret.encode("utf-8")).decode("ascii")


def unprotect_secret(storage: str, blob_text: str) -> str:
    if not blob_text:
        return ""
    if storage == "dpapi":
        return _unprotect_with_dpapi(blob_text)
    if storage == "base64":
        return base64.b64decode(blob_text).decode("utf-8")
    return ""


@dataclass
class UiSettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    protocol: str = "responses"
    output_mode: str = "dual"
    output_target: str = "default"
    output_dir: str = ""
    last_pdf: str = ""
    qps: int = 1
    ignore_cache: bool = True
    no_auto_extract_glossary: bool = True
    no_send_temperature: bool = True
    api_key_storage: str = "none"
    api_key_blob: str = ""


class BabelDocUi(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BabelDOC Local Translator")
        self.geometry("920x720")
        self.minsize(780, 620)

        self.settings = self._load_settings()
        self.api_key = self._load_api_key()
        self.process: subprocess.Popen | None = None
        self.worker: threading.Thread | None = None
        self.output_queue: queue.Queue = queue.Queue()
        self.last_output_dir: Path | None = None
        self.run_started_at = 0.0

        self._build_vars()
        self._build_ui()
        self._pump_output()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_vars(self) -> None:
        self.base_url_var = tk.StringVar(value=self.settings.base_url)
        self.api_key_var = tk.StringVar(value=self.api_key)
        self.model_var = tk.StringVar(value=self.settings.model)
        self.protocol_var = tk.StringVar(
            value="Responses API"
            if self.settings.protocol == "responses"
            else "Chat Completions API"
        )
        self.pdf_var = tk.StringVar(value=self.settings.last_pdf)
        self.output_mode_var = tk.StringVar(value=self.settings.output_mode)
        self.output_target_var = tk.StringVar(value=self.settings.output_target)
        self.output_dir_var = tk.StringVar(value=self.settings.output_dir)
        self.qps_var = tk.IntVar(value=max(1, int(self.settings.qps or 1)))
        self.ignore_cache_var = tk.BooleanVar(value=self.settings.ignore_cache)
        self.no_auto_glossary_var = tk.BooleanVar(
            value=self.settings.no_auto_extract_glossary
        )
        self.no_temperature_var = tk.BooleanVar(value=self.settings.no_send_temperature)
        self.show_key_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        credential = ttk.LabelFrame(root, text="API settings", padding=12)
        credential.grid(row=0, column=0, sticky="ew")
        credential.columnconfigure(1, weight=1)

        ttk.Label(credential, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(credential, textvariable=self.base_url_var).grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )

        ttk.Label(credential, text="API key").grid(row=1, column=0, sticky="w", pady=8)
        self.api_key_entry = ttk.Entry(
            credential, textvariable=self.api_key_var, show="*"
        )
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=8)
        ttk.Checkbutton(
            credential,
            text="Show",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
        ).grid(row=1, column=2, padx=(8, 0))

        ttk.Label(credential, text="Model").grid(row=2, column=0, sticky="w")
        ttk.Entry(credential, textvariable=self.model_var).grid(
            row=2, column=1, sticky="ew", padx=(10, 0)
        )

        ttk.Label(credential, text="Protocol").grid(row=2, column=2, sticky="e")
        ttk.Combobox(
            credential,
            textvariable=self.protocol_var,
            values=("Responses API", "Chat Completions API"),
            state="readonly",
            width=22,
        ).grid(row=2, column=3, sticky="ew", padx=(10, 0))

        file_box = ttk.LabelFrame(root, text="PDF and output", padding=12)
        file_box.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        file_box.columnconfigure(1, weight=1)

        ttk.Label(file_box, text="PDF").grid(row=0, column=0, sticky="w")
        ttk.Entry(file_box, textvariable=self.pdf_var).grid(
            row=0, column=1, sticky="ew", padx=(10, 8)
        )
        ttk.Button(file_box, text="Browse", command=self._choose_pdf).grid(
            row=0, column=2
        )

        mode_frame = ttk.Frame(file_box)
        mode_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(file_box, text="Output").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Dual only",
            variable=self.output_mode_var,
            value="dual",
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            mode_frame,
            text="Mono only",
            variable=self.output_mode_var,
            value="mono",
        ).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Both",
            variable=self.output_mode_var,
            value="both",
        ).pack(side=tk.LEFT, padx=(14, 0))

        target_frame = ttk.Frame(file_box)
        target_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(file_box, text="Folder").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Radiobutton(
            target_frame,
            text="Default: same as input PDF",
            variable=self.output_target_var,
            value="default",
            command=self._refresh_output_controls,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            target_frame,
            text="Custom",
            variable=self.output_target_var,
            value="custom",
            command=self._refresh_output_controls,
        ).pack(side=tk.LEFT, padx=(14, 0))

        self.output_entry = ttk.Entry(file_box, textvariable=self.output_dir_var)
        self.output_entry.grid(row=3, column=1, sticky="ew", padx=(10, 8), pady=(8, 0))
        self.output_browse = ttk.Button(
            file_box, text="Browse", command=self._choose_output_dir
        )
        self.output_browse.grid(row=3, column=2, pady=(8, 0))

        options = ttk.LabelFrame(root, text="Options", padding=12)
        options.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for idx in range(6):
            options.columnconfigure(idx, weight=1)

        ttk.Label(options, text="QPS").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(options, from_=1, to=20, textvariable=self.qps_var, width=8).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Checkbutton(
            options,
            text="Ignore translation cache",
            variable=self.ignore_cache_var,
        ).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(
            options,
            text="Disable auto glossary",
            variable=self.no_auto_glossary_var,
        ).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(
            options,
            text="Do not send temperature",
            variable=self.no_temperature_var,
        ).grid(row=0, column=4, sticky="w")

        buttons = ttk.Frame(root)
        buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(3, weight=1)
        self.save_button = ttk.Button(buttons, text="Save settings", command=self._save)
        self.save_button.grid(row=0, column=0)
        self.start_button = ttk.Button(
            buttons, text="Start translation", command=self._start_translation
        )
        self.start_button.grid(row=0, column=1, padx=(8, 0))
        self.stop_button = ttk.Button(
            buttons, text="Stop", command=self._stop_translation, state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=2, padx=(8, 0))
        self.open_button = ttk.Button(
            buttons,
            text="Open output folder",
            command=self._open_output_folder,
            state=tk.DISABLED,
        )
        self.open_button.grid(row=0, column=4)

        ttk.Label(root, textvariable=self.status_var).grid(
            row=5, column=0, sticky="ew", pady=(8, 0)
        )

        log_frame = ttk.LabelFrame(root, text="Run log", padding=8)
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=16, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self._refresh_output_controls()

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _choose_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*.*")),
        )
        if path:
            self.pdf_var.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_dir_var.set(path)
            self.output_target_var.set("custom")
            self._refresh_output_controls()

    def _refresh_output_controls(self) -> None:
        enabled = self.output_target_var.get() == "custom"
        state = tk.NORMAL if enabled else tk.DISABLED
        self.output_entry.configure(state=state)
        self.output_browse.configure(state=state)

    def _load_settings(self) -> UiSettings:
        if not SETTINGS_FILE.exists():
            return UiSettings()
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            defaults = asdict(UiSettings())
            defaults.update({k: v for k, v in data.items() if k in defaults})
            return UiSettings(**defaults)
        except Exception:
            return UiSettings()

    def _load_api_key(self) -> str:
        try:
            return unprotect_secret(
                self.settings.api_key_storage, self.settings.api_key_blob
            )
        except Exception:
            return ""

    def _collect_settings(self) -> UiSettings:
        storage, blob = protect_secret(self.api_key_var.get().strip())
        return UiSettings(
            base_url=self.base_url_var.get().strip(),
            model=self.model_var.get().strip(),
            protocol=(
                "responses"
                if self.protocol_var.get() == "Responses API"
                else "chat_completions"
            ),
            output_mode=self.output_mode_var.get(),
            output_target=self.output_target_var.get(),
            output_dir=self.output_dir_var.get().strip(),
            last_pdf=self.pdf_var.get().strip(),
            qps=max(1, int(self.qps_var.get() or 1)),
            ignore_cache=self.ignore_cache_var.get(),
            no_auto_extract_glossary=self.no_auto_glossary_var.get(),
            no_send_temperature=self.no_temperature_var.get(),
            api_key_storage=storage,
            api_key_blob=blob,
        )

    def _save(self) -> None:
        try:
            settings = self._collect_settings()
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.settings = settings
            self._append_log(f"Settings saved to {SETTINGS_FILE}\n")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _validate(self) -> tuple[Path, Path | None]:
        pdf_path = Path(self.pdf_var.get().strip().strip('"'))
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            raise ValueError("Please select an existing PDF file.")
        if not self.base_url_var.get().strip():
            raise ValueError("Base URL is required.")
        if not self.api_key_var.get().strip():
            raise ValueError("API key is required.")
        if not self.model_var.get().strip():
            raise ValueError("Model is required.")
        output_dir = None
        if self.output_target_var.get() == "custom":
            output_text = self.output_dir_var.get().strip()
            if not output_text:
                raise ValueError("Please choose a custom output folder.")
            output_dir = Path(output_text)
            output_dir.mkdir(parents=True, exist_ok=True)
        return pdf_path, output_dir

    def _start_translation(self) -> None:
        if self.process is not None:
            return
        try:
            pdf_path, output_dir = self._validate()
            self._save()
            command = self._build_command(pdf_path, output_dir)
            self.run_started_at = time.time()
            self.last_output_dir = output_dir or pdf_path.parent
            self._set_running(True)
            self._append_log("\n=== BabelDOC translation started ===\n")
            self._append_log(
                "API key is passed through the child process environment, not the command line.\n"
            )
            self.worker = threading.Thread(
                target=self._run_subprocess, args=(command,), daemon=True
            )
            self.worker.start()
        except Exception as exc:
            messagebox.showerror("Cannot start", str(exc))

    def _build_command(
        self, pdf_path: Path, output_dir: Path | None
    ) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "babeldoc.main",
            "--files",
            str(pdf_path),
            "--openai",
            "--openai-model",
            self.model_var.get().strip(),
            "--openai-base-url",
            self.base_url_var.get().strip(),
            "--qps",
            str(max(1, int(self.qps_var.get() or 1))),
            "--working-dir",
            str(APP_DATA_DIR / "work"),
        ]
        if self.protocol_var.get() == "Responses API":
            command.append("--openai-use-responses")
        if self.output_mode_var.get() == "dual":
            command.append("--no-mono")
        elif self.output_mode_var.get() == "mono":
            command.append("--no-dual")
        if output_dir is not None:
            command.extend(["--output", str(output_dir)])
        if self.ignore_cache_var.get():
            command.append("--ignore-cache")
        if self.no_auto_glossary_var.get():
            command.append("--no-auto-extract-glossary")
        if self.no_temperature_var.get():
            command.append("--no-send-temperature")
        return command

    def _run_subprocess(self, command: list[str]) -> None:
        env = os.environ.copy()
        app_home = APP_DATA_DIR / "home"
        app_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(app_home)
        env["USERPROFILE"] = str(app_home)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["BABELDOC_OPENAI_API_KEY"] = self.api_key_var.get().strip()
        git_config = APP_DATA_DIR / "gitconfig"
        git_config.write_text(
            f"[safe]\n\tdirectory = {PROJECT_ROOT.as_posix()}\n",
            encoding="utf-8",
        )
        env["GIT_CONFIG_GLOBAL"] = str(git_config)

        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output_queue.put(("log", line))
            return_code = self.process.wait()
            self.output_queue.put(("done", return_code))
        except Exception as exc:
            self.output_queue.put(("error", str(exc)))
        finally:
            self.process = None

    def _stop_translation(self) -> None:
        if self.process is None:
            return
        self._append_log("\nStopping translation...\n")
        self.process.terminate()

    def _pump_output(self) -> None:
        try:
            while True:
                item = self.output_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "done":
                    self._handle_done(int(item[1]))
                elif kind == "error":
                    self._append_log(f"\nError: {item[1]}\n")
                    self._set_running(False)
        except queue.Empty:
            pass
        self.after(120, self._pump_output)

    def _handle_done(self, return_code: int) -> None:
        if return_code == 0:
            self.status_var.set("Finished")
            self._set_running(False)
            self._append_log("\n=== BabelDOC translation finished ===\n")
            for path in self._recent_outputs():
                self._append_log(f"Output: {path}\n")
            self.open_button.configure(state=tk.NORMAL)
        else:
            self.status_var.set(f"Failed with exit code {return_code}")
            self._set_running(False)
            self._append_log(f"\n=== BabelDOC exited with code {return_code} ===\n")

    def _recent_outputs(self) -> list[Path]:
        if self.last_output_dir is None or not self.last_output_dir.exists():
            return []
        threshold = self.run_started_at - 5
        return sorted(
            [
                path
                for path in self.last_output_dir.glob("*.pdf")
                if path.stat().st_mtime >= threshold
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.save_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        if running:
            self.status_var.set("Running...")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_output_folder(self) -> None:
        path = self.last_output_dir
        if path is None:
            pdf_path = Path(self.pdf_var.get().strip().strip('"'))
            path = pdf_path.parent if pdf_path.exists() else None
        if path and path.exists():
            os.startfile(path)

    def _on_close(self) -> None:
        if self.process is not None:
            if not messagebox.askyesno(
                "Translation is running",
                "A translation is still running. Stop it and exit?",
            ):
                return
            self._stop_translation()
        self.destroy()


def main() -> None:
    app = BabelDocUi()
    app.mainloop()


if __name__ == "__main__":
    main()
