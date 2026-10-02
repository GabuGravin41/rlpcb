"""Coordinate helpers shared by schematic and board code."""
from __future__ import annotations

import math

SCH_GRID = 1.27  # mm (50 mil): KiCad's default schematic connection grid
IU = 10000  # 1e-4 mm resolution used as integer keys (KiCad sch internal unit is 100 nm)


def key(x: float, y: float):
    return (int(round(x * IU)), int(round(y * IU)))


def snap(v: float, grid: float = SCH_GRID) -> float:
    return round(round(v / grid) * grid, 4)


def sym_transform(px: float, py: float, angle: float, mirror: str | None):
    """Map a library-space point (Y up) to schematic-space offset (Y down).

    KiCad composes: flip Y (library -> sheet), rotate by the symbol angle
    (counter-clockwise as seen on screen), then apply mirror about the
    symbol's own axis. Verified against kicad-cli netlist export for all
    8 orientations (see tests/test_connectivity.py).
    """
    x, y = px, -py
    a = int(round(angle)) % 360
    # Rotation CCW on screen with Y pointing down.
    if a == 90:
        x, y = y, -x
    elif a == 180:
        x, y = -x, -y
    elif a == 270:
        x, y = -y, x
    elif a != 0:
        r = math.radians(a)
        x, y = x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)
    if mirror == "x":  # mirror about X axis -> flip vertically
        y = -y
    elif mirror == "y":  # mirror about Y axis -> flip horizontally
        x = -x
    return x, y


def point_on_segment(p, a, b, tol: int = 5) -> bool:
    """Integer-keyed test that p lies on the segment a-b (inclusive)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if px < min(ax, bx) - tol or px > max(ax, bx) + tol or py < min(ay, by) - tol or py > max(ay, by) + tol:
        return False
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    length = math.hypot(bx - ax, by - ay) or 1.0
    return abs(cross) / length <= tol


def rotate_pt(x, y, angle_deg):
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return x * c - y * s, x * s + y * c
