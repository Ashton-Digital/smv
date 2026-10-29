#!/usr/bin/env python3
"""Render every configured Smokeview result-review slice.

Dependencies:
  - Python 3.10 or newer.
  - A graphical desktop session (X11 or Wayland on Linux).
  - A Smokeview executable built with RENDERRESULTS and RENDERFULLSCREEN.
  - ImageMagick (``magick`` or ``convert``) for model cropping; use
    ``--no-crop`` when ImageMagick is intentionally unavailable.

Optional display-resolution probes: ``xrandr`` or ``xdpyinfo``.  If neither
is installed, the script uses 1920x1080 unless ``--size`` is supplied.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile


QUANTITIES = ("visibility", "temperature", "velocity", "pressure")
QUANTITY_PATTERN = "|".join(QUANTITIES)
COMPONENT_PATTERN = re.compile(
    r"^\s*\d+:\s+(\d+)x(\d+)([+-]\d+)([+-]\d+)\s+"
    r"[^ ]+\s+([0-9.eE+-]+)\s+(.+)$"
)


@dataclass
class Capture:
    path: Path
    quantity: str
    axis: str
    sequence: str
    position: float
    width: int
    height: int
    model_bounds: tuple[int, int, int, int] | None = None


def legacy_capture_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"{re.escape(prefix)}_({QUANTITY_PATTERN})_([xyz])_(\d{{3}})_"
        r"(m?\d+p\d{3})\.png"
    )


def human_capture_pattern(prefix: str) -> re.Pattern[str]:
    quantities = "|".join(quantity.title() for quantity in QUANTITIES)
    return re.compile(
        rf"{re.escape(prefix)} ({quantities}) [XYZ] Slice \d{{3}} at "
        r"-?\d+\.\d{3}m Clip (Min|Max)\.png"
    )


def nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a non-negative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return number


def smokeview_file(value: str) -> Path:
    path = Path(value).expanduser()
    if path.suffix.lower() != ".smv":
        path = path.with_suffix(".smv")
    path = path.resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"Smokeview file does not exist: {path}")
    return path


def executable_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise argparse.ArgumentTypeError(f"Smokeview executable is not executable: {path}")
    return path


def render_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)[xX](\d+)", value)
    if match is None or int(match.group(1)) <= 0 or int(match.group(2)) <= 0:
        raise argparse.ArgumentTypeError("render size must be WIDTHxHEIGHT")
    return int(match.group(1)), int(match.group(2))


def display_size() -> tuple[int, int] | None:
    commands = (
        (["xrandr", "--current"], r"current\s+(\d+)\s+x\s+(\d+)"),
        (["xdpyinfo"], r"dimensions:\s+(\d+)x(\d+)\s+pixels"),
    )
    for command, pattern in commands:
        try:
            result = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        match = re.search(pattern, result.stdout)
        if match is not None:
            return int(match.group(1)), int(match.group(2))
    return None


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError(f"capture is not a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def image_magick_command() -> list[str] | None:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "imagemagick" / "magick.exe"
        if bundled.is_file():
            os.environ["MAGICK_HOME"] = str(bundled.parent)
            return [str(bundled)]
    magick = shutil.which("magick")
    if magick is not None:
        return [magick]
    # Windows includes C:\Windows\System32\convert.exe, which converts disk
    # filesystems and is unrelated to ImageMagick.  Current Windows
    # ImageMagick releases provide magick.exe, so never use convert.exe there.
    if sys.platform == "win32":
        return None
    convert = shutil.which("convert")
    if convert is not None:
        return [convert]
    return None


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def discover_captures(
    output: Path, prefix: str, previous: dict[Path, tuple[int, int]]
) -> list[Capture]:
    pattern = legacy_capture_pattern(prefix)
    captures: list[Capture] = []

    for path in sorted(output.iterdir()):
        match = pattern.fullmatch(path.name)
        if match is None or not path.is_file():
            continue
        if previous.get(path) == file_signature(path):
            continue
        quantity, axis, sequence, encoded_position = match.groups()
        position_text = encoded_position.replace("p", ".")
        if position_text.startswith("m"):
            position_text = "-" + position_text[1:]
        width, height = png_size(path)
        captures.append(
            Capture(path, quantity, axis, sequence, float(position_text), width, height)
        )
    return captures


def human_capture_name(prefix: str, capture: Capture) -> str:
    return (
        f"{prefix} {capture.quantity.title()} {capture.axis.upper()} "
        f"Slice {capture.sequence} at {capture.position:.3f}m Clip Max.png"
    )


def is_white_component(colour: str) -> bool:
    compact = colour.replace(" ", "").lower()
    return (
        "255,255,255" in compact
        or "gray(255)" in compact
        or "grey(255)" in compact
        or "#ffffff" in compact
    )


def detect_model_bounds(
    capture: Capture, convert_command: list[str]
) -> tuple[int, int, int, int] | None:
    command = convert_command + [
        str(capture.path),
        "-fuzz", "2%",
        "-fill", "black", "-opaque", "white",
        "-fill", "white", "+opaque", "black",
        "-define", "connected-components:verbose=true",
        "-connected-components", "8",
        "null:",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None

    image_area = capture.width * capture.height
    minimum_area = max(100.0, image_area * 0.00005)
    confidence_area = max(1000.0, image_area * 0.001)
    components: list[tuple[int, int, int, int, float]] = []
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        match = COMPONENT_PATTERN.match(line)
        if match is None:
            continue
        component_width = int(match.group(1))
        component_height = int(match.group(2))
        x = int(match.group(3))
        y = int(match.group(4))
        area = float(match.group(5))
        if not is_white_component(match.group(6)) or area < minimum_area:
            continue
        if x >= 0.94 * capture.width or y >= 0.95 * capture.height:
            continue
        components.append(
            (x, y, x + component_width, y + component_height, area)
        )

    if not components or max(component[4] for component in components) < confidence_area:
        return None
    xmin = min(component[0] for component in components)
    ymin = min(component[1] for component in components)
    xmax = max(component[2] for component in components)
    ymax = max(component[3] for component in components)
    box_width = xmax - xmin
    box_height = ymax - ymin
    centre_x = (xmin + xmax) / 2.0
    centre_y = (ymin + ymax) / 2.0
    if box_width < 0.02 * capture.width or box_height < 0.02 * capture.height:
        return None
    if box_width > 0.90 * capture.width or box_height > 0.96 * capture.height:
        return None
    if not (0.15 * capture.width <= centre_x <= 0.85 * capture.width):
        return None
    if not (0.05 * capture.height <= centre_y <= 0.95 * capture.height):
        return None
    return xmin, ymin, xmax, ymax


def crop_capture(
    capture: Capture,
    crop_box: tuple[int, int, int, int],
    padding: int,
    convert_command: list[str],
) -> bool:
    xmin, ymin, xmax, ymax = crop_box
    safety = 4
    xmin = max(0, xmin - safety)
    ymin = max(0, ymin - safety)
    xmax = min(capture.width, xmax + safety)
    ymax = min(capture.height, ymax + safety)
    crop_width = xmax - xmin
    crop_height = ymax - ymin
    if crop_width <= 0 or crop_height <= 0:
        return False

    with tempfile.NamedTemporaryFile(
        dir=capture.path.parent,
        prefix=".smv_crop_",
        suffix=".png",
        delete=False,
    ) as stream:
        cropped_path = Path(stream.name)
    command = convert_command + [
        str(capture.path),
        "-crop", f"{crop_width}x{crop_height}+{xmin}+{ymin}",
        "+repage",
    ]
    if padding > 0:
        command.extend(["-bordercolor", "white", "-border", f"{padding}x{padding}"])
    command.append(str(cropped_path))
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return False
        os.replace(cropped_path, capture.path)
        return True
    finally:
        cropped_path.unlink(missing_ok=True)


def crop_captures(
    captures: list[Capture], padding: int, convert_command: list[str]
) -> None:
    for capture in captures:
        capture.model_bounds = detect_model_bounds(capture, convert_command)
        if capture.model_bounds is None:
            print(
                f"capture_result_slices: warning: model bounds were not detected in "
                f"{capture.path.name}; leaving it uncropped",
                file=sys.stderr,
            )

    for axis in "xyz":
        detected = [
            capture
            for capture in captures
            if capture.axis == axis and capture.model_bounds is not None
        ]
        if not detected:
            continue
        dimensions = {(capture.width, capture.height) for capture in detected}
        if len(dimensions) != 1:
            print(
                f"capture_result_slices: warning: {axis.upper()} captures have different "
                "source dimensions; leaving that axis uncropped",
                file=sys.stderr,
            )
            continue
        bounds = [capture.model_bounds for capture in detected]
        axis_box = (
            min(bound[0] for bound in bounds),
            min(bound[1] for bound in bounds),
            max(bound[2] for bound in bounds),
            max(bound[3] for bound in bounds),
        )
        cropped = 0
        final_size: tuple[int, int] | None = None
        for capture in detected:
            if crop_capture(capture, axis_box, padding, convert_command):
                cropped += 1
                final_size = png_size(capture.path)
            else:
                print(
                    f"capture_result_slices: warning: unable to crop {capture.path.name}; "
                    "leaving it unchanged",
                    file=sys.stderr,
                )
        if cropped > 0 and final_size is not None:
            print(
                f"Cropped {cropped} {axis.upper()} capture"
                f"{'s' if cropped != 1 else ''} to {final_size[0]}x{final_size[1]}"
            )


def rename_captures(captures: list[Capture], prefix: str) -> None:
    destinations = [capture.path.with_name(human_capture_name(prefix, capture)) for capture in captures]
    if len(set(destinations)) != len(destinations):
        raise RuntimeError("two result captures resolve to the same output filename")
    for capture, destination in zip(captures, destinations):
        if destination.exists() and destination != capture.path:
            raise RuntimeError(f"capture already exists: {destination}; use --overwrite")
    for capture, destination in zip(captures, destinations):
        capture.path.rename(destination)
        capture.path = destination


def supports_result_capture(executable: Path) -> bool:
    keywords = (b"SMV_FEATURE_RENDERRESULTS_1", b"RENDERFULLSCREEN")
    overlap = b""
    with executable.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = overlap + chunk
            keywords = tuple(keyword for keyword in keywords if keyword not in data)
            if not keywords:
                return True
            overlap = data[-64:]
    return not keywords


def find_smokeview(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().with_name("smokeview.exe"))
    script_dir = Path(__file__).resolve().parent
    for executable_name in ("smokeview", "smokeview_linux", "smokeview.exe"):
        candidates.append(script_dir / executable_name)

    repo_root = script_dir.parents[1]
    candidates.append(repo_root / "cbuild" / "review" / "smokeview")
    candidates.extend((repo_root / "Build" / "smokeview").glob("*/smokeview_*"))

    env_smv = os.environ.get("SMV")
    if env_smv:
        candidates.append(Path(env_smv).expanduser())
    for command in ("smokeview", "smokeview_linux"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))

    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        "Smokeview was not found. Place it beside this script, pass --smokeview EXE, "
        "set SMV, build this checkout, or add smokeview to PATH."
    )


def check_dependencies(smokeview: Path, crop_enabled: bool) -> list[str] | None:
    def report(message: str) -> None:
        print(message, flush=True)

    report("Dependency check:")
    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"Python 3.10 or newer is required; found "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}."
        )
    report(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    if sys.platform.startswith("linux"):
        display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        if not display:
            raise RuntimeError(
                "no graphical desktop session was detected; set DISPLAY/WAYLAND_DISPLAY "
                "or run the script from a desktop terminal"
            )
        report(f"  [OK] Graphical display: {display}")

    if not supports_result_capture(smokeview):
        raise RuntimeError(
            f"{smokeview} does not support RENDERRESULTS and RENDERFULLSCREEN. "
            "Build Smokeview from this checkout or pass that executable with --smokeview."
        )
    report(f"  [OK] Smokeview capture support: {smokeview}")

    convert_command = image_magick_command()
    if crop_enabled:
        if convert_command is None:
            if sys.platform == "win32":
                raise RuntimeError(
                    "ImageMagick is required for model cropping. Install ImageMagick "
                    "so 'magick.exe' is on PATH, or use --no-crop. The Windows system "
                    "'convert.exe' command is not ImageMagick."
                )
            raise RuntimeError(
                "ImageMagick is required for model cropping. Install ImageMagick so "
                "'magick' or 'convert' is on PATH, or use --no-crop."
            )
        try:
            result = subprocess.run(
                convert_command + ["-version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"unable to run ImageMagick: {error}") from error
        if result.returncode != 0:
            raise RuntimeError(
                f"ImageMagick dependency check failed: {' '.join(convert_command)} -version"
            )
        version = (result.stdout or result.stderr).splitlines()
        version_label = version[0].strip() if version else convert_command[0]
        report(f"  [OK] {version_label}")
    else:
        report("  [SKIP] ImageMagick cropping disabled by --no-crop")

    resolution_probe = shutil.which("xrandr") or shutil.which("xdpyinfo")
    if resolution_probe is None:
        report("  [OPTIONAL] xrandr/xdpyinfo not found; display-size fallback will be used")
    else:
        report(f"  [OK] Display-size probe: {resolution_probe}")
    return convert_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open a .smv case and save a PNG for every configured visibility, "
            "temperature, velocity and pressure review slice."
        )
    )
    parser.add_argument("case", type=smokeview_file, help="case .smv file (extension optional)")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="output directory (default: CASE_slice_captures beside the .smv file)",
    )
    parser.add_argument(
        "-e", "--smokeview", type=executable_file,
        help=(
            "Smokeview executable (otherwise use a sibling executable, this repository's "
            "build, SMV, or PATH)"
        ),
    )
    parser.add_argument("--prefix", help="output filename prefix (default: case name)")
    parser.add_argument(
        "--quantities", nargs="+", choices=QUANTITIES, metavar="QUANTITY",
        help="capture only selected quantities: visibility temperature velocity pressure",
    )
    parser.add_argument(
        "--size", type=render_size, metavar="WIDTHxHEIGHT",
        help="capture dimensions (default: current display resolution)",
    )
    parser.add_argument(
        "--time", type=float, default=150.0,
        help="simulation time to capture (default: 150 s; nearest available frame is used)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace captures that already exist"
    )
    parser.add_argument(
        "--crop-padding", type=nonnegative_int, default=20, metavar="PIXELS",
        help="white border around cropped models (default: 20 pixels)",
    )
    parser.add_argument(
        "--no-crop", action="store_true",
        help="keep full-size captures while still applying human-readable filenames",
    )
    parser.add_argument(
        "--keep-script", action="store_true", help="retain the generated .ssf file in the output directory"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case: Path = args.case
    output = (args.output or case.with_name(f"{case.stem}_slice_captures")).expanduser().resolve()
    prefix = args.prefix or case.stem
    fullscreen = args.size is None
    width, height = args.size or display_size() or (1920, 1080)
    if "\n" in prefix or "\r" in prefix:
        raise RuntimeError("The filename prefix must be one line")
    if "\n" in str(output) or "\r" in str(output) or "#" in str(output):
        raise RuntimeError("The output path cannot contain a newline or '#' character")

    smokeview = find_smokeview(args.smokeview)
    convert_command = check_dependencies(smokeview, crop_enabled=not args.no_crop)
    output.mkdir(parents=True, exist_ok=True)
    legacy_pattern = legacy_capture_pattern(prefix)
    human_pattern = human_capture_pattern(prefix)
    if args.overwrite:
        for path in output.iterdir():
            if path.is_file() and (
                legacy_pattern.fullmatch(path.name) is not None
                or human_pattern.fullmatch(path.name) is not None
            ):
                path.unlink()
    else:
        existing_human = [
            path for path in output.iterdir()
            if path.is_file() and human_pattern.fullmatch(path.name) is not None
        ]
        if existing_human:
            raise RuntimeError(
                f"capture already exists: {existing_human[0]}; use --overwrite"
            )
    previous_captures = {
        path: file_signature(path)
        for path in output.iterdir()
        if path.is_file() and legacy_pattern.fullmatch(path.name) is not None
    }
    script_text = (
        ("RENDERFULLSCREEN\n" if fullscreen else "")
        + "RENDERSIZE\n"
        + (" 0 0\n" if fullscreen else f" {width} {height}\n")
        + "RENDERTYPE\n"
        " PNG\n"
        "PROJECTION\n"
        " 2\n"
        "RENDERDIR\n"
        f" {output}{os.sep}\n"
        "RENDERRESULTS\n"
        f" {prefix}\n"
        f" {args.time:.9g}\n"
    )

    script_path: Path
    remove_script = not args.keep_script
    if args.keep_script:
        script_path = output / f"{case.stem}_capture_results.ssf"
        script_path.write_text(script_text, encoding="utf-8")
    else:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".ssf", prefix="smv_capture_", delete=False
        ) as stream:
            stream.write(script_text)
            script_path = Path(stream.name)

    command = [str(smokeview)]
    if args.overwrite:
        command.append("-render_overwrite")
    command.extend(["-script", str(script_path), case.name])
    print(f"Capturing result slices from {case} at t={args.time:g} s")
    print(f"Writing PNG files to {output}")
    print(f"Capture size: {width}x{height}")
    print(f"Using Smokeview: {smokeview}")
    try:
        capture_env = os.environ.copy()
        if args.quantities:
            capture_env["ASHTON_CAPTURE_QUANTITIES"] = ",".join(args.quantities)
        else:
            capture_env.pop("ASHTON_CAPTURE_QUANTITIES", None)
        returncode = subprocess.run(command, cwd=case.parent, env=capture_env, check=False).returncode
        if returncode != 0:
            return returncode
        captures = discover_captures(output, prefix, previous_captures)
        if not captures:
            print(
                "capture_result_slices: warning: no new result PNG files were found",
                file=sys.stderr,
            )
            return 0
        if not args.no_crop:
            assert convert_command is not None
            crop_captures(captures, args.crop_padding, convert_command)
        rename_captures(captures, prefix)
        print(f"Finalised {len(captures)} result capture{'s' if len(captures) != 1 else ''}")
        return 0
    finally:
        if remove_script:
            script_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as error:
        print(f"capture_result_slices: {error}", file=sys.stderr)
        sys.exit(2)
