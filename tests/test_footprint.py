"""
Tests for custom bin footprints: parsing the shape text, tracing its outline and offsetting it.
Plain asserts only, so they run with pytest or as a script (python tests/test_footprint.py).
"""

import sys
import os
import math
import importlib.util


def _load_footprint():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(project_root, "lib", "gridfinityUtils", "footprint.py")
    spec = importlib.util.spec_from_file_location("footprint", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["footprint"] = mod
    spec.loader.exec_module(mod)
    return mod


footprint = _load_footprint()

# Fusion internal units, cm
UNIT = 4.2
CLEARANCE = 0.025
RADIUS = 0.4 - CLEARANCE
WALL = 0.12

E_SHAPE = "###\n#..\n###\n#..\n###"


def raises(error, function, *args):
    try:
        function(*args)
    except error as err:
        return str(err)
    raise AssertionError(f'{function.__name__} did not raise {error.__name__}')


def close(a, b, tolerance=1e-6):
    return math.isclose(a, b, abs_tol=tolerance)


def totalArea(loops):
    return sum(footprint.loopArea(loop) for loop in loops)


# --- parsing -----------------------------------------------------------------------------------------------------

def test_grid_text_puts_the_first_line_on_top():
    shape = footprint.parseFootprint("##\n#.")
    assert shape.columns == 2 and shape.rows == 2
    # the top row is the one with the biggest row number
    assert shape.cells == frozenset({(0, 0), (0, 1), (1, 1)})


def test_the_upper_case_e_from_row_lengths():
    shape = footprint.parseFootprint("3,1,3,1,3")
    assert shape.cells == footprint.parseFootprint(E_SHAPE).cells
    assert shape.columns == 3 and shape.rows == 5
    assert shape.count == 11


def test_row_lengths_separated_by_spaces():
    assert footprint.parseFootprint("3 1 3 1 3").cells == footprint.parseFootprint(E_SHAPE).cells


def test_slashes_separate_rows():
    assert footprint.parseFootprint("###/#../###/#../###").cells == footprint.parseFootprint(E_SHAPE).cells


def test_zeros_and_ones_are_a_grid():
    shape = footprint.parseFootprint("11\n10")
    assert shape.cells == frozenset({(0, 0), (0, 1), (1, 1)})


def test_a_single_row_of_ones_is_one_row():
    shape = footprint.parseFootprint("111")
    assert shape.columns == 3 and shape.rows == 1


def test_whitespace_in_rows_is_ignored():
    assert footprint.parseFootprint("# # #\n# . .").cells == footprint.parseFootprint("###\n#..").cells


def test_short_rows_are_padded():
    shape = footprint.parseFootprint("###\n#\n###")
    assert shape.cells == footprint.parseFootprint("###\n#..\n###").cells


def test_empty_margins_are_trimmed():
    shape = footprint.parseFootprint("...\n.##\n.#.\n...")
    assert shape.cells == frozenset({(0, 0), (0, 1), (1, 1)})
    assert shape.columns == 2 and shape.rows == 2


def test_empty_text_is_rejected():
    assert 'empty' in raises(footprint.FootprintError, footprint.parseFootprint, "  \n ")
    assert 'no cells' in raises(footprint.FootprintError, footprint.parseFootprint, "...\n...")


def test_unknown_symbols_are_rejected():
    assert "'q'" in raises(footprint.FootprintError, footprint.parseFootprint, "#q#")


def test_separate_pieces_are_rejected():
    assert 'separate pieces' in raises(footprint.FootprintError, footprint.parseFootprint, "#.#")


def test_cells_touching_at_a_corner_are_rejected():
    assert 'corner' in raises(footprint.FootprintError, footprint.parseFootprint, "#.\n.#")
    # joined through another cell they would still pinch where the two meet
    assert 'corner' in raises(footprint.FootprintError, footprint.parseFootprint, "###\n#.#\n##.\n")


def test_too_big_shapes_are_rejected():
    assert 'most' in raises(footprint.FootprintError, footprint.parseFootprint, "#" * (footprint.MAX_SIZE + 1))
    assert 'most' in raises(footprint.FootprintError, footprint.parseFootprint, "/".join(["#"] * (footprint.MAX_SIZE + 1)))
    assert 'too long' in raises(footprint.FootprintError, footprint.parseFootprint, "99,1")


def test_round_trip_through_text():
    shape = footprint.parseFootprint(E_SHAPE)
    assert shape.toText() == E_SHAPE
    assert footprint.parseFootprint(shape.toText()) == shape


# --- outline -----------------------------------------------------------------------------------------------------

def test_a_rectangle_has_four_corners():
    loops = footprint.traceOutlines(footprint.parseFootprint("###\n###"))
    assert len(loops) == 1
    assert sorted(loops[0]) == [(0, 0), (0, 2), (3, 0), (3, 2)]


def test_the_e_has_twelve_corners_and_runs_counterclockwise():
    shape = footprint.parseFootprint(E_SHAPE)
    loops = footprint.traceOutlines(shape)
    assert len(loops) == 1
    assert len(loops[0]) == 12
    # the shoelace area of the corners, in cells, is the cell count
    points = loops[0]
    area = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points))) / 2
    assert area == shape.count


def test_a_ring_has_a_hole_running_the_other_way():
    shape = footprint.parseFootprint("###\n#.#\n###")
    loops = footprint.traceOutlines(shape)
    assert len(loops) == 2
    areas = []
    for points in loops:
        areas.append(sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points))) / 2)
    assert sorted(areas) == [-1, 9]


# --- offsetting --------------------------------------------------------------------------------------------------

def test_a_single_cell_matches_the_rectangular_bin_body():
    shape = footprint.parseFootprint("#")
    (loop,) = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, RADIUS, -CLEARANCE, -CLEARANCE)
    assert footprint.isClosed(loop)
    # a rectangular bin body spans 0 to the base unit less the clearance on both sides
    xs = [point[0] for segment in loop for point in segment[1:]]
    ys = [point[1] for segment in loop for point in segment[1:]]
    assert close(min(xs), 0) and close(max(xs), UNIT - CLEARANCE * 2)
    assert close(min(ys), 0) and close(max(ys), UNIT - CLEARANCE * 2)
    width = UNIT - CLEARANCE * 2
    assert close(footprint.loopArea(loop), width * width - (4 - math.pi) * RADIUS ** 2)


def test_a_rectangle_spans_the_same_as_a_rectangular_bin():
    shape = footprint.parseFootprint("##\n##\n##")
    (loop,) = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, RADIUS, -CLEARANCE, -CLEARANCE)
    xs = [point[0] for segment in loop for point in segment[1:]]
    ys = [point[1] for segment in loop for point in segment[1:]]
    assert close(max(xs), 2 * UNIT - CLEARANCE * 2)
    assert close(max(ys), 3 * UNIT - CLEARANCE * 2)
    assert footprint.outerSize(shape, UNIT, UNIT, CLEARANCE) == (2 * UNIT - CLEARANCE * 2, 3 * UNIT - CLEARANCE * 2)


def test_unequal_cell_sizes():
    shape = footprint.parseFootprint("##")
    (loop,) = footprint.outlineLoops(shape, 4.0, 5.0, 0, 0)
    assert close(footprint.loopArea(loop), 2 * 4.0 * 5.0)


def test_sharp_loops_of_the_e_have_the_expected_area():
    shape = footprint.parseFootprint(E_SHAPE)
    (loop,) = footprint.outlineLoops(shape, UNIT, UNIT, 0, 0)
    assert footprint.isClosed(loop)
    assert close(footprint.loopArea(loop), 11 * UNIT * UNIT)


def test_rounding_only_takes_the_outward_corners():
    shape = footprint.parseFootprint(E_SHAPE)
    (loop,) = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, RADIUS)
    arcs = [segment for segment in loop if segment[0] == 'arc']
    # the e has 8 outward corners and 4 inward ones, the 4 inside corners of the two gaps stay sharp
    assert len(arcs) == 8
    assert footprint.isClosed(loop)
    sharpArea = footprint.loopArea(footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, 0)[0])
    assert close(footprint.loopArea(loop), sharpArea - 8 * (1 - math.pi / 4) * RADIUS ** 2)


def test_insetting_the_e_by_the_wall_shrinks_it_by_the_wall_on_every_side():
    shape = footprint.parseFootprint(E_SHAPE)
    outer = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, 0)[0]
    inner = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE + WALL, 0)[0]
    perimeter = sum(math.hypot(s[-1][0] - s[1][0], s[-1][1] - s[1][1]) for s in outer)
    # for a rectilinear polygon moved inwards by d, the area drops by d times the perimeter, minus
    # 4 d squared for every convex corner more than concave ones (the difference is always 4)
    expectedDrop = WALL * perimeter - 4 * WALL ** 2
    assert close(footprint.loopArea(outer) - footprint.loopArea(inner), expectedDrop, 1e-6)


def test_the_cavity_arcs_run_a_wall_thickness_inside_the_outer_ones():
    shape = footprint.parseFootprint("#")
    outer = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, RADIUS)[0]
    inner = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE + WALL, RADIUS - WALL)[0]
    outerMiddles = sorted(s[2] for s in outer if s[0] == 'arc')
    innerMiddles = sorted(s[2] for s in inner if s[0] == 'arc')
    assert len(outerMiddles) == len(innerMiddles) == 4
    # arcs with the same centre are a wall thickness apart along the diagonal
    for (a, b) in zip(outerMiddles, innerMiddles):
        assert close(math.hypot(a[0] - b[0], a[1] - b[1]), WALL)


def test_a_ring_gets_an_outline_and_a_hole():
    shape = footprint.parseFootprint("###\n#.#\n###")
    loops = footprint.outlineLoops(shape, UNIT, UNIT, CLEARANCE, RADIUS)
    assert len(loops) == 2
    areas = sorted(footprint.loopArea(loop) for loop in loops)
    # the hole goes clockwise and the corners pointing into it stay sharp, the walls move away from the hole so it
    # grows by a clearance on every side
    assert close(areas[0], -(UNIT + CLEARANCE * 2) ** 2)
    assert all(footprint.isClosed(loop) for loop in loops)


def test_radius_is_cut_down_where_sides_are_short():
    shape = footprint.parseFootprint("#")
    (loop,) = footprint.outlineLoops(shape, 1.0, 1.0, 0, 10)
    # a radius of 10 on a 1 cell takes half of each side at most, the cell becomes a circle
    assert close(footprint.loopArea(loop), math.pi * 0.5 ** 2)


def test_too_thick_walls_are_reported():
    shape = footprint.parseFootprint("#")
    assert 'too thick' in raises(footprint.FootprintError, footprint.outlineLoops, shape, 1.0, 1.0, 0.5, 0)


# --- cells -------------------------------------------------------------------------------------------------------

def test_cell_index_inverts_the_cell_center():
    for index in range(8):
        center = footprint.cellCenter(index, UNIT, CLEARANCE)
        assert footprint.cellIndex(center, UNIT, CLEARANCE) == index
        # the feet and lip cutters are not exactly centered but stay inside their cell
        assert footprint.cellIndex(center + UNIT * 0.4, UNIT, CLEARANCE) == index
        assert footprint.cellIndex(center - UNIT * 0.4, UNIT, CLEARANCE) == index


if __name__ == '__main__':
    failures = 0
    tests = [(name, function) for (name, function) in sorted(globals().items()) if name.startswith('test_') and callable(function)]
    for (name, function) in tests:
        try:
            function()
            print(f'ok    {name}')
        except Exception as err:
            failures += 1
            print(f'FAIL  {name}: {type(err).__name__}: {err}')
    print(f'{len(tests) - failures} of {len(tests)} passed')
    sys.exit(1 if failures else 0)
