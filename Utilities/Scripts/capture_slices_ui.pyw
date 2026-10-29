#!/usr/bin/env python3
"""Small desktop front end for Ashton Smokeview result captures."""

from __future__ import annotations

import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
from typing import Callable
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    message = "Tkinter is required for the capture window. Install Python with Tk support."
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Ashton Smokeview", 0x10)
    else:
        print(message, file=sys.stderr)
    raise SystemExit(2)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from smv_planes import available_planes, parse_plane_selection


QUANTITIES = ("visibility", "temperature", "velocity", "pressure")
CAPTURE_SCRIPT = Path(__file__).resolve().with_name("capture_result_slices.py")
LOGO_FILE = Path(sys.executable).resolve().parent / "capture_logo.png" if getattr(sys, "frozen", False) else Path(__file__).resolve().with_name("capture_logo.png")

THEMES = {
    "dark": {"background": "#0d1722", "surface": "#172635", "field": "#101e2c",
             "foreground": "#e1ebee", "muted": "#91a8b4", "accent": "#67d2ce",
             "accent_hover": "#8ae5df", "border": "#2b4150", "hover": "#294355",
             "disabled": "#5f7480", "selection": "#327a83"},
    "light": {"background": "#edf3f5", "surface": "#ffffff", "field": "#f5f9fa",
              "foreground": "#192d38", "muted": "#5b727c", "accent": "#087f86",
              "accent_hover": "#0b989e", "border": "#c6d8dd", "hover": "#e0eef0",
              "disabled": "#8b9ba2", "selection": "#aedfe0"},
}


class RoundedButton(tk.Canvas):
    """A focusable, keyboard-operable rounded action button."""

    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None], *, width: int,
                 kind: str = "secondary", on_card: bool = False) -> None:
        super().__init__(parent, width=width, height=38, highlightthickness=0,
                         borderwidth=0, takefocus=1, cursor="hand2")
        self.label = text
        self.command = command
        self.kind = kind
        self.on_card = on_card
        self.enabled = True
        self.hovered = False
        self.focused = False
        self.colors = THEMES["dark"]
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)

    def set_theme(self, colors: dict[str, str]) -> None:
        self.colors = colors
        self.configure(background=colors["surface" if self.on_card else "background"])
        self._draw()

    def set_state(self, state: str) -> None:
        self.enabled = state != "disabled"
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self._draw()

    def set_text(self, text: str) -> None:
        self.label = text
        self._draw()

    def _click(self, _event: object) -> None:
        if self.enabled:
            self.focus_set()
            self.command()

    def _enter(self, _event: object) -> None:
        self.hovered = True
        self._draw()

    def _leave(self, _event: object) -> None:
        self.hovered = False
        self._draw()

    def _focus_in(self, _event: object) -> None:
        self.focused = True
        self._draw()

    def _focus_out(self, _event: object) -> None:
        self.focused = False
        self._draw()

    def _round_rect(self, inset: int, radius: int, color: str) -> None:
        width = int(self.cget("width"))
        height = int(self.cget("height"))
        x1, y1, x2, y2 = inset, inset, width - inset, height - inset
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=color, outline=color)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=color, outline=color)
        for left, top in ((x1, y1), (x2 - 2 * radius, y1),
                          (x1, y2 - 2 * radius), (x2 - 2 * radius, y2 - 2 * radius)):
            self.create_oval(left, top, left + 2 * radius, top + 2 * radius,
                            fill=color, outline=color)

    def _draw(self) -> None:
        colors = self.colors
        self.delete("all")
        if self.kind == "primary":
            fill = colors["accent_hover"] if self.hovered and self.enabled else colors["accent"]
            foreground = colors["background"]
        else:
            fill = colors["hover"] if self.hovered and self.enabled else colors["field"]
            foreground = colors["foreground"]
        if not self.enabled:
            foreground = colors["disabled"]
            fill = colors["field"]
        border = colors["accent"] if self.focused and self.enabled else colors["border"]
        self._round_rect(0, 12, border)
        self._round_rect(1, 11, fill)
        self.create_text(int(self.cget("width")) // 2, int(self.cget("height")) // 2,
                         text=self.label, fill=foreground, font=("Segoe UI", 10, "bold"))


def parse_times(text: str) -> list[float]:
    values: list[float] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Enter one or more times in seconds, separated by commas.")
        try:
            value = float(part)
        except ValueError as error:
            raise ValueError(f"Invalid time: {part}") from error
        if not math.isfinite(value):
            raise ValueError("Times must be finite numbers.")
        if value not in values:
            values.append(value)
    return values


def find_cases(source: Path, folder_mode: bool) -> list[Path]:
    if folder_mode:
        if not source.is_dir():
            raise ValueError(f"Folder does not exist: {source}")
        cases = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() == ".smv")
        if not cases:
            raise ValueError(f"No .smv files found under {source}")
        return cases
    if not source.is_file() or source.suffix.lower() != ".smv":
        raise ValueError(f"Select an existing .smv file: {source}")
    return [source]


def time_folder(value: float) -> str:
    label = repr(float(value)).replace("-", "m").replace(".", "p")
    return f"t_{label}s"


def output_for_case(case: Path, source: Path, folder_mode: bool, chosen_root: Path | None, time: float, multiple_times: bool) -> Path:
    if chosen_root is None:
        output = case.with_name(f"{case.stem}_slice_captures")
    else:
        relative_parent = case.parent.relative_to(source) if folder_mode else Path()
        output = chosen_root / relative_parent / f"{case.stem}_slice_captures"
    return output / time_folder(time) if multiple_times else output


def crop_tool_available() -> bool:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "imagemagick" / "magick.exe"
        if bundled.is_file():
            return True
    return bool(shutil.which("magick") or (sys.platform != "win32" and shutil.which("convert")))


class CaptureWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Ashton Smokeview — Capture result slices")
        root.minsize(760, 620)
        root.geometry("850x710")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancelled = threading.Event()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.folder_mode = tk.BooleanVar(value=False)
        self.source = tk.StringVar()
        if len(sys.argv) > 1:
            selected = Path(sys.argv[1]).expanduser()
            self.source.set(str(selected))
            self.folder_mode.set(selected.is_dir())
        self.output_root = tk.StringVar()
        self.times = tk.StringVar(value="150")
        self.quantities = {name: tk.BooleanVar(value=True) for name in QUANTITIES}
        self.crop = tk.BooleanVar(value=crop_tool_available())
        self.overwrite = tk.BooleanVar(value=True)
        self.limit_planes = tk.BooleanVar(value=False)
        self.plane_value = tk.StringVar()
        self.available_plane_text = tk.StringVar(value="Scan a case to see its slice positions.")
        self.scan_generation = 0
        self.status = tk.StringVar(value="Choose a case or folder to begin.")
        self.theme_name = "dark"
        self.buttons: list[RoundedButton] = []
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._apply_theme()
        self._build()
        root.after(100, self._drain_events)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 18))
        if LOGO_FILE.is_file():
            self.window_icon = tk.PhotoImage(file=str(LOGO_FILE))
            self.root.iconphoto(True, self.window_icon)
            self.header_logo = self.window_icon.subsample(4)
            ttk.Label(header, image=self.header_logo).pack(side="left", padx=(0, 12))
        title = ttk.Frame(header)
        title.pack(side="left", fill="x", expand=True)
        ttk.Label(title, text="Capture result slices", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(title, text="ASHTON SMOKEVIEW", style="Muted.TLabel").pack(anchor="w")
        self.theme_button = self._button(header, "Light mode", self._toggle_theme, width=112)
        self.theme_button.pack(side="right")
        source_group = ttk.LabelFrame(frame, text="Input", padding=14, style="Card.TLabelframe")
        source_group.pack(fill="x")
        ttk.Radiobutton(source_group, text="One .smv file", variable=self.folder_mode, value=False,
                        style="Card.TRadiobutton").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(source_group, text="All .smv files in a folder (including subfolders)",
                        variable=self.folder_mode, value=True, style="Card.TRadiobutton").grid(
                            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Entry(source_group, textvariable=self.source, style="Card.TEntry").grid(
            row=2, column=0, sticky="ew", pady=(10, 0), ipady=5)
        self._button(source_group, "Browse…", self._browse_source, width=104, on_card=True).grid(
            row=2, column=1, padx=(10, 0), pady=(10, 0))
        source_group.columnconfigure(0, weight=1)

        output_group = ttk.LabelFrame(frame, text="Output", padding=14, style="Card.TLabelframe")
        output_group.pack(fill="x", pady=(14, 0))
        ttk.Label(output_group, text="Leave blank to save beside each .smv file.",
                  style="CardMuted.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(output_group, textvariable=self.output_root, style="Card.TEntry").grid(
            row=1, column=0, sticky="ew", pady=(8, 0), ipady=5)
        self._button(output_group, "Choose folder…", self._browse_output, width=140, on_card=True).grid(
            row=1, column=1, padx=(10, 0), pady=(8, 0))
        output_group.columnconfigure(0, weight=1)

        options = ttk.LabelFrame(frame, text="Capture options", padding=14, style="Card.TLabelframe")
        options.pack(fill="x", pady=(14, 0))
        ttk.Label(options, text="Slice types", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        for index, name in enumerate(QUANTITIES):
            ttk.Checkbutton(options, text=name.title(), variable=self.quantities[name],
                            style="Card.TCheckbutton").grid(row=0, column=index + 1, padx=(10, 0), sticky="w")
        ttk.Label(options, text="Time(s), seconds", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(options, textvariable=self.times, width=35, style="Card.TEntry").grid(
            row=1, column=1, columnspan=4, sticky="ew", pady=(12, 0), ipady=5)
        ttk.Label(options, text="Multiple times: 60, 120, 180", style="CardMuted.TLabel").grid(
            row=2, column=1, columnspan=4, sticky="w", pady=(3, 0))
        crop_box = ttk.Checkbutton(options, text="Crop images to the model", variable=self.crop,
                                   style="Card.TCheckbutton")
        crop_box.grid(row=3, column=0, columnspan=5, sticky="w", pady=(10, 0))
        if not crop_tool_available():
            crop_box.state(["disabled"])
            ttk.Label(options, text="ImageMagick unavailable; full-size images will be saved.",
                      style="CardMuted.TLabel").grid(row=4, column=0, columnspan=5, sticky="w")
        ttk.Checkbutton(options, text="Replace existing captures", variable=self.overwrite,
                        style="Card.TCheckbutton").grid(row=5, column=0, columnspan=5, sticky="w", pady=(5, 0))

        advanced = ttk.LabelFrame(frame, text="Advanced · slice positions", padding=14, style="Card.TLabelframe")
        advanced.pack(fill="x", pady=(14, 0))
        ttk.Checkbutton(advanced, text="Capture only selected slice positions", variable=self.limit_planes,
                        command=self._toggle_plane_details, style="Card.TCheckbutton").pack(anchor="w")
        self.plane_details = ttk.Frame(advanced, style="Card.TFrame")
        ttk.Label(self.plane_details, text="Positions in metres · for example Y=3 or Y=3,Y=5",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(8, 4))
        plane_row = ttk.Frame(self.plane_details, style="Card.TFrame")
        plane_row.pack(fill="x")
        self.plane_entry = ttk.Combobox(plane_row, textvariable=self.plane_value, style="Card.TCombobox")
        self.plane_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.scan_button = self._button(plane_row, "Scan input", self._scan_planes, width=116, on_card=True)
        self.scan_button.pack(side="left", padx=(10, 0))
        ttk.Label(self.plane_details, textvariable=self.available_plane_text, style="CardMuted.TLabel",
                  wraplength=600).pack(anchor="w", pady=(5, 0))

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(16, 0))
        self.run_button = self._button(controls, "Capture slices", self._start, width=170, kind="primary")
        self.run_button.pack(side="left")
        self.cancel_button = self._button(controls, "Cancel", self._cancel, width=92)
        self.cancel_button.set_state("disabled")
        self.cancel_button.pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=12)
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True, pady=(14, 0))
        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        self._apply_theme()
        if self.source.get():
            self.root.after(200, self._scan_planes)

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], None], *, width: int,
                kind: str = "secondary", on_card: bool = False) -> RoundedButton:
        button = RoundedButton(parent, text, command, width=width, kind=kind, on_card=on_card)
        self.buttons.append(button)
        button.set_theme(THEMES[self.theme_name])
        return button

    def _toggle_plane_details(self) -> None:
        if self.limit_planes.get():
            self.plane_details.pack(fill="x")
            self._scan_planes()
        else:
            self.plane_details.pack_forget()

    def _scan_planes(self) -> None:
        source_text = self.source.get().strip()
        if not source_text:
            self.available_plane_text.set("Choose a .smv file or folder first.")
            return
        self.scan_generation += 1
        generation = self.scan_generation
        self.scan_button.set_state("disabled")
        self.available_plane_text.set("Scanning slice positions…")

        def scan() -> None:
            try:
                source = Path(source_text).expanduser().resolve()
                cases = find_cases(source, self.folder_mode.get())
                positions = {position for case in cases for position in available_planes(case)}
                ordered = sorted(positions, key=lambda token: ("xyz".index(token[0].lower()), float(token[2:])))
                self.events.put(("planes", (generation, ordered, len(cases))))
            except (OSError, ValueError) as error:
                self.events.put(("plane_error", (generation, str(error))))

        threading.Thread(target=scan, daemon=True).start()

    def _apply_theme(self) -> None:
        colors = THEMES[self.theme_name]
        self.root.configure(background=colors["background"])
        self.style.configure("TFrame", background=colors["background"])
        self.style.configure("Card.TFrame", background=colors["surface"])
        self.style.configure("TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=("Segoe UI", 10))
        self.style.configure("Heading.TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=("Segoe UI", 19, "bold"))
        self.style.configure("Muted.TLabel", background=colors["background"],
                             foreground=colors["muted"], font=("Segoe UI", 9))
        self.style.configure("Card.TLabel", background=colors["surface"],
                             foreground=colors["foreground"], font=("Segoe UI", 10))
        self.style.configure("CardMuted.TLabel", background=colors["surface"],
                             foreground=colors["muted"], font=("Segoe UI", 9))
        self.style.configure("Card.TLabelframe", background=colors["surface"],
                             foreground=colors["foreground"], bordercolor=colors["surface"], relief="flat")
        self.style.configure("Card.TLabelframe.Label", background=colors["surface"],
                             foreground=colors["accent"], font=("Segoe UI", 10, "bold"))
        for widget in ("TCheckbutton", "TRadiobutton"):
            name = f"Card.{widget}"
            self.style.configure(name, background=colors["surface"], foreground=colors["foreground"],
                                 indicatorcolor=colors["field"], indicatormargin=4,
                                 font=("Segoe UI", 10))
            self.style.map(name,
                           background=[("active", colors["surface"])],
                           foreground=[("disabled", colors["disabled"])],
                           indicatorcolor=[("selected", colors["selection"]),
                                           ("active", colors["hover"])])
        self.style.configure("Card.TEntry", fieldbackground=colors["field"],
                             foreground=colors["foreground"], insertcolor=colors["foreground"],
                             bordercolor=colors["border"], lightcolor=colors["border"],
                             darkcolor=colors["border"], padding=5, font=("Segoe UI", 10))
        self.style.configure("Card.TCombobox", fieldbackground=colors["field"],
                             background=colors["field"], foreground=colors["foreground"],
                             arrowcolor=colors["muted"], bordercolor=colors["border"],
                             lightcolor=colors["border"], darkcolor=colors["border"], padding=5,
                             font=("Segoe UI", 10))
        self.style.map("Card.TCombobox", fieldbackground=[("readonly", colors["field"])],
                       foreground=[("readonly", colors["foreground"])])
        self.root.option_add("*TCombobox*Listbox.background", colors["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", colors["foreground"])
        self.style.configure("TScrollbar", background=colors["surface"],
                             troughcolor=colors["field"], arrowcolor=colors["muted"],
                             bordercolor=colors["border"], lightcolor=colors["border"],
                             darkcolor=colors["border"])
        for button in self.buttons:
            button.set_theme(colors)
        if hasattr(self, "log"):
            self.log.configure(background=colors["field"], foreground=colors["foreground"],
                               insertbackground=colors["foreground"], selectbackground=colors["selection"],
                               relief="flat", highlightthickness=1, highlightbackground=colors["border"],
                               highlightcolor=colors["accent"], padx=10, pady=10,
                               font=("Consolas", 9))

    def _toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self._apply_theme()
        self.theme_button.set_text("Dark mode" if self.theme_name == "light" else "Light mode")

    def _browse_source(self) -> None:
        selected = filedialog.askdirectory() if self.folder_mode.get() else filedialog.askopenfilename(filetypes=[("Smokeview cases", "*.smv"), ("All files", "*.*")])
        if selected:
            self.source.set(selected)
            if self.limit_planes.get():
                self._scan_planes()

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.output_root.set(selected)

    def _write(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self) -> None:
        try:
            source = Path(self.source.get().strip()).expanduser().resolve()
            cases = find_cases(source, self.folder_mode.get())
            times = parse_times(self.times.get().strip())
            quantities = [name for name in QUANTITIES if self.quantities[name].get()]
            if not quantities:
                raise ValueError("Select at least one slice type.")
            planes = parse_plane_selection(self.plane_value.get()) if self.limit_planes.get() else ""
            if self.limit_planes.get() and not planes:
                raise ValueError("Enter at least one slice position, such as Y=3.")
            root_text = self.output_root.get().strip()
            output_root = Path(root_text).expanduser().resolve() if root_text else None
            if output_root is not None and output_root.exists() and not output_root.is_dir():
                raise ValueError(f"Output is not a folder: {output_root}")
            if getattr(sys, "frozen", False):
                worker_exe = Path(sys.executable).resolve().with_name("capture_result_slices.exe")
                if not worker_exe.is_file():
                    raise ValueError(f"Capture engine is missing: {worker_exe}")
            elif not CAPTURE_SCRIPT.is_file():
                raise ValueError(f"Capture engine is missing: {CAPTURE_SCRIPT}")
        except ValueError as error:
            messagebox.showerror("Capture setup", str(error), parent=self.root)
            return
        self.cancelled.clear()
        self.run_button.set_state("disabled")
        self.cancel_button.set_state("normal")
        self._write(f"Starting {len(cases)} case(s) at {len(times)} time(s).\n")
        config = (cases, source, self.folder_mode.get(), output_root, times, quantities, planes,
                  self.crop.get(), self.overwrite.get())
        self.worker = threading.Thread(target=self._run, args=config, daemon=True)
        self.worker.start()

    def _run(self, cases: list[Path], source: Path, folder_mode: bool, output_root: Path | None,
             times: list[float], quantities: list[str], planes: str, crop: bool, overwrite: bool) -> None:
        failures = 0
        try:
            for case_number, case in enumerate(cases, 1):
                for time in times:
                    if self.cancelled.is_set():
                        self.events.put(("done", "Cancelled."))
                        return
                    output = output_for_case(case, source, folder_mode, output_root, time, len(times) > 1)
                    self.events.put(("status", f"Case {case_number}/{len(cases)} · {time:g} s"))
                    self.events.put(("log", f"\n{case} at {time:g} s → {output}\n"))
                    if getattr(sys, "frozen", False):
                        install_dir = Path(sys.executable).resolve().parent
                        command = [str(install_dir / "capture_result_slices.exe"), str(case),
                                   "--smokeview", str(install_dir / "smokeview.exe")]
                    else:
                        command = [sys.executable, "-u", str(CAPTURE_SCRIPT), str(case)]
                    command.extend(["-o", str(output), "--time", repr(time), "--quantities", *quantities])
                    if planes:
                        command.extend(["--planes", planes])
                    if not crop:
                        command.append("--no-crop")
                    if overwrite:
                        command.append("--overwrite")
                    kwargs: dict[str, object] = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                                                  "text": True, "encoding": "utf-8", "errors": "replace"}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    else:
                        kwargs["start_new_session"] = True
                    process = subprocess.Popen(command, **kwargs)
                    self.process = process
                    assert process.stdout is not None
                    for line in process.stdout:
                        self.events.put(("log", line))
                    result = process.wait()
                    self.process = None
                    if result != 0 and not self.cancelled.is_set():
                        failures += 1
                        self.events.put(("log", f"Capture failed (exit code {result}).\n"))
            if self.cancelled.is_set():
                self.events.put(("done", "Cancelled."))
            else:
                self.events.put(("done", f"Finished: {len(cases) * len(times) - failures} succeeded, {failures} failed."))
        except Exception as error:
            self.events.put(("log", f"Capture stopped: {error}\n"))
            self.events.put(("done", "Capture stopped with an error."))

    def _cancel(self) -> None:
        self.cancelled.set()
        self.status.set("Cancelling…")
        process = self.process
        if process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._write(str(value))
                elif kind == "status":
                    self.status.set(str(value))
                elif kind == "done":
                    self.status.set(str(value))
                    self.run_button.set_state("normal")
                    self.cancel_button.set_state("disabled")
                elif kind == "planes":
                    generation, positions, count = value
                    if generation != self.scan_generation:
                        continue
                    self.plane_entry.configure(values=positions)
                    self.available_plane_text.set(
                        f"Available in {count} case(s): {', '.join(positions)}" if positions
                        else "No 2D slice positions found in the selected input."
                    )
                    self.scan_button.set_state("normal")
                elif kind == "plane_error":
                    generation, error = value
                    if generation != self.scan_generation:
                        continue
                    self.available_plane_text.set(f"Could not scan input: {error}")
                    self.scan_button.set_state("normal")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno("Capture running", "Stop capturing and close?", parent=self.root):
                return
            self._cancel()
        self.root.destroy()


def main() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    root = tk.Tk()
    CaptureWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
