"""Read planar slice coordinates from an FDS Smokeview case file."""

from __future__ import annotations

import math
from pathlib import Path
import re


PLANE_TOKEN = re.compile(r"^([xyzXYZ])\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$")


def parse_plane_selection(value: str) -> str:
    """Validate and normalise a comma-separated list such as Y=3, Y=5."""
    if not value.strip():
        return ""
    tokens: list[str] = []
    for part in value.split(","):
        match = PLANE_TOKEN.fullmatch(part.strip())
        if match is None:
            raise ValueError("Enter slice positions as X=1, Y=3, Y=5 (metres).")
        position = float(match.group(2))
        if not math.isfinite(position):
            raise ValueError("Slice positions must be finite numbers.")
        token = f"{match.group(1).lower()}={position:.3f}"
        if token not in tokens:
            tokens.append(token)
    return ",".join(tokens)


def available_planes(case: Path) -> list[str]:
    """List the axis and position of 2D SLCF/SLCC/SLFC records in a .smv file."""
    lines = case.read_text(encoding="utf-8", errors="replace").splitlines()
    mesh_coordinates: dict[int, dict[str, dict[int, float]]] = {}
    mesh_sizes: dict[int, tuple[int, int, int]] = {}
    mesh_number = 0
    found: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        keyword = line.split(maxsplit=1)[0] if line else ""
        if keyword == "GRID" and index + 1 < len(lines):
            mesh_number += 1
            sizes = lines[index + 1].split()
            if len(sizes) >= 3:
                mesh_sizes[mesh_number] = tuple(int(part) for part in sizes[:3])
                mesh_coordinates[mesh_number] = {}
        elif keyword in ("TRNX", "TRNY", "TRNZ") and mesh_number in mesh_sizes:
            axis = keyword[-1].lower()
            count = mesh_sizes[mesh_number]["xyz".index(axis)]
            coordinates: dict[int, float] = {}
            for row in lines[index + 2:index + 3 + count]:
                parts = row.split()
                if len(parts) >= 2:
                    coordinates[int(parts[0])] = float(parts[1])
            mesh_coordinates[mesh_number][axis] = coordinates
        elif keyword in ("SLCF", "SLCC", "SLFC") and "&" in line:
            mesh_match = re.match(r"^\w+\s+(\d+)", line)
            section = line.split("&", 1)[1].split("!", 1)[0].split()
            if mesh_match is not None and len(section) >= 6:
                mesh = mesh_coordinates.get(int(mesh_match.group(1)), {})
                bounds = [int(part) for part in section[:6]]
                fixed = [axis for offset, axis in enumerate("xyz") if bounds[2 * offset] == bounds[2 * offset + 1]]
                if len(fixed) == 1:
                    axis = fixed[0]
                    coordinate_index = bounds[2 * "xyz".index(axis)]
                    coordinate = mesh.get(axis, {}).get(coordinate_index)
                    if coordinate is not None:
                        if keyword == "SLCC":
                            previous = mesh[axis].get(max(0, coordinate_index - 1), coordinate)
                            coordinate = (coordinate + previous) / 2
                        found.add(f"{axis.upper()}={coordinate:.3f}")
        index += 1
    return sorted(found, key=lambda token: ("xyz".index(token[0].lower()), float(token[2:])))
