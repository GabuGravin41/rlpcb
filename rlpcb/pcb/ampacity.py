"""Track current capacity (IPC-2221 charts as the usual closed-form fit).

    I = k · ΔT^0.44 · A^0.725       A in mil², ΔT in °C, k = 0.048 (outer layers), 0.024 (inner layers)

The fit is conservative for short tracks and for boards with planes nearby (they spread heat); IPC-2152 gives larger
currents in those cases. It is the rule most design guides and fab calculators still use, so the numbers here match
what an engineer gets from a calculator.
"""
from __future__ import annotations

MIL = 0.0254                 # mm
OZ_UM = 34.79                # 1 oz/ft² copper thickness in µm


def _area_mil2(width_mm: float, oz: float) -> float:
    return (width_mm / MIL) * (oz * OZ_UM / 25.4)


def current_for(width_mm: float, dT: float = 10.0, oz: float = 1.0, inner: bool = False) -> float:
    k = 0.024 if inner else 0.048
    return k * dT ** 0.44 * _area_mil2(width_mm, oz) ** 0.725


def width_for(current_a: float, dT: float = 10.0, oz: float = 1.0, inner: bool = False) -> float:
    """Track width (mm) that carries current_a with a temperature rise of dT."""
    k = 0.024 if inner else 0.048
    area = (current_a / (k * dT ** 0.44)) ** (1 / 0.725)
    return area / (oz * OZ_UM / 25.4) * MIL


def rise_for(current_a: float, width_mm: float, oz: float = 1.0, inner: bool = False) -> float:
    """Temperature rise (°C) of a track of width_mm carrying current_a."""
    k = 0.024 if inner else 0.048
    return (current_a / (k * _area_mil2(width_mm, oz) ** 0.725)) ** (1 / 0.44)
