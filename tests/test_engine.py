import itertools

import pytest

from backend.engine import compute_layout, placements_to_csv
from backend.engine.geometry import normalize_rotation
from backend.models import LayerConfig, PalletParams


def params(**kw):
    layers = kw.pop("layers", None)
    p = PalletParams(**kw)
    if layers is not None:
        p.layers = [LayerConfig(**l) if isinstance(l, dict) else l for l in layers]
    return p


def assert_valid(result, p):
    """All boxes inside the borders and no two boxes closer than the gap."""
    eps = 1e-6
    for b in result.placements:
        assert b.x - b.size_x / 2 >= p.border_x - eps
        assert b.x + b.size_x / 2 <= 1200 - p.border_x + eps
        assert b.y - b.size_y / 2 >= p.border_y - eps
        assert b.y + b.size_y / 2 <= 800 - p.border_y + eps
        assert b.rotation in (-90, 0, 90, 180)
        if b.rotation in (0, 180):
            assert (b.size_x, b.size_y) == (p.box_length, p.box_width)
        else:
            assert (b.size_x, b.size_y) == (p.box_width, p.box_length)
    for a, b in itertools.combinations(result.placements, 2):
        if a.layer != b.layer:
            continue
        sep_x = abs(a.x - b.x) - (a.size_x + b.size_x) / 2
        sep_y = abs(a.y - b.y) - (a.size_y + b.size_y) / 2
        assert max(sep_x, sep_y) >= p.gap - eps, f"boxes {a.index} and {b.index} overlap"


def test_normalize_rotation():
    assert normalize_rotation(270) == -90
    assert normalize_rotation(-180) == 180
    assert normalize_rotation(450) == 90
    with pytest.raises(ValueError):
        normalize_rotation(45)


def test_column_capacity_and_coordinates():
    p = params(box_length=400, box_width=300, box_height=200, total_boxes=6, layer_count=1)
    r = compute_layout(p)
    assert r.errors == []
    assert len(r.placements) == 6
    # 3 x 2 grid of 400 x 300, centred in Y: (800 - 600) / 2 = 100 margin
    xs = sorted({b.x for b in r.placements})
    ys = sorted({b.y for b in r.placements})
    assert xs == [200, 600, 1000]
    assert ys == [250, 550]
    assert all(b.z == 200 for b in r.placements)


def test_column_rotated_90():
    p = params(box_length=400, box_width=300, total_boxes=8, layer_count=1, layers=[{"pattern": "column", "rotation": 90}])
    r = compute_layout(p)
    assert r.errors == []
    assert {b.rotation for b in r.placements} == {90}
    assert len(r.placements) == 8


def test_gap_and_border_are_respected():
    for pattern in ("column", "interlocked", "pinwheel", "optimized"):
        p = params(box_length=310, box_width=210, box_height=150, total_boxes=20, layer_count=2,
                   gap=8, border_x=15, border_y=25, layers=[{"pattern": pattern}])
        r = compute_layout(p)
        assert r.placements, pattern
        assert_valid(r, p)


def test_gap_reduces_capacity_exactly():
    # 3 x 400 = 1200 fits only without a gap
    p0 = params(box_length=400, box_width=400, total_boxes=1, layer_count=1)
    p1 = params(box_length=400, box_width=400, total_boxes=1, layer_count=1, gap=1)
    assert compute_layout(p0).layers[0].capacity == 6
    assert compute_layout(p1).layers[0].capacity == 2


def test_z_with_interlayer():
    p = params(box_height=200, interlayer_thickness=5, total_boxes=18, layer_count=3)
    r = compute_layout(p)
    assert [l.z_top for l in r.layers] == [200, 405, 610]
    assert r.interlayers == [200, 405]
    p.interlayer_bottom = True
    r = compute_layout(p)
    assert [l.z_top for l in r.layers] == [205, 410, 615]
    assert r.interlayers == [0, 205, 410]


def test_interlocked_rotates_every_other_layer():
    p = params(box_length=400, box_width=300, total_boxes=20, layer_count=3,
               layers=[{"pattern": "interlocked", "rotation": 180}])
    r = compute_layout(p)
    assert [l.rotations for l in r.layers] == [[180], [-90], [180]]
    assert_valid(r, p)


def test_pinwheel_uses_four_directions():
    p = params(box_length=310, box_width=210, total_boxes=12, layer_count=1,
               layers=[{"pattern": "pinwheel", "rotation": 0}])
    r = compute_layout(p)
    assert r.errors == []
    assert sorted({b.rotation for b in r.placements}) == [-90, 0, 90, 180]
    assert_valid(r, p)


def test_optimized_beats_or_equals_column():
    for dims in [(400, 300), (310, 210), (250, 180), (370, 230), (600, 400)]:
        base = dict(box_length=dims[0], box_width=dims[1], total_boxes=1, layer_count=1)
        best_col = max(compute_layout(params(**base, layers=[{"pattern": "column", "rotation": r}])).layers[0].capacity
                       for r in (0, 90))
        r = compute_layout(params(**base, layers=[{"pattern": "optimized"}]))
        assert r.layers[0].capacity >= best_col
    r = compute_layout(params(box_length=400, box_width=300, total_boxes=8, layer_count=1, layers=[{"pattern": "optimized"}]))
    assert r.layers[0].capacity == 8


def test_optimized_rotation_options():
    p = params(box_length=310, box_width=210, total_boxes=12, layer_count=1,
               layers=[{"pattern": "optimized", "rot_long": 180, "rot_cross": -90}])
    r = compute_layout(p)
    assert {b.rotation for b in r.placements} <= {180, -90}
    assert_valid(r, p)


def test_placement_order_far_corner_first():
    p = params(box_length=400, box_width=300, total_boxes=6, layer_count=1)
    r = compute_layout(p)
    first, last = r.placements[0], r.placements[-1]
    assert (first.x, first.y) == (1000, 550)
    assert (last.x, last.y) == (200, 250)
    # never place a box beyond an already placed one (robot at origin)
    for a, b in zip(r.placements, r.placements[1:]):
        assert (b.x < a.x) or (b.x == a.x and b.y < a.y)
    p.primary_axis = "y"
    r = compute_layout(p)
    assert [(b.x, b.y) for b in r.placements[:3]] == [(1000, 550), (600, 550), (200, 550)]


def test_mixed_patterns_never_place_behind_a_placed_box():
    from backend.engine.layout import _blocks
    for pattern in ("pinwheel", "optimized"):
        for dims in [(310, 210), (370, 230), (250, 180)]:
            p = params(box_length=dims[0], box_width=dims[1], total_boxes=1000, layer_count=1, gap=3,
                       layers=[{"pattern": pattern}])
            boxes = [vars(b) for b in compute_layout(p).placements]
            for i, earlier in enumerate(boxes):
                for later in boxes[i + 1:]:
                    assert not _blocks(earlier, later), (pattern, dims, earlier["index"], later["index"])


def test_layers_bottom_to_top_and_partial_modes():
    p = params(box_length=400, box_width=300, total_boxes=8, layer_count=2)
    r = compute_layout(p)
    assert [b.layer for b in r.placements] == [0] * 6 + [1] * 2
    assert any("partial" in w for w in r.warnings)
    centered = [(b.x, b.y) for b in r.placements if b.layer == 1]
    assert all(b == 600 for b, _ in centered)  # the two middle boxes
    p.partial_layer_mode = "start_corner"
    r = compute_layout(p)
    assert [(b.x, b.y) for b in r.placements if b.layer == 1] == [(1000, 550), (1000, 250)]


def test_too_many_boxes_is_error():
    r = compute_layout(params(box_length=400, box_width=300, total_boxes=20, layer_count=3))
    assert r.errors and "capacity is 18" in r.errors[0]


def test_box_does_not_fit_is_error():
    r = compute_layout(params(box_length=900, box_width=900, total_boxes=1, layer_count=1))
    assert r.errors


def test_layer_config_per_layer():
    p = params(box_length=400, box_width=300, total_boxes=14, layer_count=2,
               layers=[{"pattern": "column", "rotation": 0}, {"pattern": "column", "rotation": 90}])
    r = compute_layout(p)
    assert [l.capacity for l in r.layers] == [6, 8]


def test_csv_format():
    p = params(box_length=400, box_width=300, box_height=200, total_boxes=2, layer_count=1,
               partial_layer_mode="start_corner", layers=[{"pattern": "column", "rotation": -90}])
    text = placements_to_csv(compute_layout(p).placements)
    lines = text.split("\n")
    assert lines[-1] == ""  # every row ends with LF
    assert lines[0] == "1050.0,600.0,200.0,-90.0"
    assert all(len(l.split(",")) == 4 for l in lines[:-1])
    assert "\r" not in text
