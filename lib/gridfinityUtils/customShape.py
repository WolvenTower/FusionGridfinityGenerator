"""Grid-based custom Gridfinity footprints.

The text syntax is intentionally independent from Fusion 360 so it can be
validated and tested without the Fusion API:

    ###
    #..
    ###
    #..
    ###

'#' means an occupied Gridfinity cell and '.' means empty space.
Rows may also be separated with '/' for single-line UI inputs.
"""

from collections import deque


class CustomShapeError(ValueError):
    pass


class CustomShape:
    def __init__(self, cells: set[tuple[int, int]]):
        if not cells:
            raise CustomShapeError('Shape contains no occupied cells.')

        self.cells = frozenset(cells)
        self.min_x = min(x for x, _ in cells)
        self.max_x = max(x for x, _ in cells)
        self.min_y = min(y for _, y in cells)
        self.max_y = max(y for _, y in cells)

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def length(self) -> int:
        return self.max_y - self.min_y + 1

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def contains(self, x: int, y: int) -> bool:
        return (x, y) in self.cells

    def iter_cells(self):
        return sorted(self.cells, key=lambda cell: (cell[1], cell[0]))

    @classmethod
    def rectangle(cls, width: int, length: int):
        if width < 1 or length < 1:
            raise CustomShapeError(
                'Rectangle width and length must both be at least 1.'
            )

        return cls({
            (x, y)
            for y in range(length)
            for x in range(width)
        })

    @classmethod
    def parse(cls, text: str):
        if text is None:
            raise CustomShapeError('Shape is empty.')

        # The command UI can use a single-line input, while tests and future
        # UI controls can use normal multiline text.
        text = text.replace('/', '\n')
        lines = []

        for raw_line in text.splitlines():
            line = ''.join(raw_line.split())
            if line:
                lines.append(line)

        if not lines:
            raise CustomShapeError('Shape is empty.')

        cells = set()

        for y, line in enumerate(lines):
            for x, char in enumerate(line):
                if char == '#':
                    cells.add((x, y))
                elif char != '.':
                    raise CustomShapeError(
                        f"Invalid character '{char}'. Use '#' for a cell and '.' for empty space."
                    )

        if not cells:
            raise CustomShapeError("Shape must contain at least one '#'.")

        min_x = min(x for x, _ in cells)
        min_y = min(y for _, y in cells)
        shape = cls({
            (x - min_x, y - min_y)
            for x, y in cells
        })
        shape.validate_connected()
        return shape

    def validate_connected(self):
        start = next(iter(self.cells))
        visited = {start}
        queue = deque([start])

        while queue:
            x, y = queue.popleft()
            for neighbor in (
                (x + 1, y),
                (x - 1, y),
                (x, y + 1),
                (x, y - 1),
            ):
                if neighbor in self.cells and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        if len(visited) != len(self.cells):
            raise CustomShapeError(
                "Shape must be one connected object. Separate groups of '#' are not supported."
            )

    def exposed_edges(self):
        directions = {
            'north': (0, -1),
            'south': (0, 1),
            'west': (-1, 0),
            'east': (1, 0),
        }
        result = []

        for x, y in self.cells:
            for direction, (dx, dy) in directions.items():
                if (x + dx, y + dy) not in self.cells:
                    result.append(((x, y), direction))

        return result
