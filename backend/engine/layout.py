"""Builds the complete pallet: patterns per layer, Z heights, placement order, validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache

from ..models import LayerConfig, PalletParams
from . import patterns
from .geometry import EPS, PALLET_LENGTH_X, PALLET_WIDTH_Y, normalize_rotation
from .patterns import SCALE, to_um


@dataclass
class Placement:
    index: int          # 1-based placing order over the whole pallet (= CSV row)
    layer: int          # 0-based layer index
    x: float            # centre of the top face, mm
    y: float
    z: float
    rotation: int       # -90, 0, 90, 180
    size_x: float       # footprint along X, mm
    size_y: float       # footprint along Y, mm
    block: int = 0


@dataclass
class LayerInfo:
    index: int
    pattern: str
    capacity: int
    count: int
    z_top: float
    z_bottom: float
    rotations: list[int]


@dataclass
class LayoutResult:
    placements: list[Placement] = field(default_factory=list)
    layers: list[LayerInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_boxes: int = 0
    capacity: int = 0
    stack_height: float = 0.0
    interlayers: list[float] = field(default_factory=list)  # Z of the bottom of every interlayer
    usable_area: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _rotation_for(cfg: LayerConfig, cell: patterns.Cell, effective_base: int) -> int:
    if cfg.pattern in ("column", "interlocked"):
        return effective_base
    if cfg.pattern == "pinwheel":
        return normalize_rotation(effective_base + 90 * cell.block)
    return cfg.rot_long if cell.lengthwise else cfg.rot_cross  # optimized


@lru_cache(maxsize=256)
def _cells(pattern: str, ux: int, uy: int, a: int, b: int, lengthwise: bool) -> tuple[patterns.Cell, ...]:
    if pattern in ("column", "interlocked"):
        return tuple(patterns.column(ux, uy, a, b, lengthwise))
    if pattern == "pinwheel":
        return tuple(patterns.pinwheel(ux, uy, a, b, lengthwise))
    return tuple(patterns.optimized(ux, uy, a, b))


def _layer_positions(p: PalletParams, cfg: LayerConfig, layer_index: int) -> list[dict]:
    """Full-capacity positions of one layer, centred in the usable area (mm)."""
    gap = to_um(p.gap)
    usable_x = to_um(PALLET_LENGTH_X - 2 * p.border_x)
    usable_y = to_um(PALLET_WIDTH_Y - 2 * p.border_y)
    length, width = to_um(p.box_length), to_um(p.box_width)
    if usable_x <= 0 or usable_y <= 0:
        return []

    base = cfg.rotation
    if cfg.pattern == "interlocked" and layer_index % 2 == 1:
        base = normalize_rotation(base + 90)
    lengthwise = base in (0, 180)

    cells = _cells(cfg.pattern, usable_x + gap, usable_y + gap, length + gap, width + gap, lengthwise)
    if not cells:
        return []

    def size(c: patterns.Cell) -> tuple[int, int]:
        return (length, width) if c.lengthwise else (width, length)

    bbox_x = max(c.px + size(c)[0] for c in cells)
    bbox_y = max(c.py + size(c)[1] for c in cells)
    off_x = to_um(p.border_x) + (usable_x - bbox_x) / 2
    off_y = to_um(p.border_y) + (usable_y - bbox_y) / 2

    out = []
    for c in cells:
        sx, sy = size(c)
        out.append({
            "x": (off_x + c.px + sx / 2) / SCALE,
            "y": (off_y + c.py + sy / 2) / SCALE,
            "size_x": sx / SCALE,
            "size_y": sy / SCALE,
            "rotation": _rotation_for(cfg, c, base),
            "block": c.block,
        })
    return out


def _blocks(a: dict, b: dict) -> bool:
    """True if box a lies between the robot (origin corner) and box b, i.e. b must be placed first.

    a blocks b when it is completely closer to the origin along X while overlapping b in Y,
    or completely closer along Y while overlapping in X.
    """
    ax0, ax1 = a["x"] - a["size_x"] / 2, a["x"] + a["size_x"] / 2
    ay0, ay1 = a["y"] - a["size_y"] / 2, a["y"] + a["size_y"] / 2
    bx0, bx1 = b["x"] - b["size_x"] / 2, b["x"] + b["size_x"] / 2
    by0, by1 = b["y"] - b["size_y"] / 2, b["y"] + b["size_y"] / 2
    overlap_x = min(ax1, bx1) - max(ax0, bx0) > EPS
    overlap_y = min(ay1, by1) - max(ay0, by0) > EPS
    return (ax1 <= bx0 + EPS and overlap_y) or (ay1 <= by0 + EPS and overlap_x)


def _order(positions: list[dict], primary_axis: str) -> list[dict]:
    """Robot stands at the origin corner: fill from the far corner (max X, max Y) towards it.

    A box is placed only after every box that lies behind it (seen from the robot). Among the
    boxes that are free to be placed, the one farthest along the primary axis goes first.
    """

    def key(pos: dict):
        near_x = round(pos["x"] - pos["size_x"] / 2, 3)
        near_y = round(pos["y"] - pos["size_y"] / 2, 3)
        return (-near_x, -near_y) if primary_axis == "x" else (-near_y, -near_x)

    remaining = sorted(positions, key=key)
    # waiting[i] = number of unplaced boxes that must be placed before box i
    waiting = [sum(1 for j, b in enumerate(remaining) if j != i and _blocks(a, b))
               for i, a in enumerate(remaining)]
    placed = [False] * len(remaining)
    out = []
    for _ in range(len(remaining)):
        free = [i for i in range(len(remaining)) if not placed[i] and waiting[i] == 0]
        # a cycle cannot happen for most layouts; if it does, fall back to the sort order
        i = free[0] if free else next(i for i in range(len(remaining)) if not placed[i])
        placed[i] = True
        out.append(remaining[i])
        for k, a in enumerate(remaining):
            if not placed[k] and _blocks(a, remaining[i]):
                waiting[k] -= 1
    return out


def _select_partial(ordered: list[dict], count: int, mode: str, p: PalletParams) -> list[dict]:
    if count >= len(ordered):
        return ordered
    if mode == "start_corner":
        return ordered[:count]
    cx = PALLET_LENGTH_X / 2
    cy = PALLET_WIDTH_Y / 2
    ranked = sorted(range(len(ordered)),
                    key=lambda i: (round((ordered[i]["x"] - cx) ** 2 + (ordered[i]["y"] - cy) ** 2, 3), i))
    chosen = sorted(ranked[:count])
    return [ordered[i] for i in chosen]


def compute_layout(p: PalletParams) -> LayoutResult:
    res = LayoutResult(usable_area={
        "x_min": p.border_x, "x_max": PALLET_LENGTH_X - p.border_x,
        "y_min": p.border_y, "y_max": PALLET_WIDTH_Y - p.border_y,
    })
    if p.border_x * 2 >= PALLET_LENGTH_X - EPS or p.border_y * 2 >= PALLET_WIDTH_Y - EPS:
        res.errors.append("The borders leave no usable area on the pallet.")
        return res

    remaining = p.total_boxes
    t = p.interlayer_thickness
    index = 0
    layer_cache: dict[tuple, list[dict]] = {}  # identical layers are computed only once
    for li in range(p.layer_count):
        cfg = p.layer_config(li)
        z_bottom = li * p.box_height + (li + (1 if p.interlayer_bottom else 0)) * t
        z_top = z_bottom + p.box_height
        cache_key = (cfg.model_dump_json(), li % 2 if cfg.pattern == "interlocked" else 0)
        if cache_key not in layer_cache:
            layer_cache[cache_key] = _order(_layer_positions(p, cfg, li), p.primary_axis)
        full = layer_cache[cache_key]
        capacity = len(full)
        res.capacity += capacity
        if capacity == 0:
            res.errors.append(f"Layer {li + 1}: the box does not fit on the pallet with the "
                              f"'{cfg.pattern}' pattern and the given borders.")
        count = min(capacity, max(remaining, 0))
        chosen = _select_partial(full, count, p.partial_layer_mode, p)
        remaining -= count

        if 0 < count < capacity:
            res.warnings.append(f"Layer {li + 1} is a partial layer: {count} of {capacity} boxes "
                                f"({'centered' if p.partial_layer_mode == 'centered' else 'packed from start corner'}).")
        if count == 0 and capacity > 0:
            res.warnings.append(f"Layer {li + 1} is empty, the total number of boxes is already reached.")

        if count > 0:
            interlayer_z = z_bottom - t
            if t > 0 and (li > 0 or p.interlayer_bottom):
                res.interlayers.append(round(interlayer_z, 3))
            res.stack_height = z_top

        for pos in chosen:
            index += 1
            res.placements.append(Placement(
                index=index, layer=li, x=pos["x"], y=pos["y"], z=z_top, rotation=pos["rotation"],
                size_x=pos["size_x"], size_y=pos["size_y"], block=pos["block"],
            ))
        res.layers.append(LayerInfo(
            index=li, pattern=cfg.pattern, capacity=capacity, count=count,
            z_top=z_top, z_bottom=z_bottom,
            rotations=sorted({pos["rotation"] for pos in full}),
        ))

    res.total_boxes = len(res.placements)
    if remaining > 0:
        res.errors.append(f"{p.total_boxes} boxes do not fit in {p.layer_count} layer(s): the capacity is "
                          f"{res.capacity}. Add layers, change the pattern or reduce the number of boxes.")
    return res
