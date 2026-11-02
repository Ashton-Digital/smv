#!/usr/bin/env python3
"""PySide6 desktop window for Ashton Smokeview slice captures."""
from __future__ import annotations

import sys
import threading
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPalette, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QToolButton, QListWidget,
    QVBoxLayout, QWidget, QButtonGroup)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from capture_ui_core import (CAPTURE_SCRIPT, QUANTITIES, CaptureJob, CaseCaptureSettings, ClipVariant,
    crop_tool_available, external_process_env, find_cases, parse_times)
from smv_planes import available_planes, parse_plane_selection

LOGO_FILE = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
             else SCRIPT_DIR) / "capture_logo.png"
CHECK_FILE = LOGO_FILE.with_name("capture_check.svg")

THEMES = {
    "dark": dict(bg="#101820", surface="#18242e", input="#111d26", text="#e7eef0",
                 muted="#a4b6bd", border="#354550", hover="#263742", accent="#55c6c2",
                 accent_hover="#72dad5", selected="#256c72", disabled="#71828b",
                 error="#f5a49a", success="#9dd9bc"),
    "light": dict(bg="#f4f7f8", surface="#ffffff", input="#ffffff", text="#172b35",
                  muted="#526873", border="#bdcdd3", hover="#e8f1f2", accent="#087d83",
                  accent_hover="#096b70", selected="#cce9e8", disabled="#82939a",
                  error="#a83229", success="#167456"),
}


class CaptureWorker(QObject):
    log = Signal(str)
    status = Signal(str)
    done = Signal(str, str)

    def __init__(self, job: CaptureJob) -> None:
        super().__init__()
        self.job = job

    @Slot()
    def run(self) -> None:
        message, state = self.job.run(self.log.emit, self.status.emit)
        self.done.emit(message, state)


class SettingsScrollArea(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.scrollbar_timer = QTimer(self)
        self.scrollbar_timer.setSingleShot(True)
        self.scrollbar_timer.timeout.connect(self.sync_scrollbar)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        content_height = self.widget().sizeHint().height() if self.widget() else 0
        return QSize(hint.width(), max(240, content_height + 4))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.scrollbar_timer.start(0)

    def sync_scrollbar(self) -> None:
        content_height = self.widget().sizeHint().height() if self.widget() else 0
        policy = (Qt.ScrollBarAsNeeded if content_height > self.viewport().height()
                  else Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(policy)


class CaptureWindow(QWidget):
    scan_result = Signal(int, list, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ashton Smokeview: Capture result slices")
        if LOGO_FILE.is_file():
            self.setWindowIcon(QIcon(str(LOGO_FILE)))
        self.job: CaptureJob | None = None
        self.thread: QThread | None = None
        self.pending_result: tuple[str, str] | None = None
        self.capture_folders: list[Path] = []
        self.scan_generation = 0
        self.scan_key: tuple[str, bool, bool] | None = None
        self.scan_pending = False
        self.scan_error = ""
        self.case_positions: list[tuple[Path, list[str]]] = []
        self.case_axes: dict[Path, set[str]] = {}
        self.case_drafts: dict[Path, list[tuple[str, str, str]]] = {}
        self.row_widgets: list[tuple[QComboBox, QLineEdit, QComboBox, QPushButton]] = []
        self.rendering_rows = False
        self.loaded_case_data: dict[str, dict] | None = None
        self.load_warning = ""
        self.case_index = 0
        self.theme = "dark"
        self.last_state = "muted"
        self.settings_height_timer = QTimer(self)
        self.settings_height_timer.setSingleShot(True)
        self.settings_height_timer.timeout.connect(self._settle_settings_height)
        self._build()
        self.scan_result.connect(self._scan_finished)
        self._apply_theme()
        if len(sys.argv) > 1:
            selected = Path(sys.argv[1]).expanduser()
            self.source.setText(str(selected))
            self.folder_radio.setChecked(selected.is_dir())
        self._mode_changed()
        self._validate()
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(820, screen.width()), min(780, screen.height()))
        self.setMinimumSize(min(700, screen.width()), min(560, screen.height()))

    def _label(self, text: str, role: str = "label") -> QLabel:
        label = QLabel(text)
        label.setObjectName(role)
        return label

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_settings_height()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(10)
        if LOGO_FILE.is_file():
            logo = QLabel()
            logo.setPixmap(QIcon(str(LOGO_FILE)).pixmap(36, 36))
            logo.setFixedSize(36, 36)
            header.addWidget(logo)
        title = self._label("Capture result slices", "title")
        header.addWidget(title)
        header.addStretch()
        help_button = QPushButton("Help")
        help_button.setObjectName("quietButton")
        help_button.clicked.connect(self._show_help)
        header.addWidget(help_button)
        self.theme_button = QPushButton("Light mode")
        self.theme_button.setObjectName("quietButton")
        self.theme_button.clicked.connect(self._toggle_theme)
        header.addWidget(self.theme_button)
        outer.addLayout(header)

        self.settings_scroll = SettingsScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.settings_scroll.setMinimumHeight(240)
        self.settings_scroll.setMaximumHeight(470)
        form = QWidget()
        self.settings_scroll.setWidget(form)
        fields = QVBoxLayout(form)
        fields.setContentsMargins(0, 0, 5, 0)
        fields.setSpacing(8)

        # Input and output share one aligned label/path/button grid.
        paths = QWidget()
        grid = QGridLayout(paths)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(1, 1)
        modes = QHBoxLayout()
        modes.setSpacing(16)
        self.file_radio = QRadioButton("Single .smv file")
        self.folder_radio = QRadioButton("Folder")
        self.file_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.file_radio)
        group.addButton(self.folder_radio)
        modes.addWidget(self.file_radio)
        modes.addWidget(self.folder_radio)
        modes.addStretch()
        grid.addLayout(modes, 0, 1, 1, 2)
        self.file_radio.toggled.connect(self._mode_changed)
        self.folder_radio.toggled.connect(self._mode_changed)
        self.subfolders = QCheckBox("Include subfolders")
        self.subfolders.setChecked(True)
        grid.addWidget(self.subfolders, 1, 1, 1, 2)
        grid.addWidget(self._label("Input file or folder"), 2, 0)
        self.source = QLineEdit()
        self.source.setAccessibleName("Input file or folder")
        grid.addWidget(self.source, 2, 1)
        browse_source = QPushButton("Browse…")
        browse_source.clicked.connect(self._browse_source)
        grid.addWidget(browse_source, 2, 2)
        grid.addWidget(self._label("Output folder (optional)"), 3, 0)
        self.output = QLineEdit()
        self.output.setAccessibleName("Output folder (optional)")
        grid.addWidget(self.output, 3, 1)
        browse_output = QPushButton("Browse…")
        browse_output.clicked.connect(self._browse_output)
        grid.addWidget(browse_output, 3, 2)
        grid.addWidget(self._label("Leave blank to save beside each .smv file.", "helper"), 4, 1, 1, 2)
        fields.addWidget(paths)

        settings = QWidget()
        setting_layout = QVBoxLayout(settings)
        setting_layout.setContentsMargins(0, 0, 0, 0)
        setting_layout.setSpacing(7)
        setting_layout.addWidget(self._label("Capture settings", "section"))
        slices = QHBoxLayout()
        slices.setSpacing(16)
        slices.addWidget(self._label("Slice types"))
        self.quantities = {}
        for quantity in QUANTITIES:
            box = QCheckBox(quantity.title())
            box.setChecked(True)
            self.quantities[quantity] = box
            slices.addWidget(box)
        slices.addStretch()
        setting_layout.addLayout(slices)
        times_row = QHBoxLayout()
        times_row.setSpacing(8)
        times_row.addWidget(self._label("Capture times (seconds)"))
        self.times = QLineEdit("150")
        self.times.setFixedWidth(160)
        self.times.setAccessibleName("Capture times in seconds")
        times_row.addWidget(self.times)
        times_row.addWidget(self._label("e.g. 60, 120, 180", "helper"))
        times_row.addStretch()
        setting_layout.addLayout(times_row)
        options = QHBoxLayout()
        options.setSpacing(20)
        self.crop = QCheckBox("Crop images to the model")
        self.crop.setChecked(crop_tool_available())
        self.crop.setEnabled(crop_tool_available())
        self.overwrite = QCheckBox("Replace existing captures")
        self.overwrite.setChecked(True)
        options.addWidget(self.crop)
        options.addWidget(self.overwrite)
        options.addStretch()
        setting_layout.addLayout(options)
        if not crop_tool_available():
            setting_layout.addWidget(self._label("ImageMagick unavailable; full-size images will be saved.", "helper"))
        fields.addWidget(settings)

        self.advanced_button = QToolButton()
        self.advanced_button.setText("Advanced slices and clipping")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setArrowType(Qt.RightArrow)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        fields.addWidget(self.advanced_button)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(5)
        case_row = QHBoxLayout()
        self.plane_summary = self._label("Scan input to list available slices.", "helper")
        self.plane_summary.setWordWrap(True)
        case_row.addWidget(self.plane_summary, 1)
        self.add_variant = QPushButton("Add clip view")
        self.add_variant.clicked.connect(lambda _checked=False: self._add_variant_row())
        case_row.addWidget(self.add_variant)
        self.save_job_button = QPushButton("Save job…")
        self.save_job_button.clicked.connect(self._save_job)
        self.load_job_button = QPushButton("Load job…")
        self.load_job_button.clicked.connect(self._load_job)
        case_row.addWidget(self.save_job_button)
        case_row.addWidget(self.load_job_button)
        self.scan_button = QPushButton("Scan input")
        self.scan_button.clicked.connect(self._scan_planes)
        case_row.addWidget(self.scan_button)
        advanced_layout.addLayout(case_row)
        body = QHBoxLayout()
        body.setSpacing(10)
        self.case_list = QListWidget()
        self.case_list.setFixedWidth(170)
        self.case_list.setFixedHeight(112)
        self.case_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.case_list.currentRowChanged.connect(self._show_case)
        body.addWidget(self.case_list, 0, Qt.AlignTop)
        self.apply_all_button = QPushButton("Apply to all cases")
        self.apply_all_button.setToolTip("Copy this case's normal axes and clip views to every scanned case")
        self.apply_all_button.setEnabled(False)
        self.apply_all_button.clicked.connect(self._apply_to_all_cases)
        details = QWidget()
        details.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(5)
        detail_layout.setAlignment(Qt.AlignTop)
        self.case_label = self._label("Scan input to list .smv cases.", "helper")
        axes_row = QHBoxLayout()
        axes_row.setSpacing(14)
        axes_row.addWidget(self._label("Normal slices"))
        self.axis_boxes = {}
        for axis in "xyz":
            box = QCheckBox(axis.upper())
            box.setChecked(True)
            box.toggled.connect(self._axis_changed)
            self.axis_boxes[axis] = box
            axes_row.addWidget(box)
        axes_row.addStretch()
        axes_row.addWidget(self.apply_all_button)
        detail_layout.addLayout(axes_row)
        grid_widget = QWidget()
        grid_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.variants_grid = QGridLayout(grid_widget)
        self.variants_grid.setContentsMargins(0, 0, 0, 0)
        self.variants_grid.setHorizontalSpacing(6)
        self.variants_grid.setVerticalSpacing(6)
        for column, label in enumerate(("Slice", "Clip (m)", "View", "")):
            self.variants_grid.addWidget(self._label(label, "helper"), 0, column)
        self.variants_grid.setColumnStretch(0, 2)
        self.variants_grid.setColumnStretch(1, 1)
        detail_layout.addWidget(grid_widget)
        body.addWidget(details, 1, Qt.AlignTop)
        advanced_layout.addLayout(body)
        fields.addWidget(self.advanced)
        self.advanced.setVisible(False)
        outer.addWidget(self.settings_scroll)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.run_button = QPushButton("Capture slices")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._start)
        actions.addWidget(self.run_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.cancel_button)
        self.open_captures_button = QPushButton("Open captures")
        self.open_captures_button.setEnabled(False)
        self.open_captures_button.clicked.connect(self._open_captures)
        actions.addWidget(self.open_captures_button)
        self.status_label = self._label("Choose a .smv file or folder.", "status")
        actions.addWidget(self.status_label, 1)
        outer.addLayout(actions)
        outer.addWidget(self._label("Capture log", "section"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log.setPlaceholderText("Capture progress will appear here.")
        outer.addWidget(self.log, 1)

        for editor in (self.output, self.times):
            editor.textChanged.connect(self._validate)
        self.source.textChanged.connect(self._input_changed)
        for box in self.quantities.values():
            box.toggled.connect(self._validate)
        self.subfolders.toggled.connect(self._input_changed)

    def _stylesheet(self, c: dict[str, str]) -> str:
        return f"""
        QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: 'Segoe UI'; font-size: 9pt; }}
        QLabel#title {{ font-size: 15pt; font-weight: 600; }}
        QLabel#section {{ font-weight: 600; }}
        QLabel#helper {{ color: {c['muted']}; font-size: 8.5pt; }}
        QLabel#status {{ color: {c['muted']}; }}
        QLineEdit, QPlainTextEdit, QComboBox, QListWidget {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 7px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
        QLineEdit {{ min-height: 32px; padding: 0 9px; }}
        QComboBox {{ min-height: 32px; padding: 0 9px; }}
        QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
        QListWidget::item {{ padding: 5px 7px; border-radius: 4px; }}
        QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus {{ border: 1px solid {c['accent']}; }}
        QPlainTextEdit {{ padding: 8px; }}
        QPushButton {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 7px; min-height: 32px; padding: 0 13px; }}
        QPushButton:hover {{ background: {c['hover']}; border-color: {c['muted']}; }}
        QPushButton:focus {{ border: 2px solid {c['accent']}; padding: 0 12px; }}
        QPushButton:pressed {{ background: {c['selected']}; }}
        QPushButton:disabled {{ background: {c['bg']}; color: {c['disabled']}; border-color: {c['border']}; }}
        QPushButton#primaryButton {{ background: {c['accent']}; color: {c['bg']}; border-color: {c['accent']}; font-weight: 600; }}
        QPushButton#primaryButton:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
        QPushButton#primaryButton:disabled {{ background: {c['surface']}; color: {c['disabled']}; border-color: {c['border']}; }}
        QToolButton {{ background: transparent; color: {c['text']}; border: 1px solid transparent; border-radius: 6px; padding: 5px 7px; text-align: left; }}
        QToolButton#smallToolButton {{ color: {c['muted']}; font-size: 8.5pt; padding: 2px 5px; }}
        QToolButton:hover {{ background: {c['hover']}; }}
        QToolButton:focus {{ border-color: {c['accent']}; }}
        QCheckBox, QRadioButton {{ spacing: 7px; }}
        QCheckBox:focus, QRadioButton:focus {{ color: {c['accent']}; }}
        QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; background: {c['input']}; border: 1px solid {c['muted']}; }}
        QCheckBox::indicator {{ border-radius: 4px; }}
        QRadioButton::indicator {{ border-radius: 9px; }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover,
        QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {c['accent']}; }}
        QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url('{CHECK_FILE.as_posix()}'); }}
        QRadioButton::indicator:checked {{ border-color: {c['accent']}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {c['accent']}, stop:0.40 {c['accent']}, stop:0.43 {c['input']}, stop:1 {c['input']}); }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: {c['surface']}; border-color: {c['disabled']}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: {c['bg']}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 25px; }}
        QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """

    def _apply_theme(self) -> None:
        c = THEMES[self.theme]
        app = QApplication.instance()
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(c['bg']))
        palette.setColor(QPalette.WindowText, QColor(c['text']))
        palette.setColor(QPalette.Base, QColor(c['input']))
        palette.setColor(QPalette.Text, QColor(c['text']))
        palette.setColor(QPalette.Button, QColor(c['surface']))
        palette.setColor(QPalette.ButtonText, QColor(c['text']))
        palette.setColor(QPalette.Highlight, QColor(c['accent']))
        palette.setColor(QPalette.HighlightedText, QColor(c['bg']))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(c['disabled']))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c['disabled']))
        app.setPalette(palette)
        self.setStyleSheet(self._stylesheet(c))
        self._update_status_color()
        self.theme_button.setText("Dark mode" if self.theme == "light" else "Light mode")

    def _update_status_color(self) -> None:
        c = THEMES[self.theme]
        color = c['error'] if self.last_state == 'failed' else c['success'] if self.last_state == 'success' else c['accent'] if self.last_state == 'running' else c['muted']
        self.status_label.setStyleSheet(f"color: {color};")

    def _toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self._apply_theme()

    def _show_help(self) -> None:
        QMessageBox.information(
            self, "Capture result slices: Help",
            "Choose one .smv file or a folder. Include subfolders is on by default.\n\n"
            "Select slice types and enter times in seconds, separated by commas. "
            "Leave Output folder blank to save beside each case.\n\n"
            "Expand Advanced slices and clipping to scan available positions. "
            "In folder mode, choose a case in the left list. X, Y and Z control "
            "normal captures for that case. Add clip views to capture a slice "
            "again with a different absolute clip coordinate or Min/Max view. "
            "Apply to all cases copies the selected case's axes and clip views "
            "across a folder job; each case stays editable afterward. "
            "Save job and Load job keep these settings for later. "
            "Click Capture slices to run; watch the log or use Cancel to stop. "
            "A completed single-folder capture opens in your file manager. "
            "Use Open captures to revisit it or choose a folder from a batch.\n\n"
            "For Smokeview keyboard shortcuts, open Ashton Smokeview Help from "
            "the Windows Start menu, or run smvhelp on Linux.",
        )

    def _set_status(self, text: str, state: str = "muted") -> None:
        self.last_state = state
        self.status_label.setText(text)
        self._update_status_color()

    def _mode_changed(self) -> None:
        self.subfolders.setVisible(self.folder_radio.isChecked())
        self._input_changed()
        self._update_settings_height()

    def _current_scan_key(self) -> tuple[str, bool, bool]:
        return (self.source.text().strip(), self.folder_radio.isChecked(),
                self.subfolders.isChecked())

    def _input_changed(self) -> None:
        self.scan_generation += 1
        self.scan_key = None
        self.scan_pending = False
        self.scan_error = ""
        self.case_positions = []
        self.case_axes = {}
        self.case_drafts = {}
        self.loaded_case_data = None
        self.load_warning = ""
        self.case_index = 0
        self.scan_button.setEnabled(True)
        self.case_list.clear()
        self._show_case(0)
        self._validate()

    def _show_case(self, index: int) -> None:
        self.rendering_rows = True
        for widgets in self.row_widgets:
            for widget in widgets:
                self.variants_grid.removeWidget(widget)
                widget.deleteLater()
        self.row_widgets.clear()
        count = len(self.case_positions)
        self.case_index = max(0, min(index, count - 1))
        self.case_list.setVisible(count > 1)
        self.apply_all_button.setVisible(count > 1)
        self.apply_all_button.setEnabled(count > 1 and not self.scan_pending and self.job is None)
        self.add_variant.setEnabled(bool(count))
        for box in self.axis_boxes.values():
            box.setEnabled(bool(count))
        if not count:
            self.case_label.setText("Scan input to list .smv cases.")
            self.plane_summary.setText("Scan input to list available slices.")
        else:
            case, positions = self.case_positions[self.case_index]
            source = Path(self.scan_key[0]).expanduser().resolve()
            name = case.relative_to(source) if self.scan_key[1] else Path(case.name)
            self.case_label.setText(f"Case {self.case_index + 1} of {count}: {name}")
            self.case_label.setToolTip(str(case))
            for axis, box in self.axis_boxes.items():
                box.setChecked(axis in self.case_axes[case])
            for draft in self.case_drafts[case]:
                self._add_variant_row(draft)
            self.plane_summary.setText(f"{len(positions)} slices found in {case.name}.")
        self.rendering_rows = False
        self._update_settings_height()

    def _apply_to_all_cases(self) -> None:
        if len(self.case_positions) < 2 or self.scan_pending or self.job is not None:
            return
        self._rows_changed()
        selected_case = self.case_positions[self.case_index][0]
        axes = self.case_axes[selected_case]
        drafts = self.case_drafts[selected_case]
        for case, _ in self.case_positions:
            self.case_axes[case] = set(axes)
            self.case_drafts[case] = list(drafts)
        missing = sum(any(slice_text not in positions for slice_text, _, _ in drafts)
                      for case, positions in self.case_positions if case != selected_case)
        summary = f"Applied axes and {len(drafts)} clip view(s) to all {len(self.case_positions)} cases."
        if missing:
            summary += f" {missing} case(s) lack a selected slice; review them before capture."
        self.plane_summary.setText(summary)
        self._validate()

    def _axis_changed(self) -> None:
        if self.rendering_rows or not self.case_positions:
            return
        case = self.case_positions[self.case_index][0]
        self.case_axes[case] = {axis for axis, box in self.axis_boxes.items() if box.isChecked()}
        self._validate()

    def _add_variant_row(self, draft: tuple[str, str, str] | None = None) -> None:
        if not self.case_positions:
            return
        _, positions = self.case_positions[self.case_index]
        if draft is None:
            selected = positions[0] if positions else ""
            draft = (selected, selected[2:] if selected else "", "max")
        slice_box = QComboBox()
        slice_box.setEditable(True)
        slice_box.addItems(positions)
        slice_box.setCurrentText(draft[0])
        slice_box.setAccessibleName("Slice position")
        clip = QLineEdit(draft[1])
        clip.setPlaceholderText("metres")
        clip.setAccessibleName("Clip coordinate in metres")
        clip.setFixedWidth(96)
        side = QComboBox()
        side.addItems(["Max", "Min"])
        side.setCurrentText(draft[2].title())
        side.setAccessibleName("View from minimum or maximum")
        remove = QPushButton("Remove")
        widgets = (slice_box, clip, side, remove)
        row = len(self.row_widgets) + 1
        for column, widget in enumerate(widgets):
            self.variants_grid.addWidget(widget, row, column)
        self.row_widgets.append(widgets)
        slice_box.activated.connect(lambda _index, box=slice_box, field=clip:
                                    field.setText(box.currentText().split("=", 1)[-1]))
        slice_box.currentTextChanged.connect(self._rows_changed)
        clip.textChanged.connect(self._rows_changed)
        side.currentTextChanged.connect(self._rows_changed)
        remove.clicked.connect(lambda _checked=False, row_widgets=widgets:
                               self._remove_variant_row(row_widgets))
        self._rows_changed()
        self._update_settings_height()

    def _remove_variant_row(self, widgets) -> None:
        if widgets not in self.row_widgets:
            return
        self._rows_changed()
        case = self.case_positions[self.case_index][0]
        index = self.row_widgets.index(widgets)
        self.case_drafts[case].pop(index)
        self._show_case(self.case_index)
        self._validate()

    def _rows_changed(self) -> None:
        if self.rendering_rows or not self.case_positions:
            return
        case = self.case_positions[self.case_index][0]
        self.case_drafts[case] = [(slice_box.currentText(), clip.text(), side.currentText().lower())
                                  for slice_box, clip, side, _ in self.row_widgets]
        self._validate()

    def _case_settings(self) -> dict[Path, CaseCaptureSettings]:
        settings = {}
        for case, _positions in self.case_positions:
            variants = []
            seen = set()
            for slice_text, clip_text, side in self.case_drafts.get(case, []):
                token = parse_plane_selection(slice_text)
                if not token or "," in token:
                    raise ValueError(f"Enter one X, Y or Z slice in each row for {case.name}.")
                try:
                    clip = float(clip_text)
                except ValueError as error:
                    raise ValueError(f"Enter a numeric clip coordinate for {case.name}.") from error
                if not math.isfinite(clip):
                    raise ValueError(f"Clip coordinate must be finite for {case.name}.")
                if side not in ("min", "max"):
                    raise ValueError(f"Choose Min or Max for {case.name}.")
                variant = ClipVariant(token, round(clip, 3), side)
                if variant.argument() in seen:
                    raise ValueError(f"Duplicate clip view for {case.name}: {variant.argument()}")
                seen.add(variant.argument())
                variants.append(variant)
            settings[case] = CaseCaptureSettings(self.case_axes.get(case, set("xyz")), variants)
        return settings

    def _update_settings_height(self) -> None:
        self._settle_settings_height()
        self.settings_height_timer.start(10)

    def _settle_settings_height(self) -> None:
        self.settings_scroll.widget().layout().invalidate()
        self.settings_scroll.widget().layout().activate()
        self.settings_scroll.widget().adjustSize()
        self.settings_scroll.setMaximumHeight(max(240, self.settings_scroll.widget().sizeHint().height() + 4))
        self.settings_scroll.updateGeometry()
        self.layout().activate()
        self.settings_scroll.scrollbar_timer.start(0)

    def _toggle_advanced(self, open_: bool) -> None:
        self.advanced_button.setArrowType(Qt.DownArrow if open_ else Qt.RightArrow)
        self.advanced.setVisible(open_)
        self.log.setMinimumHeight(110 if open_ else 140)
        self._update_settings_height()
        if open_ and self.scan_key != self._current_scan_key():
            self._scan_planes()

    def _browse_source(self) -> None:
        if self.folder_radio.isChecked():
            selected = QFileDialog.getExistingDirectory(self, "Select folder")
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "Select Smokeview case", "", "Smokeview cases (*.smv);;All files (*)")
        if selected:
            self.source.setText(selected)
            if self.advanced_button.isChecked():
                self._scan_planes()

    def _browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select output folder")
        if selected:
            self.output.setText(selected)

    def _reason(self) -> str:
        source_text = self.source.text().strip()
        if not source_text:
            return "Choose a .smv file or folder."
        source = Path(source_text).expanduser()
        if self.folder_radio.isChecked():
            if not source.is_dir():
                return "Choose an existing folder."
        elif not source.is_file() or source.suffix.lower() != ".smv":
            return "Choose an existing .smv file."
        try:
            parse_times(self.times.text().strip())
        except ValueError as error:
            return str(error)
        if not any(box.isChecked() for box in self.quantities.values()):
            return "Select at least one slice type."
        if self.advanced_button.isChecked():
            if self.scan_pending:
                return "Scanning slice positions..."
            if self.scan_error:
                return self.scan_error
            if self.scan_key != self._current_scan_key():
                return "Scan input to configure slices and clipping."
            if self.load_warning:
                return self.load_warning
            try:
                settings = self._case_settings()
            except ValueError as error:
                return str(error)
            if not any(value.axes or value.variants for value in settings.values()):
                return "Enable a normal axis or add a clip view."
        output = self.output.text().strip()
        if output and Path(output).expanduser().exists() and not Path(output).expanduser().is_dir():
            return "Output must be a folder."
        return ""

    def _validate(self) -> None:
        if self.job is not None:
            return
        reason = self._reason()
        self.run_button.setEnabled(not reason)
        self._set_status(reason or "Ready to capture.")

    def _scan_planes(self) -> None:
        source_text = self.source.text().strip()
        if not source_text:
            self._input_changed()
            return
        self.scan_generation += 1
        generation = self.scan_generation
        folder_mode = self.folder_radio.isChecked()
        recurse = self.subfolders.isChecked()
        self.scan_pending = True
        self.scan_error = ""
        self.scan_button.setEnabled(False)
        self.apply_all_button.setEnabled(False)
        self.plane_summary.setText("Scanning .smv cases and slice positions...")
        self._validate()
        def scan() -> None:
            try:
                source = Path(source_text).expanduser().resolve()
                cases = find_cases(source, folder_mode, recurse)
                found = [(case, available_planes(case)) for case in cases]
                self.scan_result.emit(generation, found, "")
            except (OSError, ValueError) as error:
                self.scan_result.emit(generation, [], str(error))
        threading.Thread(target=scan, daemon=True).start()

    @Slot(int, list, str)
    def _scan_finished(self, generation: int, found: list, error: str) -> None:
        if generation != self.scan_generation:
            return
        self.scan_pending = False
        self.scan_button.setEnabled(True)
        if error:
            self.scan_key = None
            self.scan_error = f"Could not scan input: {error}"
            self.case_positions = []
            self.case_axes = {}
            self.case_drafts = {}
            self.case_list.clear()
            self._show_case(0)
            self.plane_summary.setText(self.scan_error)
        else:
            self.case_positions = found
            self.case_axes = {case: self.case_axes.get(case, set("xyz")) for case, _ in found}
            self.case_drafts = {case: self.case_drafts.get(case, []) for case, _ in found}
            self.scan_key = self._current_scan_key()
            source = Path(self.scan_key[0]).expanduser().resolve()
            self.case_list.blockSignals(True)
            self.case_list.clear()
            for case, _ in found:
                name = case.relative_to(source) if self.folder_radio.isChecked() else Path(case.name)
                self.case_list.addItem(str(name))
            self.case_list.setCurrentRow(0)
            self.case_list.blockSignals(False)
            if self.loaded_case_data is not None:
                found_keys = set()
                for case, _ in found:
                    key = (case.relative_to(source) if self.folder_radio.isChecked()
                           else Path(case.name)).as_posix()
                    found_keys.add(key)
                    saved = self.loaded_case_data.get(key)
                    if saved is not None:
                        self.case_axes[case] = set(saved["axes"])
                        self.case_drafts[case] = [tuple(row) for row in saved["variants"]]
                missing = set(self.loaded_case_data) - found_keys
                self.load_warning = ("Saved cases are missing: " + ", ".join(sorted(missing))) if missing else ""
                self.loaded_case_data = None
            self._show_case(0)
        self._validate()

    def _save_job(self) -> None:
        if self.scan_pending or self.scan_key != self._current_scan_key() or not self.case_positions:
            QMessageBox.warning(self, "Save job", "Scan the selected input before saving a job.")
            return
        reason = self._reason()
        if reason:
            QMessageBox.warning(self, "Save job", reason)
            return
        try:
            settings = self._case_settings()
            parse_times(self.times.text().strip())
        except ValueError as error:
            QMessageBox.warning(self, "Save job", str(error))
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save capture job", "capture-job.json",
                                                   "Capture jobs (*.json)")
        if not filename:
            return
        path = Path(filename).expanduser().resolve()
        source = Path(self.source.text().strip()).expanduser().resolve()
        relative = lambda value: Path(os.path.relpath(value, path.parent)).as_posix()
        cases = {}
        for case, config in settings.items():
            key = (case.relative_to(source) if self.folder_radio.isChecked()
                   else Path(case.name)).as_posix()
            cases[key] = {"axes": sorted(config.axes),
                          "variants": [[v.slice, f"{v.clip:.3f}", v.side] for v in config.variants]}
        data = {"schema": 1, "source": relative(source),
                "folder_mode": self.folder_radio.isChecked(),
                "include_subfolders": self.subfolders.isChecked(),
                "output": relative(Path(self.output.text().strip()).expanduser().resolve())
                          if self.output.text().strip() else "",
                "times": self.times.text().strip(),
                "quantities": [name for name, box in self.quantities.items() if box.isChecked()],
                "crop": self.crop.isChecked(), "overwrite": self.overwrite.isChecked(),
                "cases": cases}
        try:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Save job", str(error))
            return
        self._set_status(f"Saved job: {path.name}", "success")

    def _load_job(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Load capture job", "", "Capture jobs (*.json)")
        if not filename:
            return
        try:
            path = Path(filename).expanduser().resolve()
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("cases"), dict):
                raise ValueError("Unsupported capture job format.")
            source = (path.parent / data["source"]).resolve()
            output = (path.parent / data["output"]).resolve() if data.get("output") else None
            for saved in data["cases"].values():
                if not isinstance(saved, dict) or not set(saved["axes"]) <= set("xyz"):
                    raise ValueError("Invalid case axis settings in job file.")
                if not isinstance(saved["variants"], list):
                    raise ValueError("Invalid clip rows in job file.")
                if any(not isinstance(row, list) or len(row) != 3 or
                       not all(isinstance(value, str) for value in row)
                       for row in saved["variants"]):
                    raise ValueError("Invalid clip row in job file.")
            parse_times(data["times"])
            if not set(data["quantities"]) <= set(QUANTITIES):
                raise ValueError("Invalid slice types in job file.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, "Load job", str(error))
            return
        self.folder_radio.setChecked(bool(data["folder_mode"]))
        self.file_radio.setChecked(not bool(data["folder_mode"]))
        self.subfolders.setChecked(bool(data["include_subfolders"]))
        self.source.setText(str(source))
        self.output.setText(str(output) if output else "")
        self.times.setText(data["times"])
        for name, box in self.quantities.items():
            box.setChecked(name in data["quantities"])
        self.crop.setChecked(bool(data["crop"]) and self.crop.isEnabled())
        self.overwrite.setChecked(bool(data["overwrite"]))
        self.loaded_case_data = data["cases"]
        if self.advanced_button.isChecked():
            self._scan_planes()
        else:
            self.advanced_button.setChecked(True)

    def _start(self) -> None:
        try:
            source = Path(self.source.text().strip()).expanduser().resolve()
            folder_mode = self.folder_radio.isChecked()
            cases = find_cases(source, folder_mode, self.subfolders.isChecked())
            times = parse_times(self.times.text().strip())
            quantities = [q for q, box in self.quantities.items() if box.isChecked()]
            if self.advanced_button.isChecked():
                if self.scan_key != self._current_scan_key() or self.scan_pending:
                    raise ValueError("Scan input to configure slices and clipping.")
                if cases != [case for case, _ in self.case_positions]:
                    raise ValueError("The folder contents changed. Scan input again.")
                case_settings = self._case_settings()
                planes = ""
            else:
                case_settings = None
                planes = ""
            output_text = self.output.text().strip()
            output = Path(output_text).expanduser().resolve() if output_text else None
            if output is not None and output.exists() and not output.is_dir():
                raise ValueError(f"Output is not a folder: {output}")
            if getattr(sys, "frozen", False) and sys.platform == "win32":
                worker_exe = Path(sys.executable).resolve().with_name("capture_result_slices.exe")
                if not worker_exe.is_file():
                    raise ValueError(f"Capture engine is missing: {worker_exe}")
            elif not CAPTURE_SCRIPT.is_file():
                raise ValueError(f"Capture engine is missing: {CAPTURE_SCRIPT}")
        except (ValueError, OSError) as error:
            QMessageBox.critical(self, "Capture setup", str(error))
            return
        self.job = CaptureJob(cases, source, folder_mode, output, times, quantities, planes,
                              self.crop.isChecked(), self.overwrite.isChecked(), case_settings)
        self.apply_all_button.setEnabled(False)
        self.capture_folders = []
        self.open_captures_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        active_count = (sum(bool(value.axes or value.variants) for value in case_settings.values())
                        if case_settings is not None else len(cases))
        self._set_status(f"Running: {active_count} case(s), {len(times)} time(s)", "running")
        self.log.appendPlainText(f"Starting {active_count} case(s) at {len(times)} time(s).")
        self.thread = QThread(self)
        self.worker = CaptureWorker(self.job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_log)
        self.worker.status.connect(self._progress)
        self.worker.done.connect(self._capture_done)
        self.worker.done.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot(str)
    def _append_log(self, line: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(line)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    @Slot(str)
    def _progress(self, text: str) -> None:
        self._set_status(text, "running")

    @Slot(str, str)
    def _capture_done(self, message: str, state: str) -> None:
        self.pending_result = (message, state)
        self.capture_folders = list(self.job.completed_outputs) if self.job is not None else []
        self.open_captures_button.setEnabled(bool(self.capture_folders))
        self.cancel_button.setEnabled(False)
        self._set_status(message, state)
        if state == "success" and len(self.capture_folders) == 1:
            self._open_capture_folder(self.capture_folders[0])
        if self.thread is None:
            self.job = None
            self._validate()
            self._set_status(message, state)
            self.pending_result = None

    def _open_capture_folder(self, folder: Path) -> None:
        if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
            opener = shutil.which("xdg-open")
            command = [opener, str(folder)] if opener else None
            if command is None:
                opener = shutil.which("gio")
                if opener:
                    command = [opener, "open", str(folder)]
            if command is None:
                QMessageBox.warning(self, "Open captures", "No desktop folder opener was found.")
                return
            try:
                subprocess.Popen(command, env=external_process_env(),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            except OSError as error:
                QMessageBox.warning(self, "Open captures", str(error))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(self, "Open captures", f"Could not open {folder}")

    def _open_captures(self) -> None:
        if not self.capture_folders:
            return
        if len(self.capture_folders) == 1:
            folder = self.capture_folders[0]
        else:
            choice, accepted = QInputDialog.getItem(
                self, "Open captures", "Choose an output folder:",
                [str(path) for path in self.capture_folders], 0, False)
            if not accepted:
                return
            folder = Path(choice)
        self._open_capture_folder(folder)

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self.job = None
        self.apply_all_button.setEnabled(len(self.case_positions) > 1)
        self._validate()
        if self.pending_result is not None:
            self._set_status(*self.pending_result)
            self.pending_result = None

    def _cancel(self) -> None:
        if self.job is not None:
            self._set_status("Cancelling…", "running")
            self.job.cancel()

    def closeEvent(self, event) -> None:
        if self.job is not None:
            answer = QMessageBox.question(self, "Capture running", "Stop capturing and close?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.job.cancel()
            if self.thread is not None:
                self.thread.quit()
                if not self.thread.wait(5000):
                    self._set_status("Waiting for capture to stop…", "running")
                    event.ignore()
                    return
        event.accept()


def main() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        sys.argv.remove("--smoke-test")
    app = QApplication(sys.argv)
    app.setApplicationName("smv-cap-ui")
    app.setApplicationDisplayName("Capture result slices")
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("smv-cap-ui")
    if LOGO_FILE.is_file():
        app.setWindowIcon(QIcon(str(LOGO_FILE)))
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    window = CaptureWindow()
    window.show()
    if smoke_test:
        def exercise_controls() -> None:
            try:
                if not LOGO_FILE.is_file() or not CHECK_FILE.is_file():
                    raise RuntimeError("Capture UI assets are missing")
                if window.open_captures_button.isEnabled():
                    raise RuntimeError("Open captures should be disabled before a capture")
                case = Path.cwd() / "smv-ui-smoke-test.smv"
                window.case_positions = [(case, ["Y=5.000"])]
                window.case_axes = {case: set("xyz")}
                window.case_drafts = {case: []}
                window.scan_key = (str(case), False, True)
                window._show_case(0)
                window.add_variant.click()
                if len(window.row_widgets) != 1:
                    raise RuntimeError("Add clip view did not create a row")
                window.row_widgets[0][3].click()
                if window.row_widgets:
                    raise RuntimeError("Remove did not delete the clip view row")
                other_case = Path.cwd() / "smv-ui-smoke-test-2.smv"
                window.case_positions.append((other_case, ["Y=5.000"]))
                window.case_axes[other_case] = set("xyz")
                window.case_drafts[other_case] = []
                window._show_case(0)
                window.add_variant.click()
                window.axis_boxes["x"].setChecked(False)
                window.apply_all_button.click()
                if (window.case_axes[other_case] != {"y", "z"}
                        or window.case_drafts[other_case] != window.case_drafts[case]):
                    raise RuntimeError("Apply to all did not copy case settings")
                window._show_case(1)
                window.axis_boxes["z"].setChecked(False)
                if "z" not in window.case_axes[case]:
                    raise RuntimeError("Editing one case changed another case")
                for _ in range(20):
                    window.theme_button.click()
                    app.processEvents()
                if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
                    smokeview = Path(sys.executable).resolve().parent / "smokeview"
                    result = subprocess.run([str(smokeview), "-version"],
                                            env=external_process_env(), capture_output=True,
                                            text=True, timeout=15, check=False)
                    if result.returncode != 0:
                        raise RuntimeError(f"Smokeview failed from bundled UI: {result.stderr.strip()}")
            except Exception as error:
                print(f"Capture UI smoke test failed: {error}", file=sys.stderr)
                app.exit(1)
                return
            app.quit()
        QTimer.singleShot(0, exercise_controls)
    result = app.exec()
    window.close()
    window.deleteLater()
    app.processEvents()
    del window
    del app
    raise SystemExit(result)


if __name__ == "__main__":
    main()
