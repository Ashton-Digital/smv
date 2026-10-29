#!/usr/bin/env python3
"""PySide6 desktop window for Ashton Smokeview slice captures."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget, QButtonGroup)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from capture_ui_core import (CAPTURE_SCRIPT, QUANTITIES, CaptureJob,
    crop_tool_available, find_cases, parse_times)
from smv_planes import available_planes, parse_plane_selection

LOGO_FILE = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
             else SCRIPT_DIR) / "capture_logo.png"

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
    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), 360)


class CaptureWindow(QWidget):
    scan_result = Signal(int, list, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ashton Smokeview — Capture result slices")
        if LOGO_FILE.is_file():
            self.setWindowIcon(QIcon(str(LOGO_FILE)))
        self.job: CaptureJob | None = None
        self.thread: QThread | None = None
        self.pending_result: tuple[str, str] | None = None
        self.scan_generation = 0
        self.theme = "dark"
        self.last_state = "muted"
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

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)
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
        fields.setSpacing(14)

        # Input and output share one aligned label/path/button grid.
        paths = QWidget()
        grid = QGridLayout(paths)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
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
        setting_layout.setSpacing(8)
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
        self.advanced_button.setText("Advanced — slice positions")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setArrowType(Qt.RightArrow)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        fields.addWidget(self.advanced_button)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(16, 0, 0, 0)
        advanced_layout.setSpacing(6)
        self.limit_planes = QCheckBox("Capture only selected slice positions")
        self.limit_planes.toggled.connect(self._toggle_plane_details)
        advanced_layout.addWidget(self.limit_planes)
        self.plane_details = QWidget()
        detail_layout = QVBoxLayout(self.plane_details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(5)
        detail_layout.addWidget(self._label("Positions in metres · for example Y=3 or Y=3,Y=5", "helper"))
        plane_row = QHBoxLayout()
        plane_row.setSpacing(8)
        self.plane_entry = QComboBox()
        self.plane_entry.setEditable(True)
        self.plane_entry.setAccessibleName("Selected slice positions")
        plane_row.addWidget(self.plane_entry, 1)
        self.scan_button = QPushButton("Scan input")
        self.scan_button.clicked.connect(self._scan_planes)
        plane_row.addWidget(self.scan_button)
        detail_layout.addLayout(plane_row)
        self.available_planes = self._label("Scan a case to see its slice positions.", "helper")
        self.available_planes.setWordWrap(True)
        detail_layout.addWidget(self.available_planes)
        advanced_layout.addWidget(self.plane_details)
        fields.addWidget(self.advanced)
        self.advanced.setVisible(False)
        self.plane_details.setVisible(False)
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
        self.status_label = self._label("Choose a .smv file or folder.", "status")
        actions.addWidget(self.status_label, 1)
        outer.addLayout(actions)
        outer.addWidget(self._label("Capture log", "section"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log.setPlaceholderText("Capture progress will appear here.")
        outer.addWidget(self.log, 1)

        for editor in (self.source, self.output, self.times, self.plane_entry.lineEdit()):
            editor.textChanged.connect(self._validate)
        for box in self.quantities.values():
            box.toggled.connect(self._validate)
        self.subfolders.toggled.connect(self._validate)
        self.limit_planes.toggled.connect(self._validate)

    def _stylesheet(self, c: dict[str, str]) -> str:
        return f"""
        QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: 'Segoe UI'; font-size: 9pt; }}
        QLabel#title {{ font-size: 15pt; font-weight: 600; }}
        QLabel#section {{ font-weight: 600; }}
        QLabel#helper {{ color: {c['muted']}; font-size: 8.5pt; }}
        QLabel#status {{ color: {c['muted']}; }}
        QLineEdit, QComboBox, QPlainTextEdit {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 7px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
        QLineEdit, QComboBox {{ min-height: 32px; padding: 0 9px; }}
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
        QComboBox QLineEdit {{ border: none; background: transparent; min-height: 0; padding: 0; }}
        QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; selection-background-color: {c['selected']}; }}
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
        QToolButton:hover {{ background: {c['hover']}; }}
        QToolButton:focus {{ border-color: {c['accent']}; }}
        QCheckBox, QRadioButton {{ spacing: 7px; }}
        QCheckBox:focus, QRadioButton:focus {{ color: {c['accent']}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: {c['bg']}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 25px; }}
        QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """

    def _apply_theme(self) -> None:
        c = THEMES[self.theme]
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
        QApplication.instance().setPalette(palette)
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
            self, "Capture result slices — Help",
            "Choose one .smv file or a folder. Include subfolders is on by default.\n\n"
            "Select slice types and enter times in seconds, separated by commas. "
            "Leave Output folder blank to save beside each case.\n\n"
            "Advanced lets you scan and select slice positions such as Y=3,Y=5. "
            "Click Capture slices to run; watch the log or use Cancel to stop.\n\n"
            "For Smokeview keyboard shortcuts, open Ashton Smokeview Help from "
            "the Windows Start menu, or run smvhelp on Linux.",
        )

    def _set_status(self, text: str, state: str = "muted") -> None:
        self.last_state = state
        self.status_label.setText(text)
        self._update_status_color()

    def _mode_changed(self) -> None:
        self.subfolders.setVisible(self.folder_radio.isChecked())
        self._validate()

    def _toggle_advanced(self, open_: bool) -> None:
        self.advanced_button.setArrowType(Qt.DownArrow if open_ else Qt.RightArrow)
        self.advanced.setVisible(open_)
        if open_ and self.limit_planes.isChecked():
            self._scan_planes()

    def _toggle_plane_details(self, enabled: bool) -> None:
        self.plane_details.setVisible(enabled)
        if enabled:
            self._scan_planes()

    def _browse_source(self) -> None:
        if self.folder_radio.isChecked():
            selected = QFileDialog.getExistingDirectory(self, "Select folder")
        else:
            selected, _ = QFileDialog.getOpenFileName(self, "Select Smokeview case", "", "Smokeview cases (*.smv);;All files (*)")
        if selected:
            self.source.setText(selected)
            if self.limit_planes.isChecked():
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
        if self.limit_planes.isChecked():
            try:
                if not parse_plane_selection(self.plane_entry.currentText()):
                    return "Enter a slice position, such as Y=3."
            except ValueError as error:
                return str(error)
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
            self.available_planes.setText("Choose a .smv file or folder first.")
            return
        self.scan_generation += 1
        generation = self.scan_generation
        folder_mode = self.folder_radio.isChecked()
        recurse = self.subfolders.isChecked()
        self.scan_button.setEnabled(False)
        self.available_planes.setText("Scanning slice positions…")
        def scan() -> None:
            try:
                source = Path(source_text).expanduser().resolve()
                cases = find_cases(source, folder_mode, recurse)
                positions = {p for case in cases for p in available_planes(case)}
                ordered = sorted(positions, key=lambda token: ("xyz".index(token[0].lower()), float(token[2:])))
                self.scan_result.emit(generation, ordered, len(cases), "")
            except (OSError, ValueError) as error:
                self.scan_result.emit(generation, [], 0, str(error))
        threading.Thread(target=scan, daemon=True).start()

    @Slot(int, list, int, str)
    def _scan_finished(self, generation: int, positions: list, count: int, error: str) -> None:
        if generation != self.scan_generation:
            return
        self.scan_button.setEnabled(True)
        if error:
            self.available_planes.setText(f"Could not scan input: {error}")
        else:
            current = self.plane_entry.currentText()
            self.plane_entry.clear()
            self.plane_entry.addItems(positions)
            self.plane_entry.setCurrentText(current)
            self.available_planes.setText(f"Available in {count} case(s): {', '.join(positions)}" if positions else "No 2D slice positions found in the selected input.")

    def _start(self) -> None:
        try:
            source = Path(self.source.text().strip()).expanduser().resolve()
            folder_mode = self.folder_radio.isChecked()
            cases = find_cases(source, folder_mode, self.subfolders.isChecked())
            times = parse_times(self.times.text().strip())
            quantities = [q for q, box in self.quantities.items() if box.isChecked()]
            planes = parse_plane_selection(self.plane_entry.currentText()) if self.limit_planes.isChecked() else ""
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
                              self.crop.isChecked(), self.overwrite.isChecked())
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._set_status(f"Running · {len(cases)} case(s), {len(times)} time(s)", "running")
        self.log.appendPlainText(f"Starting {len(cases)} case(s) at {len(times)} time(s).")
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
        self.cancel_button.setEnabled(False)
        self._set_status(message, state)
        if self.thread is None:
            self.job = None
            self._validate()
            self._set_status(message, state)
            self.pending_result = None

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self.job = None
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
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    window = CaptureWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(0, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
