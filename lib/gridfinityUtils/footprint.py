"""
Custom bin footprints: a shape made of base cells, parsed from text and turned into outlines for the generators.

Nothing here talks to Fusion, so it can be tested on its own. Lengths are in Fusion internal units, cm.

Text format, one row per line, the top row first (the top of the text is the +Y side of the bin):

    ###        '#' is a cell, '.' is an empty spot
    #..
    ###
    #..
    ###

Rows can also be separated with '/', so a single line input works too: ###/#../###/#../###
Or just give the number of cells in each row, left aligned: 3,1,3,1,3
"""
import math
import re
from dataclasses import dataclass

# generating more than this many cells in either direction would take Fusion forever
MAX_SIZE = 30

FILLED_CHARACTERS = '#xX1*'
EMPTY_CHARACTERS = '.0_-'

Point = tuple[float, float]
# ('line', start, end) or ('arc', start, middle, end), a loop is a closed chain of these, each starting where the last ends
Segment = tuple
Loop = list[Segment]

class FootprintError(ValueError):
    """The text can't be turned into a footprint, the message tells the user why"""
    pass

@dataclass(frozen=True)
class Footprint:
    # (column, row) of every cell, column 0 is the left most, row 0 the bottom (smallest Y) one
    cells: frozenset[tuple[int, int]]
    columns: int
    rows: int

    def has(self, column: int, row: int) -> bool:
        return (column, row) in self.cells

    @property
    def count(self) -> int:
        return len(self.cells)

    def toText(self) -> str:
        """Canonical text of the footprint, the top row first"""
        return '\n'.join(
            ''.join('#' if self.has(column, row) else '.' for column in range(self.columns))
            for row in range(self.rows - 1, -1, -1)
        )

def _isRowLengthsText(text: str) -> bool:
    """Numbers only, like 3,1,3,1,3. Plain 0 and 1 without any separator but whitespace is a grid, like 101/111"""
    if re.fullmatch(r'[\d\s,;/]+', text) is None:
        return False
    if re.search(r'[,;]', text) is not None:
        return True
    return re.search(r'[2-9]', text) is not None

def _gridFromRowLengths(text: str) -> list[list[bool]]:
    tokens = [token for token in re.split(r'[\s,;/]+', text) if token != '']
    rows = []
    for token in tokens:
        length = int(token)
        if length > MAX_SIZE:
            raise FootprintError(f'A row of {length} cells is too long, {MAX_SIZE} is the most')
        rows.append([True] * length)
    return rows

def _gridFromSymbols(text: str) -> list[list[bool]]:
    rows = []
    for line in re.split(r'[\r\n/|]+', text):
        symbols = re.sub(r'\s+', '', line)
        row = []
        for symbol in symbols:
            if symbol in FILLED_CHARACTERS:
                row.append(True)
            elif symbol in EMPTY_CHARACTERS:
                row.append(False)
            else:
                raise FootprintError(f"Unexpected '{symbol}', use '#' for a cell and '.' for an empty spot")
        rows.append(row)
    return rows

def parseFootprint(text: str) -> Footprint:
    """Cells of the shape in the text, see the module description for the format. Raises FootprintError when it
    is empty, too big, falls apart in several pieces or has pieces touching only at a corner"""
    if text is None or text.strip() == '':
        raise FootprintError('The shape is empty')
    text = text.strip()
    grid = _gridFromRowLengths(text) if _isRowLengthsText(text) else _gridFromSymbols(text)

    # the first row is the top one
    cells = set()
    for (lineIndex, row) in enumerate(grid):
        for (column, isFilled) in enumerate(row):
            if isFilled:
                cells.add((column, len(grid) - 1 - lineIndex))
    if len(cells) == 0:
        raise FootprintError('The shape has no cells')

    # spare empty rows and columns around the shape don't count
    minColumn = min(column for (column, _) in cells)
    minRow = min(row for (_, row) in cells)
    cells = {(column - minColumn, row - minRow) for (column, row) in cells}
    columns = max(column for (column, _) in cells) + 1
    rows = max(row for (_, row) in cells) + 1
    if columns > MAX_SIZE or rows > MAX_SIZE:
        raise FootprintError(f'The shape is {columns} by {rows} cells, {MAX_SIZE} by {MAX_SIZE} is the most')

    footprint = Footprint(frozenset(cells), columns, rows)
    _validateShape(footprint)
    return footprint

def _validateShape(footprint: Footprint):
    for column in range(-1, footprint.columns):
        for row in range(-1, footprint.rows):
            bottomLeft = footprint.has(column, row)
            bottomRight = footprint.has(column + 1, row)
            topLeft = footprint.has(column, row + 1)
            topRight = footprint.has(column + 1, row + 1)
            if (bottomLeft and topRight and not bottomRight and not topLeft) or (bottomRight and topLeft and not bottomLeft and not topRight):
                raise FootprintError(f'Cells touch only at a corner near column {column + 2}, row {row + 2} from the bottom left, add a cell to join them')
    # every cell has to be reachable from the first one through the cell sides
    start = next(iter(sorted(footprint.cells)))
    reached = {start}
    pending = [start]
    while pending:
        (column, row) = pending.pop()
        for neighbour in ((column + 1, row), (column - 1, row), (column, row + 1), (column, row - 1)):
            if neighbour in footprint.cells and neighbour not in reached:
                reached.add(neighbour)
                pending.append(neighbour)
    if len(reached) != len(footprint.cells):
        raise FootprintError('The shape falls apart in separate pieces, every cell has to share a side with another one')

def traceOutlines(footprint: Footprint) -> list[list[tuple[int, int]]]:
    """Corners of the shape boundary in cell coordinates, the outer boundary and one for every hole.
    All walk with the shape on their left, so the outer boundary goes counterclockwise and holes clockwise.
    Only corners where the boundary turns are returned"""
    next_corner: dict[tuple[int, int], tuple[int, int]] = {}
    for (column, row) in footprint.cells:
        if not footprint.has(column, row - 1):
            next_corner[(column, row)] = (column + 1, row)
        if not footprint.has(column + 1, row):
            next_corner[(column + 1, row)] = (column + 1, row + 1)
        if not footprint.has(column, row + 1):
            next_corner[(column + 1, row + 1)] = (column, row + 1)
        if not footprint.has(column - 1, row):
            next_corner[(column, row + 1)] = (column, row)

    loops = []
    visited = set()
    for startCorner in sorted(next_corner):
        if startCorner in visited:
            continue
        points = []
        corner = startCorner
        while corner not in visited:
            visited.add(corner)
            points.append(corner)
            corner = next_corner[corner]
        loops.append(_withoutStraightCorners(points))
    return loops

def _withoutStraightCorners(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    count = len(points)
    for index in range(count):
        previous = points[index - 1]
        current = points[index]
        following = points[(index + 1) % count]
        incoming = (current[0] - previous[0], current[1] - previous[1])
        outgoing = (following[0] - current[0], following[1] - current[1])
        if incoming[0] * outgoing[1] - incoming[1] * outgoing[0] != 0:
            result.append(current)
    return result

def _unit(dx: float, dy: float) -> Point:
    length = math.hypot(dx, dy)
    return (dx / length, dy / length)

def outlineLoops(
    footprint: Footprint,
    unitX: float,
    unitY: float,
    inset: float,
    cornerRadius: float,
    offsetX: float = 0,
    offsetY: float = 0,
) -> list[Loop]:
    """Boundary of the shape moved inwards by the inset, with the outward pointing corners rounded.
    Cells are unitX by unitY big and the cell at column 0, row 0 starts at the offset. Inward pointing corners
    stay sharp, so a wall following the outline keeps its thickness when offsetting it again with a smaller radius.
    The corner radius is cut down where the sides next to a corner are too short for it"""
    loops = []
    for corners in traceOutlines(footprint):
        count = len(corners)
        # scale to lengths first, then walk the sides
        vertices = [(column * unitX, row * unitY) for (column, row) in corners]
        directions = [_unit(vertices[(i + 1) % count][0] - vertices[i][0], vertices[(i + 1) % count][1] - vertices[i][1]) for i in range(count)]
        # the side leaving vertex i is directions[i], the one arriving is directions[i - 1], left normal of (x, y) is (-y, x)
        moved = []
        for i in range(count):
            incoming = directions[i - 1]
            outgoing = directions[i]
            normalIn = (-incoming[1], incoming[0])
            normalOut = (-outgoing[1], outgoing[0])
            moved.append((
                vertices[i][0] + inset * (normalIn[0] + normalOut[0]),
                vertices[i][1] + inset * (normalIn[1] + normalOut[1]),
            ))
        sideLengths = [math.hypot(moved[(i + 1) % count][0] - moved[i][0], moved[(i + 1) % count][1] - moved[i][1]) for i in range(count)]
        if min(sideLengths) <= 1e-9:
            raise FootprintError('The walls are too thick for the shape')

        # (arrival point, arc middle or None, departure point) for every vertex
        ports: list[tuple[Point, Point | None, Point]] = []
        for i in range(count):
            incoming = directions[i - 1]
            outgoing = directions[i]
            isConvex = incoming[0] * outgoing[1] - incoming[1] * outgoing[0] > 0
            vertex = moved[i]
            radius = min(cornerRadius, sideLengths[i - 1] / 2, sideLengths[i] / 2)
            if not isConvex or radius <= 1e-9:
                ports.append((vertex, None, vertex))
                continue
            normalIn = (-incoming[1], incoming[0])
            normalOut = (-outgoing[1], outgoing[0])
            start = (vertex[0] - incoming[0] * radius, vertex[1] - incoming[1] * radius)
            end = (vertex[0] + outgoing[0] * radius, vertex[1] + outgoing[1] * radius)
            center = (vertex[0] + radius * (normalIn[0] + normalOut[0]), vertex[1] + radius * (normalIn[1] + normalOut[1]))
            diagonal = _unit(normalIn[0] + normalOut[0], normalIn[1] + normalOut[1])
            middle = (center[0] - radius * diagonal[0], center[1] - radius * diagonal[1])
            ports.append((start, middle, end))

        loop: Loop = []
        for i in range(count):
            (arrival, middle, departure) = ports[i]
            (_, _, previousDeparture) = ports[i - 1]
            if math.hypot(arrival[0] - previousDeparture[0], arrival[1] - previousDeparture[1]) > 1e-9:
                loop.append(('line', previousDeparture, arrival))
            if middle is not None:
                loop.append(('arc', arrival, middle, departure))
        loops.append([_shifted(segment, offsetX, offsetY) for segment in loop])
    return loops

def _shifted(segment: Segment, offsetX: float, offsetY: float) -> Segment:
    return (segment[0],) + tuple((point[0] + offsetX, point[1] + offsetY) for point in segment[1:])

def loopArea(loop: Loop) -> float:
    """Signed area of a loop, positive when it goes counterclockwise, arcs included"""
    area = 0.0
    for segment in loop:
        start = segment[1]
        end = segment[-1]
        area += (start[0] * end[1] - end[0] * start[1]) / 2
        if segment[0] == 'arc':
            area += _arcSegmentArea(segment[1], segment[2], segment[3])
    return area

def _arcSegmentArea(start: Point, middle: Point, end: Point) -> float:
    """Signed area between an arc through the three points and its chord, positive when the arc bulges to the
    right of the way from start to end, which is outwards for the corners of a counterclockwise loop"""
    chord = math.hypot(end[0] - start[0], end[1] - start[1])
    # distance of the middle from the chord is the sagitta
    cross = (end[0] - start[0]) * (middle[1] - start[1]) - (end[1] - start[1]) * (middle[0] - start[0])
    sagitta = abs(cross) / chord
    if sagitta <= 1e-12:
        return 0.0
    radius = (chord ** 2 / 4 + sagitta ** 2) / (2 * sagitta)
    angle = 2 * math.asin(min(1.0, chord / (2 * radius)))
    if sagitta > radius:
        angle = 2 * math.pi - angle
    area = radius ** 2 / 2 * (angle - math.sin(angle))
    # a middle left of the way means the arc bulges left
    return -area if cross > 0 else area

def isClosed(loop: Loop) -> bool:
    """Every segment starts where the one before it ended"""
    for i, segment in enumerate(loop):
        previousEnd = loop[i - 1][-1]
        if math.hypot(segment[1][0] - previousEnd[0], segment[1][1] - previousEnd[1]) > 1e-9:
            return False
    return True

def cellIndex(center: float, unit: float, clearance: float) -> int:
    """Column or row of the cell a body centered at the given coordinate belongs to. Bins and plates share the
    grid, cells start a clearance before the origin"""
    return int(math.floor((center + clearance) / unit))

def cellCenter(index: int, unit: float, clearance: float) -> float:
    return unit * (index + 0.5) - clearance

def sizeInCells(footprint: Footprint) -> tuple[int, int]:
    return (footprint.columns, footprint.rows)

def outerSize(footprint: Footprint, unitX: float, unitY: float, clearance: float) -> tuple[float, float]:
    """Width and length of the bounding box of the bin body, same as a rectangular bin of the same size"""
    return (footprint.columns * unitX - clearance * 2, footprint.rows * unitY - clearance * 2)
