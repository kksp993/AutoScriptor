"""Helpers for generating regular Box grids.

The grid area includes the gaps between cells. The generated boxes keep the
same width/height as the first cell, so the gaps are skipped rather than
included in each returned box.
"""

from __future__ import annotations

from AutoScriptor.utils.box import Box


def _as_box(box) -> Box:
    if hasattr(box, "box") and isinstance(box.box, Box):
        return box.box
    if isinstance(box, Box):
        return box
    raise TypeError(f"expected Box or B(...), got {type(box)!r}")


def _step(first_start: int, first_size: int, grid_start: int, grid_size: int, count: int) -> float:
    if count <= 0:
        raise ValueError("row/col must be positive")
    if count == 1:
        return 0.0
    last_start = grid_start + grid_size - first_size
    return (last_start - first_start) / (count - 1)


def make_box_grid(
    first_box,
    grid_box,
    *,
    row: int,
    col: int,
    ctor=None,
) -> list[list]:
    """Return a row x col matrix of boxes.

    Args:
        first_box: The top-left cell's exact box, e.g. Box(422,145,99,96).
        grid_box: The full grid area including inter-cell gaps.
        row: Number of rows.
        col: Number of columns.
        ctor: Optional constructor. Pass ``B`` to return ``B(...)`` targets;
            omit it to return plain ``Box`` objects without importing UI map.
    """
    first = _as_box(first_box)
    grid = _as_box(grid_box)
    x_step = _step(first.left, first.width, grid.left, grid.width, col)
    y_step = _step(first.top, first.height, grid.top, grid.height, row)
    make = ctor or Box
    return [
        [
            make(
                round(first.left + x_step * c),
                round(first.top + y_step * r),
                first.width,
                first.height,
            )
            for c in range(col)
        ]
        for r in range(row)
    ]
