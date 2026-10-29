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
FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

THEMES = {
    "dark": {"background": "#0d1722", "surface": "#172635", "field": "#101e2c",
             "foreground": "#e1ebee", "muted": "#91a8b4", "accent": "#67d2ce",
             "accent_hover": "#8ae5df", "border": "#2b4150", "hover": "#294355",
             "disabled": "#5f7480", "selection": "#327a83", "error": "#f49b8d"},
    "light": {"background": "#edf3f5", "surface": "#ffffff", "field": "#f5f9fa",
              "foreground": "#192d38", "muted": "#5b727c", "accent": "#087f86",
              "accent_hover": "#0b989e", "border": "#c6d8dd", "hover": "#e0eef0",
              "disabled": "#8b9ba2", "selection": "#aedfe0", "error": "#ad3828"},
}


class RoundedButton(tk.Canvas):
    """A focusable, keyboard-operable rounded action button."""

    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None], *, width: int,
                 kind: str = "secondary", on_card: bool = False) -> None:
        super().__init__(parent, width=width, height=32, highlightthickness=0,
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
        self._round_rect(0, 10, border)
        self._round_rect(1, 9, fill)
        self.create_text(int(self.cget("width")) // 2, int(self.cget("height")) // 2,
                         text=self.label, fill=foreground, font=(FONT_FAMILY, 9, "bold"))


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


def find_cases(source: Path, folder_mode: bool, include_subfolders: bool = True) -> list[Path]:
    if folder_mode:
        if not source.is_dir():
            raise ValueError(f"Folder does not exist: {source}")
        paths = source.rglob("*") if include_subfolders else source.iterdir()
        cases = sorted(path for path in paths if path.is_file() and path.suffix.lower() == ".smv")
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
        root.minsize(700, 620)
        root.geometry("800x720")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancelled = threading.Event()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.folder_mode = tk.BooleanVar(value=False)
        self.include_subfolders = tk.BooleanVar(value=True)
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
        self.running = False
        self.status_kind = "muted"
        self.theme_name = "dark"
        self.buttons: list[RoundedButton] = []
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._apply_theme()
        self._build()
        self._update_mode()
        for value in (self.folder_mode, self.include_subfolders, self.source,
                      self.output_root, self.times, self.limit_planes, self.plane_value,
                      *self.quantities.values()):
            value.trace_add("write", self._update_ready)
        self._update_ready()
        root.after(100, self._drain_events)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 12))
        if LOGO_FILE.is_file():
            self.window_icon = tk.PhotoImage(file=str(LOGO_FILE))
            self.root.iconphoto(True, self.window_icon)
            self.header_logo = self.window_icon.subsample(6)
            ttk.Label(header, image=self.header_logo).pack(side="left", padx=(0, 10))
        title = ttk.Frame(header)
        title.pack(side="left", fill="x", expand=True)
        ttk.Label(title, text="Capture result slices", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(title, text="ASHTON SMOKEVIEW", style="Muted.TLabel").pack(anchor="w")
        self.theme_button = self._button(header, "Light mode", self._toggle_theme, width=88)
        self.theme_button.pack(side="right")

        panes = ttk.PanedWindow(frame, orient="vertical")
        panes.pack(fill="both", expand=True)
        form = ttk.Frame(panes)
        panes.add(form, weight=0)

        source_group = ttk.LabelFrame(form, text="Input", padding=10, style="Section.TLabelframe")
        source_group.pack(fill="x")
        mode_row = ttk.Frame(source_group, style="Section.TFrame")
        mode_row.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(mode_row, text="Single .smv file", variable=self.folder_mode, value=False,
                        command=self._update_mode, style="Section.TRadiobutton").pack(side="left")
        ttk.Radiobutton(mode_row, text="Folder", variable=self.folder_mode, value=True,
                        command=self._update_mode, style="Section.TRadiobutton").pack(side="left", padx=(18, 0))
        self.subfolder_box = ttk.Checkbutton(source_group, text="Include subfolders",
                                             variable=self.include_subfolders,
                                             style="Section.TCheckbutton")
        self.subfolder_box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.subfolder_box.grid_remove()
        ttk.Label(source_group, text="Input file or folder", style="Section.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Entry(source_group, textvariable=self.source, style="Card.TEntry").grid(
            row=3, column=0, sticky="ew", ipady=3)
        self._button(source_group, "Browse…", self._browse_source, width=82, on_card=True).grid(
            row=3, column=1, padx=(8, 0))
        source_group.columnconfigure(0, weight=1)

        output_group = ttk.LabelFrame(form, text="Output", padding=10, style="Section.TLabelframe")
        output_group.pack(fill="x", pady=(10, 0))
        ttk.Label(output_group, text="Output folder (optional)", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Entry(output_group, textvariable=self.output_root, style="Card.TEntry").grid(
            row=1, column=0, sticky="ew", ipady=3)
        self._button(output_group, "Browse…", self._browse_output, width=82, on_card=True).grid(
            row=1, column=1, padx=(8, 0))
        ttk.Label(output_group, text="Leave blank to save beside each .smv file.",
                  style="SectionMuted.TLabel").grid(row=2, column=0, columnspan=2,
                                                     sticky="w", pady=(4, 0))
        output_group.columnconfigure(0, weight=1)

        options = ttk.LabelFrame(form, text="Capture settings", padding=10, style="Section.TLabelframe")
        options.pack(fill="x", pady=(10, 0))
        ttk.Label(options, text="Slice types", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        slice_row = ttk.Frame(options, style="Section.TFrame")
        slice_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        for index, name in enumerate(QUANTITIES):
            ttk.Checkbutton(slice_row, text=name.title(), variable=self.quantities[name],
                            style="Section.TCheckbutton").pack(side="left", padx=(0 if index == 0 else 18, 0))
        ttk.Label(options, text="Capture times (seconds)", style="Section.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 4))
        ttk.Entry(options, textvariable=self.times, style="Card.TEntry").grid(
            row=3, column=0, sticky="ew", ipady=3)
        ttk.Label(options, text="e.g. 60, 120, 180", style="SectionMuted.TLabel").grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        option_row = ttk.Frame(options, style="Section.TFrame")
        option_row.grid(row=5, column=0, sticky="w", pady=(8, 0))
        crop_box = ttk.Checkbutton(option_row, text="Crop images to the model", variable=self.crop,
                                   style="Section.TCheckbutton")
        crop_box.pack(side="left")
        ttk.Checkbutton(option_row, text="Replace existing captures", variable=self.overwrite,
                        style="Section.TCheckbutton").pack(side="left", padx=(18, 0))
        if not crop_tool_available():
            crop_box.state(["disabled"])
            ttk.Label(options, text="ImageMagick unavailable; full-size images will be saved.",
                      style="SectionMuted.TLabel").grid(row=6, column=0, sticky="w")
        options.columnconfigure(0, weight=1)

        self.advanced_open = tk.BooleanVar(value=False)
        advanced = ttk.Frame(form)
        advanced.pack(fill="x", pady=(10, 0))
        self.advanced_button = ttk.Button(advanced, text="▸  Advanced — slice positions",
                                          command=self._toggle_advanced, style="Disclosure.TButton")
        self.advanced_button.pack(anchor="w")
        self.advanced_details = ttk.Frame(advanced, style="Section.TFrame", padding=(10, 6, 10, 8))
        ttk.Checkbutton(self.advanced_details, text="Capture only selected slice positions",
                        variable=self.limit_planes, command=self._toggle_plane_details,
                        style="Section.TCheckbutton").pack(anchor="w")
        self.plane_details = ttk.Frame(self.advanced_details, style="Section.TFrame")
        ttk.Label(self.plane_details, text="Positions in metres · for example Y=3 or Y=3,Y=5",
                  style="SectionMuted.TLabel").pack(anchor="w", pady=(6, 3))
        plane_row = ttk.Frame(self.plane_details, style="Section.TFrame")
        plane_row.pack(fill="x")
        self.plane_entry = ttk.Combobox(plane_row, textvariable=self.plane_value, style="Card.TCombobox")
        self.plane_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.scan_button = self._button(plane_row, "Scan", self._scan_planes, width=72, on_card=True)
        self.scan_button.pack(side="left", padx=(8, 0))
        ttk.Label(self.plane_details, textvariable=self.available_plane_text, style="SectionMuted.TLabel",
                  wraplength=600).pack(anchor="w", pady=(3, 0))

        controls = ttk.Frame(form)
        controls.pack(fill="x", pady=(12, 0))
        self.run_button = self._button(controls, "Capture slices", self._start, width=132, kind="primary")
        self.run_button.pack(side="left")
        self.cancel_button = self._button(controls, "Cancel", self._cancel, width=72)
        self.cancel_button.set_state("disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.status_label = ttk.Label(controls, textvariable=self.status, style="StatusMuted.TLabel")
        self.status_label.pack(side="left", padx=(12, 0))

        log_section = ttk.Frame(panes)
        panes.add(log_section, weight=1)
        ttk.Label(log_section, text="Capture log", style="SectionHeading.TLabel").pack(
            anchor="w", pady=(8, 5))
        log_frame = ttk.Frame(log_section)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=5, wrap="word", state="disabled")
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
        self._update_ready()

    def _toggle_advanced(self) -> None:
        self.advanced_open.set(not self.advanced_open.get())
        if self.advanced_open.get():
            self.advanced_button.configure(text="▾  Advanced — slice positions")
            self.advanced_details.pack(fill="x")
            if self.limit_planes.get():
                self._toggle_plane_details()
        else:
            self.advanced_button.configure(text="▸  Advanced — slice positions")
            self.advanced_details.pack_forget()

    def _update_mode(self) -> None:
        if self.folder_mode.get():
            self.subfolder_box.grid()
        else:
            self.subfolder_box.grid_remove()
        self._update_ready()

    def _set_status(self, message: str, kind: str = "muted") -> None:
        self.status.set(message)
        self.status_kind = kind
        if hasattr(self, "status_label"):
            self.status_label.configure(style=f"Status{kind.title()}.TLabel")

    def _update_ready(self, *_args: object) -> None:
        if self.running or not hasattr(self, "run_button"):
            return
        source_text = self.source.get().strip()
        if not source_text:
            reason = "Choose a .smv file or folder."
        else:
            source = Path(source_text).expanduser()
            if self.folder_mode.get():
                reason = "Choose an existing folder." if not source.is_dir() else ""
            else:
                reason = "Choose an existing .smv file." if not source.is_file() or source.suffix.lower() != ".smv" else ""
        if not reason:
            try:
                parse_times(self.times.get().strip())
            except ValueError as error:
                reason = str(error)
        if not reason and not any(value.get() for value in self.quantities.values()):
            reason = "Select at least one slice type."
        if not reason and self.limit_planes.get():
            try:
                planes = parse_plane_selection(self.plane_value.get())
                if not planes:
                    reason = "Enter a slice position, such as Y=3."
            except ValueError as error:
                reason = str(error)
        if not reason:
            output_text = self.output_root.get().strip()
            if output_text:
                output = Path(output_text).expanduser()
                if output.exists() and not output.is_dir():
                    reason = "Output must be a folder."
        self.run_button.set_state("disabled" if reason else "normal")
        self._set_status(reason or "Ready to capture.", "muted" if reason else "ready")

    def _scan_planes(self) -> None:
        source_text = self.source.get().strip()
        if not source_text:
            self.available_plane_text.set("Choose a .smv file or folder first.")
            return
        self.scan_generation += 1
        generation = self.scan_generation
        folder_mode = self.folder_mode.get()
        include_subfolders = self.include_subfolders.get()
        self.scan_button.set_state("disabled")
        self.available_plane_text.set("Scanning slice positions…")

        def scan() -> None:
            try:
                source = Path(source_text).expanduser().resolve()
                cases = find_cases(source, folder_mode, include_subfolders)
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
        self.style.configure("Section.TFrame", background=colors["surface"])
        self.style.configure("TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9))
        self.style.configure("Heading.TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 16, "bold"))
        self.style.configure("Muted.TLabel", background=colors["background"],
                             foreground=colors["muted"], font=(FONT_FAMILY, 8))
        self.style.configure("Section.TLabel", background=colors["surface"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9))
        self.style.configure("SectionMuted.TLabel", background=colors["surface"],
                             foreground=colors["muted"], font=(FONT_FAMILY, 8))
        self.style.configure("SectionHeading.TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9, "bold"))
        self.style.configure("Section.TLabelframe", background=colors["surface"],
                             bordercolor=colors["border"], relief="solid", borderwidth=1)
        self.style.configure("Section.TLabelframe.Label", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9, "bold"))
        self.style.configure("StatusMuted.TLabel", background=colors["background"],
                             foreground=colors["muted"], font=(FONT_FAMILY, 9))
        self.style.configure("StatusReady.TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9))
        self.style.configure("StatusRunning.TLabel", background=colors["background"],
                             foreground=colors["accent"], font=(FONT_FAMILY, 9))
        self.style.configure("StatusSuccess.TLabel", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9))
        self.style.configure("StatusFailed.TLabel", background=colors["background"],
                             foreground=colors["error"],
                             font=(FONT_FAMILY, 9))
        self.style.configure("Disclosure.TButton", background=colors["background"],
                             foreground=colors["foreground"], font=(FONT_FAMILY, 9, "bold"),
                             borderwidth=0, padding=(0, 3), relief="flat",
                             focuscolor=colors["accent"], focusthickness=2)
        self.style.map("Disclosure.TButton", foreground=[("disabled", colors["disabled"])],
                       background=[("active", colors["background"]),
                                   ("pressed", colors["background"])])
        for widget in ("TCheckbutton", "TRadiobutton"):
            name = f"Section.{widget}"
            self.style.configure(name, background=colors["surface"], foreground=colors["foreground"],
                                 indicatorcolor=colors["field"], indicatormargin=4,
                                 focuscolor=colors["accent"], focusthickness=2,
                                 font=(FONT_FAMILY, 9))
            self.style.map(name,
                           background=[("active", colors["surface"])],
                           foreground=[("disabled", colors["disabled"])],
                           indicatorcolor=[("selected", colors["accent"]),
                                           ("active", colors["hover"])])
        self.style.configure("Card.TEntry", fieldbackground=colors["field"],
                             foreground=colors["foreground"], insertcolor=colors["foreground"],
                             bordercolor=colors["border"], lightcolor=colors["border"],
                             darkcolor=colors["border"], padding=4, font=(FONT_FAMILY, 9))
        self.style.map("Card.TEntry", bordercolor=[("focus", colors["accent"])],
                       lightcolor=[("focus", colors["accent"])])
        self.style.configure("Card.TCombobox", fieldbackground=colors["field"],
                             background=colors["field"], foreground=colors["foreground"],
                             arrowcolor=colors["muted"], bordercolor=colors["border"],
                             lightcolor=colors["border"], darkcolor=colors["border"], padding=4,
                             font=(FONT_FAMILY, 9))
        self.style.map("Card.TCombobox", fieldbackground=[("readonly", colors["field"])],
                       foreground=[("readonly", colors["foreground"])],
                       bordercolor=[("focus", colors["accent"])])
        self.root.option_add("*TCombobox*Listbox.background", colors["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", colors["foreground"])
        self.style.configure("TScrollbar", background=colors["surface"],
                             troughcolor=colors["field"], arrowcolor=colors["muted"],
                             bordercolor=colors["border"], lightcolor=colors["border"],
                             darkcolor=colors["border"])
        for button in self.buttons:
            button.set_theme(colors)
        if hasattr(self, "status_label"):
            self.status_label.configure(style=f"Status{self.status_kind.title()}.TLabel")
        if hasattr(self, "log"):
            self.log.configure(background=colors["field"], foreground=colors["foreground"],
                               insertbackground=colors["foreground"], selectbackground=colors["selection"],
                               relief="flat", highlightthickness=1, highlightbackground=colors["border"],
                               highlightcolor=colors["accent"], padx=7, pady=6,
                               font=(FONT_FAMILY, 9))

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
            cases = find_cases(source, self.folder_mode.get(), self.include_subfolders.get())
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
        self.running = True
        self.run_button.set_state("disabled")
        self.cancel_button.set_state("normal")
        self._set_status(f"Running · {len(cases)} case(s), {len(times)} time(s)", "running")
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
                        self.events.put(("done", ("Cancelled.", "muted")))
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
                self.events.put(("done", ("Cancelled.", "muted")))
            else:
                message = f"Finished: {len(cases) * len(times) - failures} succeeded, {failures} failed."
                self.events.put(("done", (message, "failed" if failures else "success")))
        except Exception as error:
            self.events.put(("log", f"Capture stopped: {error}\n"))
            self.events.put(("done", ("Capture stopped with an error.", "failed")))

    def _cancel(self) -> None:
        self.cancelled.set()
        self._set_status("Cancelling…", "running")
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
                    self._set_status(str(value), "running")
                elif kind == "done":
                    self.running = False
                    self.cancel_button.set_state("disabled")
                    self._update_ready()
                    message, state = value
                    self._set_status(message, state)
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
