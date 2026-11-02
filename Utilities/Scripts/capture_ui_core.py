"""Capture window orchestration without a GUI dependency."""
from __future__ import annotations

import math
import os
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
from typing import Callable

QUANTITIES = ("visibility", "temperature", "velocity", "pressure")
CAPTURE_SCRIPT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                  else Path(__file__).resolve().parent) / "capture_result_slices.py"


@dataclass(frozen=True)
class ClipVariant:
    slice: str
    clip: float
    side: str = "max"

    def argument(self) -> str:
        return f"{self.slice}@{self.clip:.3f}:{self.side}"


@dataclass
class CaseCaptureSettings:
    axes: set[str] = field(default_factory=lambda: set("xyz"))
    variants: list[ClipVariant] = field(default_factory=list)


def parse_times(text: str) -> list[float]:
    values = []
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


def time_token(value: float) -> str:
    return f"t_{repr(float(value)).replace('-', 'm').replace('.', 'p')}s"


def output_for_case(case: Path, chosen_root: Path | None) -> Path:
    return chosen_root if chosen_root is not None else case.with_name(f"{case.stem}_slice_captures")


def capture_prefix(case: Path, source: Path, folder_mode: bool,
                   duplicate_stem: bool, time: float, multiple_times: bool) -> str:
    prefix = case.stem
    if duplicate_stem:
        relative = case.relative_to(source) if folder_mode else Path(case.name)
        digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:8]
        prefix += f"__{digest}"
    if multiple_times:
        prefix += f"__{time_token(time)}"
    return prefix


def crop_tool_available() -> bool:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "imagemagick" / "magick.exe"
        if bundled.is_file():
            return True
    return bool(shutil.which("magick") or (sys.platform != "win32" and shutil.which("convert")))


def external_process_env() -> dict[str, str] | None:
    """Restore the host library search path for programs launched by a frozen Linux UI."""
    if not (getattr(sys, "frozen", False) and sys.platform.startswith("linux")):
        return None
    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    return env


class CaptureJob:
    def __init__(self, cases: list[Path], source: Path, folder_mode: bool,
                 output_root: Path | None, times: list[float], quantities: list[str],
                 planes: str | dict[Path, str], crop: bool, overwrite: bool,
                 case_settings: dict[Path, CaseCaptureSettings] | None = None) -> None:
        self.cases = cases
        self.source = source
        self.folder_mode = folder_mode
        self.output_root = output_root
        self.times = times
        self.quantities = quantities
        self.planes = planes
        self.crop = crop
        self.overwrite = overwrite
        self.case_settings = case_settings
        self.cancelled = threading.Event()
        self.process: subprocess.Popen[str] | None = None
        self.completed_outputs: list[Path] = []

    def cancel(self) -> None:
        self.cancelled.set()
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def run(self, log: Callable[[str], None], status: Callable[[str], None]) -> tuple[str, str]:
        failures = 0
        self.completed_outputs.clear()
        if self.case_settings is not None:
            active_cases = [case for case in self.cases if
                            (settings := self.case_settings.get(case, CaseCaptureSettings())).axes
                            or settings.variants]
        else:
            active_cases = ([case for case in self.cases if self.planes.get(case)]
                            if isinstance(self.planes, dict) else self.cases)
        total = len(active_cases) * len(self.times)
        stem_counts = Counter(case.stem.casefold() for case in active_cases)
        try:
            if len(active_cases) < len(self.cases):
                log(f"Skipping {len(self.cases) - len(active_cases)} case(s) with no selected slice positions.\n")
            for case_number, case in enumerate(active_cases, 1):
                for time in self.times:
                    if self.cancelled.is_set():
                        return "Cancelled.", "muted"
                    output = output_for_case(case, self.output_root)
                    prefix = capture_prefix(case, self.source, self.folder_mode,
                                            stem_counts[case.stem.casefold()] > 1,
                                            time, len(self.times) > 1)
                    status(f"Case {case_number}/{len(active_cases)} · {time:g} s")
                    log(f"\n{case} at {time:g} s → {output}\n")
                    if getattr(sys, "frozen", False) and os.name == "nt":
                        install_dir = Path(sys.executable).resolve().parent
                        command = [str(install_dir / "capture_result_slices.exe"), str(case),
                                   "--smokeview", str(install_dir / "smokeview.exe")]
                    else:
                        python = shutil.which("python3") if getattr(sys, "frozen", False) else sys.executable
                        if not python:
                            raise RuntimeError("Python 3 is required to run the capture engine.")
                        command = [python, "-u", str(CAPTURE_SCRIPT), str(case)]
                    command.extend(["-o", str(output), "--prefix", prefix, "--time", repr(time),
                                    "--quantities", *self.quantities])
                    planes = self.planes.get(case, "") if isinstance(self.planes, dict) else self.planes
                    if planes:
                        command.extend(["--planes", planes])
                    if self.case_settings is not None:
                        settings = self.case_settings.get(case, CaseCaptureSettings())
                        command.extend(["--default-axes", "".join(sorted(settings.axes))])
                        for variant in settings.variants:
                            command.extend(["--clip-variant", variant.argument()])
                    if not self.crop:
                        command.append("--no-crop")
                    if self.overwrite:
                        command.append("--overwrite")
                    kwargs: dict[str, object] = {"stdout": subprocess.PIPE,
                                                 "stderr": subprocess.STDOUT,
                                                 "text": True, "encoding": "utf-8",
                                                 "errors": "replace"}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    else:
                        kwargs["start_new_session"] = True
                        clean_env = external_process_env()
                        if clean_env is not None:
                            kwargs["env"] = clean_env
                    self.process = subprocess.Popen(command, **kwargs)
                    assert self.process.stdout is not None
                    for line in self.process.stdout:
                        log(line)
                    result = self.process.wait()
                    self.process = None
                    if result == 0 and output.is_dir() and output not in self.completed_outputs:
                        self.completed_outputs.append(output)
                    if result != 0 and not self.cancelled.is_set():
                        failures += 1
                        log(f"Capture failed (exit code {result}).\n")
            if self.cancelled.is_set():
                return "Cancelled.", "muted"
            return f"Finished: {total - failures} succeeded, {failures} failed.", "failed" if failures else "success"
        except Exception as error:
            log(f"Capture stopped: {error}\n")
            return "Capture stopped with an error.", "failed"
        finally:
            self.process = None
