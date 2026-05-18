from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import queue
import re
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


try:
    from tkinterdnd2 import DND_FILES
    from tkinterdnd2 import TkinterDnD
except Exception:  # pragma: no cover - optional desktop integration
    DND_FILES = None
    TkinterDnD = None


APP_NAME = "BabelDOC"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ICON_PNG = PROJECT_ROOT / "babeldoc" / "assets" / "ui" / "babeldoc-ui-icon.png"
ICON_ICO = PROJECT_ROOT / "babeldoc" / "assets" / "ui" / "babeldoc-ui-icon.ico"

STAGES = [
    "Parse PDF and Create Intermediate Representation",
    "DetectScannedFile",
    "Parse Page Layout",
    "Parse Paragraphs",
    "Parse Formulas and Styles",
    "Translate Paragraphs",
    "Typesetting",
    "Add Fonts",
    "Generate drawing instructions",
    "Subset font",
    "Save PDF",
]


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
    ok = ctypes.windll.crypt32.CryptProtectData(
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
    ok = ctypes.windll.crypt32.CryptUnprotectData(
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


def parse_dnd_files(data: str) -> list[str]:
    if not data:
        return []
    result = []
    token = []
    in_brace = False
    for char in data.strip():
        if char == "{":
            in_brace = True
            token = []
        elif char == "}":
            in_brace = False
            value = "".join(token).strip()
            if value:
                result.append(value)
            token = []
        elif char.isspace() and not in_brace:
            value = "".join(token).strip()
            if value:
                result.append(value)
            token = []
        else:
            token.append(char)
    value = "".join(token).strip()
    if value:
        result.append(value)
    return result


def unique_paths(paths: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in paths:
        normalized = str(Path(item).resolve()).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(Path(item)))
    return result


@dataclass
class UiSettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    protocol: str = "responses"
    output_mode: str = "dual"
    output_target: str = "default"
    output_dir: str = ""
    files: list[str] | None = None
    qps: int = 1
    ignore_cache: bool = True
    no_auto_extract_glossary: bool = True
    no_send_temperature: bool = True
    api_key_storage: str = "none"
    api_key_blob: str = ""


class BabelDocUi(TkinterDnD.Tk if TkinterDnD else tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BabelDOC UI")
        self.geometry("1120x760")
        self.minsize(980, 660)
        self.configure(bg="#eef3f2")

        self.settings = self._load_settings()
        self.api_key = self._load_api_key()
        self.file_paths: list[str] = unique_paths(self.settings.files or [])
        self.process: subprocess.Popen | None = None
        self.worker: threading.Thread | None = None
        self.output_queue: queue.Queue = queue.Queue()
        self.stop_requested = False
        self.current_index = 0
        self.batch_total = 0
        self.last_output_dir: Path | None = None
        self.run_started_at = 0.0
        self.completed_count = 0
        self.failed_count = 0
        self.batch_output_dirs: list[Path] = []

        self._configure_style()
        self._build_vars()
        self._load_icon()
        self._build_ui()
        self._refresh_file_list()
        self._update_progress(0, "Ready")
        self._pump_output()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eef3f2")
        style.configure("Surface.TFrame", background="#ffffff")
        style.configure("Panel.TLabelframe", background="#ffffff", borderwidth=1)
        style.configure(
            "Panel.TLabelframe.Label",
            background="#ffffff",
            foreground="#203432",
            font=("Segoe UI Semibold", 10),
        )
        style.configure("TLabel", background="#ffffff", foreground="#203432")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#60706d")
        style.configure("Title.TLabel", background="#eef3f2", foreground="#102523")
        style.configure("Accent.TButton", padding=(14, 8))
        style.configure("TButton", padding=(10, 6))
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#dbe6e3",
            background="#0f766e",
            bordercolor="#dbe6e3",
            lightcolor="#0f766e",
            darkcolor="#0f766e",
        )

    def _build_vars(self) -> None:
        self.base_url_var = tk.StringVar(value=self.settings.base_url)
        self.api_key_var = tk.StringVar(value=self.api_key)
        self.model_var = tk.StringVar(value=self.settings.model)
        self.protocol_var = tk.StringVar(
            value="Responses API"
            if self.settings.protocol == "responses"
            else "Chat Completions API"
        )
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
        self.progress_text_var = tk.StringVar(value="Ready")
        self.file_count_var = tk.StringVar(value="0 files")

    def _load_icon(self) -> None:
        self.icon_image = None
        try:
            if ICON_ICO.exists():
                self.iconbitmap(str(ICON_ICO))
            if ICON_PNG.exists():
                self.icon_image = tk.PhotoImage(file=str(ICON_PNG))
                self.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def _build_ui(self) -> None:
        shell = ttk.Frame(self, padding=18)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=0)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        header.columnconfigure(1, weight=1)
        if self.icon_image:
            icon_small = self.icon_image.subsample(8, 8)
            self.header_icon = icon_small
            ttk.Label(header, image=icon_small, background="#eef3f2").grid(
                row=0, column=0, rowspan=2, padx=(0, 12)
            )
        ttk.Label(
            header,
            text="BabelDOC UI",
            style="Title.TLabel",
            font=("Segoe UI Semibold", 22),
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            text="Local PDF translation workspace with encrypted API settings, batch runs, and drag-and-drop input.",
            style="Title.TLabel",
            font=("Segoe UI", 10),
        ).grid(row=1, column=1, sticky="w")
        self._build_actions(header)

        left = ttk.Frame(shell, style="Surface.TFrame", padding=14)
        left.grid(row=1, column=0, sticky="ns", padx=(0, 14))
        left.columnconfigure(0, weight=1)

        self._build_settings(left)

        right = ttk.Frame(shell)
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(0, weight=2)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_file_panel(right)
        self._build_progress_panel(right)
        self._build_log_panel(right)

    def _build_settings(self, parent: ttk.Frame) -> None:
        api = ttk.LabelFrame(parent, text="Connection", style="Panel.TLabelframe", padding=12)
        api.grid(row=0, column=0, sticky="ew")
        api.columnconfigure(1, weight=1)

        ttk.Label(api, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(api, textvariable=self.base_url_var, width=34).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10)
        )
        ttk.Label(api, text="API key").grid(row=2, column=0, sticky="w")
        self.api_key_entry = ttk.Entry(api, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=3, column=0, sticky="ew", pady=(4, 10))
        ttk.Checkbutton(
            api,
            text="Show",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
        ).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(4, 10))

        ttk.Label(api, text="Model").grid(row=4, column=0, sticky="w")
        ttk.Entry(api, textvariable=self.model_var).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(4, 10)
        )
        ttk.Label(api, text="Protocol").grid(row=6, column=0, sticky="w")
        ttk.Combobox(
            api,
            textvariable=self.protocol_var,
            values=("Responses API", "Chat Completions API"),
            state="readonly",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        output = ttk.LabelFrame(parent, text="Output", style="Panel.TLabelframe", padding=12)
        output.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        output.columnconfigure(0, weight=1)
        for text, value in (
            ("Dual only", "dual"),
            ("Mono only", "mono"),
            ("Both", "both"),
        ):
            ttk.Radiobutton(
                output, text=text, variable=self.output_mode_var, value=value
            ).grid(sticky="w", pady=2)
        ttk.Separator(output).grid(sticky="ew", pady=8)
        ttk.Radiobutton(
            output,
            text="Default: same as input PDF",
            variable=self.output_target_var,
            value="default",
            command=self._refresh_output_controls,
        ).grid(sticky="w", pady=2)
        ttk.Radiobutton(
            output,
            text="Custom folder",
            variable=self.output_target_var,
            value="custom",
            command=self._refresh_output_controls,
        ).grid(sticky="w", pady=2)
        self.output_entry = ttk.Entry(output, textvariable=self.output_dir_var)
        self.output_entry.grid(sticky="ew", pady=(8, 6))
        self.output_browse = ttk.Button(
            output, text="Choose folder", command=self._choose_output_dir
        )
        self.output_browse.grid(sticky="ew")

        options = ttk.LabelFrame(parent, text="Run options", style="Panel.TLabelframe", padding=12)
        options.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(options, text="QPS").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(options, from_=1, to=20, textvariable=self.qps_var, width=8).grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Checkbutton(
            options,
            text="Ignore translation cache",
            variable=self.ignore_cache_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(
            options,
            text="Disable auto glossary",
            variable=self.no_auto_glossary_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            options,
            text="Do not send temperature",
            variable=self.no_temperature_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._refresh_output_controls()

    def _build_actions(self, parent: ttk.Frame) -> None:
        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        actions.columnconfigure(1, weight=1)
        self.save_button = ttk.Button(actions, text="Save settings", command=self._save)
        self.save_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.start_button = ttk.Button(
            actions,
            text="Start batch",
            style="Accent.TButton",
            command=self._start_translation,
        )
        self.start_button.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.stop_button = ttk.Button(
            actions, text="Stop", command=self._stop_translation, state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.open_button = ttk.Button(
            actions,
            text="Open output folder",
            command=self._open_output_folder,
            state=tk.DISABLED,
        )
        self.open_button.grid(row=0, column=3, sticky="e")

    def _build_file_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Input PDFs", style="Panel.TLabelframe", padding=12)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(panel, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="Add PDFs", command=self._choose_pdfs).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Remove selected", command=self._remove_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(toolbar, text="Clear", command=self._clear_files).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(toolbar, textvariable=self.file_count_var, style="Muted.TLabel").pack(
            side=tk.RIGHT
        )

        columns = ("name", "folder", "status")
        self.file_tree = ttk.Treeview(
            panel, columns=columns, show="headings", selectmode="extended", height=10
        )
        self.file_tree.heading("name", text="File")
        self.file_tree.heading("folder", text="Folder")
        self.file_tree.heading("status", text="Status")
        self.file_tree.column("name", width=360, anchor="w")
        self.file_tree.column("folder", width=360, anchor="w")
        self.file_tree.column("status", width=110, anchor="w")
        self.file_tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=self.file_tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=yscroll.set)

        self.drop_label = tk.Label(
            panel,
            text="Drop PDF files here",
            bg="#e7f3f0",
            fg="#0f4f4a",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.drop_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        if DND_FILES:
            for widget in (self, panel, self.file_tree, self.drop_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._handle_drop)
        else:
            self.drop_label.configure(text="Drag-and-drop needs tkinterdnd2; use Add PDFs.")

    def _build_progress_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Surface.TFrame", padding=12)
        panel.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, textvariable=self.status_var, font=("Segoe UI Semibold", 10)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(panel, textvariable=self.progress_text_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e"
        )
        self.progress = ttk.Progressbar(
            panel, mode="determinate", maximum=100, style="Horizontal.TProgressbar"
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Run log", style="Panel.TLabelframe", padding=8)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            panel,
            wrap=tk.WORD,
            height=10,
            state=tk.DISABLED,
            bg="#fbfdfc",
            fg="#203432",
            insertbackground="#203432",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _choose_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select PDF files",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*.*")),
        )
        self._add_files(list(paths))

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_dir_var.set(path)
            self.output_target_var.set("custom")
            self._refresh_output_controls()

    def _handle_drop(self, event) -> None:
        self._add_files(parse_dnd_files(event.data))

    def _add_files(self, paths: list[str]) -> None:
        pdfs = []
        for path_text in paths:
            path = Path(path_text.strip().strip('"'))
            if path.is_dir():
                pdfs.extend(str(p) for p in sorted(path.glob("*.pdf")))
            elif path.exists() and path.suffix.lower() == ".pdf":
                pdfs.append(str(path))
        self.file_paths = unique_paths([*self.file_paths, *pdfs])
        self._refresh_file_list()

    def _remove_selected(self) -> None:
        selected = set(self.file_tree.selection())
        self.file_paths = [
            path for index, path in enumerate(self.file_paths) if str(index) not in selected
        ]
        self._refresh_file_list()

    def _clear_files(self) -> None:
        self.file_paths = []
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.file_tree.delete(*self.file_tree.get_children())
        for index, path_text in enumerate(self.file_paths):
            path = Path(path_text)
            status = "Queued" if path.exists() else "Missing"
            self.file_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(path.name, str(path.parent), status),
            )
        count = len(self.file_paths)
        self.file_count_var.set(f"{count} file{'s' if count != 1 else ''}")

    def _set_file_status(self, index: int, status: str) -> None:
        item = str(index)
        if self.file_tree.exists(item):
            values = list(self.file_tree.item(item, "values"))
            values[2] = status
            self.file_tree.item(item, values=values)
            self.file_tree.see(item)

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
            files=self.file_paths,
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

    def _validate(self) -> tuple[list[Path], Path | None]:
        pdfs = [Path(path) for path in self.file_paths]
        missing = [path for path in pdfs if not path.exists() or path.suffix.lower() != ".pdf"]
        if missing:
            raise ValueError(f"Missing or invalid PDF: {missing[0]}")
        if not pdfs:
            raise ValueError("Please add at least one PDF file.")
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
        return pdfs, output_dir

    def _start_translation(self) -> None:
        if self.process is not None:
            return
        try:
            pdfs, output_dir = self._validate()
            self._save()
            self.stop_requested = False
            self.current_index = 0
            self.batch_total = len(pdfs)
            self.completed_count = 0
            self.failed_count = 0
            self.run_started_at = time.time()
            self.last_output_dir = output_dir or pdfs[0].parent
            self.batch_output_dirs = self._batch_output_dirs(pdfs, output_dir)
            self._set_running(True)
            self._append_log("\n=== BabelDOC batch started ===\n")
            self._append_log(
                "API key is passed through the child process environment, not the command line.\n"
            )
            self.worker = threading.Thread(
                target=self._run_batch, args=(pdfs, output_dir), daemon=True
            )
            self.worker.start()
        except Exception as exc:
            messagebox.showerror("Cannot start", str(exc))

    def _batch_output_dirs(self, pdfs: list[Path], output_dir: Path | None) -> list[Path]:
        dirs = [output_dir] if output_dir is not None else [path.parent for path in pdfs]
        unique_dirs = []
        seen = set()
        for directory in dirs:
            resolved = directory.resolve()
            key = str(resolved).lower()
            if key not in seen:
                seen.add(key)
                unique_dirs.append(resolved)
        return unique_dirs

    def _build_command(self, pdf_path: Path, output_dir: Path | None) -> list[str]:
        effective_output_dir = output_dir or pdf_path.parent
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
            "--output",
            str(effective_output_dir),
        ]
        if self.protocol_var.get() == "Responses API":
            command.append("--openai-use-responses")
        if self.output_mode_var.get() == "dual":
            command.append("--no-mono")
        elif self.output_mode_var.get() == "mono":
            command.append("--no-dual")
        if self.ignore_cache_var.get():
            command.append("--ignore-cache")
        if self.no_auto_glossary_var.get():
            command.append("--no-auto-extract-glossary")
        if self.no_temperature_var.get():
            command.append("--no-send-temperature")
        return command

    def _run_batch(self, pdfs: list[Path], output_dir: Path | None) -> None:
        for index, pdf_path in enumerate(pdfs):
            if self.stop_requested:
                self.output_queue.put(("batch_stopped", None))
                return
            effective_output_dir = output_dir or pdf_path.parent
            self.output_queue.put(
                ("file_start", index, str(pdf_path), str(effective_output_dir))
            )
            return_code = self._run_one(self._build_command(pdf_path, output_dir), index)
            self.output_queue.put(("file_done", index, return_code))
            if return_code != 0:
                self.failed_count += 1
            else:
                self.completed_count += 1
        self.output_queue.put(("batch_done", None))

    def _run_one(self, command: list[str], file_index: int) -> int:
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
                self._queue_progress_from_line(line, file_index)
            return self.process.wait()
        except Exception as exc:
            self.output_queue.put(("error", str(exc)))
            return 1
        finally:
            self.process = None

    def _queue_progress_from_line(self, line: str, file_index: int) -> None:
        for stage_index, stage in enumerate(STAGES):
            if stage in line:
                base = self._file_base_progress(file_index)
                stage_width = 100 / max(1, self.batch_total) / len(STAGES)
                percent = min(99.0, base + stage_index * stage_width)
                self.output_queue.put(("progress", percent, stage))
                return
        if "Translation completed" in line:
            self.output_queue.put(
                (
                    "progress",
                    self._file_base_progress(file_index) + 80 / max(1, self.batch_total),
                    "Translation completed",
                )
            )
        elif "finish translate" in line:
            self.output_queue.put(
                (
                    "progress",
                    self._file_base_progress(file_index) + 98 / max(1, self.batch_total),
                    "Saving output",
                )
            )

    def _file_base_progress(self, file_index: int | None = None) -> float:
        if self.batch_total <= 0:
            return 0
        if file_index is None:
            file_index = self.current_index
        return (file_index / self.batch_total) * 100

    def _stop_translation(self) -> None:
        self.stop_requested = True
        if self.process is not None:
            self._append_log("\nStopping translation...\n")
            self.process.terminate()

    def _pump_output(self) -> None:
        try:
            while True:
                item = self.output_queue.get_nowait()
                self._handle_queue_item(item)
        except queue.Empty:
            pass
        self.after(120, self._pump_output)

    def _handle_queue_item(self, item: tuple) -> None:
        kind = item[0]
        if kind == "log":
            self._append_log(item[1])
        elif kind == "progress":
            self._update_progress(float(item[1]), str(item[2]))
        elif kind == "file_start":
            self.current_index = int(item[1])
            path = Path(item[2])
            self.last_output_dir = Path(item[3]) if len(item) > 3 else path.parent
            self._set_file_status(self.current_index, "Running")
            self._update_progress(self._file_base_progress(), f"Running {path.name}")
            self._append_log(f"\n--- [{self.current_index + 1}/{self.batch_total}] {path} ---\n")
        elif kind == "file_done":
            index = int(item[1])
            return_code = int(item[2])
            if return_code == 0:
                self._set_file_status(index, "Done")
            else:
                self._set_file_status(index, f"Failed ({return_code})")
            percent = ((index + 1) / max(1, self.batch_total)) * 100
            self._update_progress(percent, "File finished")
        elif kind == "batch_done":
            self.status_var.set(
                f"Finished: {self.completed_count} done, {self.failed_count} failed"
            )
            self._set_running(False)
            self.open_button.configure(state=tk.NORMAL)
            self._append_log("\n=== BabelDOC batch finished ===\n")
            for path in self._recent_outputs():
                self._append_log(f"Output: {path}\n")
        elif kind == "batch_stopped":
            self.status_var.set("Stopped")
            self._set_running(False)
            self._append_log("\n=== BabelDOC batch stopped ===\n")
        elif kind == "error":
            self._append_log(f"\nError: {item[1]}\n")

    def _recent_outputs(self) -> list[Path]:
        directories = self.batch_output_dirs or (
            [self.last_output_dir] if self.last_output_dir is not None else []
        )
        directories = [directory for directory in directories if directory.exists()]
        if not directories:
            return []
        threshold = self.run_started_at - 5
        return sorted(
            [
                path
                for directory in directories
                for path in directory.glob("*.pdf")
                if path.stat().st_mtime >= threshold
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _set_running(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.start_button.configure(state=state)
        self.save_button.configure(state=state)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        if running:
            self.status_var.set("Running...")
            self.open_button.configure(state=tk.DISABLED)

    def _update_progress(self, percent: float, text: str) -> None:
        percent = max(0.0, min(100.0, percent))
        self.progress.configure(value=percent)
        self.progress_text_var.set(f"{percent:.0f}%")
        if text:
            self.status_var.set(text)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, self._clean_log_text(text))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clean_log_text(self, text: str) -> str:
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)

    def _open_output_folder(self) -> None:
        path = self.last_output_dir
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
