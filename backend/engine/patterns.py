"""Layer pattern generators.

All generators work in integer micrometres in an "inflated" space. Each box footprint is grown by
the gap, and the usable area is grown by one gap. A box is then a rectangle of size (a, b) or (b, a),
and boxes touch each other without gaps. The real box occupies [px, px + size - gap] on each axis.

A generator returns a list of Cell(px, py, lengthwise, block):
  lengthwise = True  -> box length along X (rotation 0 / 180)
  lengthwise = False -> box length along Y (rotation 90 / -90)
  block      = index of the sub-block (used by the pinwheel to assign rotations)
"""

from __future__ import annotations

import bisect
import sys
from dataclasses import dataclass
from functools import lru_cache

SCALE = 1000  # mm -> um


def to_um(value_mm: float) -> int:
    return int(round(value_mm * SCALE))


@dataclass(frozen=True)
class Cell:
    px: int
    py: int
    lengthwise: bool
    block: int = 0


def _grid(x0: int, y0: int, nx: int, ny: int, fx: int, fy: int, lengthwise: bool, block: int) -> list[Cell]:
    return [Cell(x0 + i * fx, y0 + j * fy, lengthwise, block) for i in range(nx) for j in range(ny)]


# --------------------------------------------------------------------------- column / interlocked

def column(ux: int, uy: int, a: int, b: int, lengthwise: bool) -> list[Cell]:
    """Uniform grid. a = inflated box length, b = inflated box width."""
    fx, fy = (a, b) if lengthwise else (b, a)
    return _grid(0, 0, ux // fx, uy // fy, fx, fy, lengthwise, 0)


# --------------------------------------------------------------------------- pinwheel

def pinwheel(ux: int, uy: int, a: int, b: int, first_lengthwise: bool) -> list[Cell]:
    """Four point-symmetric blocks around the centre, block k is rotated k * 90 deg.

    Block 0: corner (0, 0),  footprint (p, q),  n1x * n1y boxes, size A x B
    Block 1: corner (+X, 0), footprint (q, p),  n2x * n2y boxes, size C x D
    Block 2: corner (+X,+Y), same as block 0 (point symmetric)
    Block 3: corner (0, +Y), same as block 1
    Total size (A + C) x (B + D); possible hole in the middle of size |A-C| x |B-D|.
    Returns [] if no pinwheel with four non-empty blocks fits.
    """
    p, q = (a, b) if first_lengthwise else (b, a)
    best = None  # (count, -hole, n1x, n1y, n2x, n2y)
    for n1x in range(1, ux // p + 1):
        big_a = n1x * p
        for n1y in range(1, uy // q + 1):
            big_b = n1y * q
            for n2x in range(1, (ux - big_a) // q + 1):
                big_c = n2x * q
                max_n2y = (uy - big_b) // p
                if big_c > big_a:  # blocks 1 and 3 overlap in X -> must not overlap in Y: D <= B
                    max_n2y = min(max_n2y, big_b // p)
                elif big_c < big_a:  # blocks 0 and 2 overlap in X -> need D >= B
                    if max_n2y * p < big_b:
                        continue
                if max_n2y < 1:
                    continue
                big_d = max_n2y * p
                count = 2 * (n1x * n1y + n2x * max_n2y)
                hole = abs(big_a - big_c) * abs(big_b - big_d)
                key = (count, -hole, n1x, n1y, n2x, max_n2y)
                if best is None or key[:2] > best[:2]:
                    best = key
    if best is None:
        return []
    _, _, n1x, n1y, n2x, n2y = best
    big_a, big_b, big_c, big_d = n1x * p, n1y * q, n2x * q, n2y * p
    w, h = big_a + big_c, big_b + big_d
    cells = []
    cells += _grid(0, 0, n1x, n1y, p, q, first_lengthwise, 0)
    cells += _grid(w - big_c, 0, n2x, n2y, q, p, not first_lengthwise, 1)
    cells += _grid(w - big_a, h - big_b, n1x, n1y, p, q, first_lengthwise, 2)
    cells += _grid(0, h - big_d, n2x, n2y, q, p, not first_lengthwise, 3)
    return cells


# --------------------------------------------------------------------------- optimized ("tetris")

_MAX_DP_STATES = 60_000


def _normal_points(limit: int, a: int, b: int) -> list[int]:
    pts = set()
    for i in range(limit // a + 1):
        base = i * a
        for j in range((limit - base) // b + 1):
            pts.add(base + j * b)
    return sorted(pts)


def guillotine(ux: int, uy: int, a: int, b: int) -> list[Cell]:
    """Recursive guillotine packing (dynamic programming over normal patterns)."""
    xs = _normal_points(ux, a, b)
    ys = _normal_points(uy, a, b)
    if len(xs) * len(ys) > _MAX_DP_STATES:
        # Extremely small boxes compared to the pallet: a uniform grid is practically optimal.
        c1, c2 = column(ux, uy, a, b, True), column(ux, uy, a, b, False)
        return c1 if len(c1) >= len(c2) else c2

    def snap(v: int, pts: list[int]) -> int:
        return pts[bisect.bisect_right(pts, v) - 1]

    plan: dict[tuple[int, int], tuple] = {}

    @lru_cache(maxsize=None)
    def best(x: int, y: int) -> int:
        n_long = (x // a) * (y // b)
        n_cross = (x // b) * (y // a)
        value, choice = (n_long, ("H", True)) if n_long >= n_cross else (n_cross, ("H", False))
        for x1 in xs:
            if x1 == 0:
                continue
            if 2 * x1 > x:
                break
            v = best(x1, y) + best(snap(x - x1, xs), y)
            if v > value:
                value, choice = v, ("X", x1)
        for y1 in ys:
            if y1 == 0:
                continue
            if 2 * y1 > y:
                break
            v = best(x, y1) + best(x, snap(y - y1, ys))
            if v > value:
                value, choice = v, ("Y", y1)
        plan[(x, y)] = choice
        return value

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 20_000))
    try:
        best(snap(ux, xs), snap(uy, ys))
    finally:
        sys.setrecursionlimit(old_limit)

    cells: list[Cell] = []
    stack = [(snap(ux, xs), snap(uy, ys), 0, 0)]
    while stack:
        x, y, ox, oy = stack.pop()
        kind, arg = plan[(x, y)]
        if kind == "H":
            fx, fy = (a, b) if arg else (b, a)
            cells += _grid(ox, oy, x // fx, y // fy, fx, fy, arg, 0)
        elif kind == "X":
            stack.append((arg, y, ox, oy))
            stack.append((snap(x - arg, xs), y, ox + arg, oy))
        else:
            stack.append((x, arg, ox, oy))
            stack.append((x, snap(y - arg, ys), ox, oy + arg))
    return cells


def optimized_candidates(ux: int, uy: int, a: int, b: int) -> list[list[Cell]]:
    """Candidate layouts for the optimized pattern, most boxes first (guillotine first on ties).

    Plain columns in both orientations are included too: when the layer below limits the allowed
    overhang, a less dense layout may carry more boxes.
    """
    candidates = [guillotine(ux, uy, a, b), pinwheel(ux, uy, a, b, True), pinwheel(ux, uy, a, b, False),
                  column(ux, uy, a, b, True), column(ux, uy, a, b, False)]
    unique: list[list[Cell]] = []
    for c in candidates:
        if c and all(set(c) != set(u) for u in unique):
            unique.append(c)
    unique.sort(key=len, reverse=True)  # stable sort keeps the guillotine first on ties
    return unique


def optimized(ux: int, uy: int, a: int, b: int) -> list[Cell]:
    """Layout with the most boxes."""
    cands = optimized_candidates(ux, uy, a, b)
    return cands[0] if cands else []
