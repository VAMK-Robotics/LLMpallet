"""CSV export: one row per box, `X,Y,Z,R` with one decimal, first placed box first."""

from __future__ import annotations

from collections.abc import Iterable

from .layout import Placement


def _fmt(value: float) -> str:
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def placements_to_csv(placements: Iterable[Placement]) -> str:
    rows = [",".join(_fmt(v) for v in (p.x, p.y, p.z, float(p.rotation)))
            for p in sorted(placements, key=lambda p: p.index)]
    return "".join(row + "\n" for row in rows)
