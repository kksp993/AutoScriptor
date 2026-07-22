from __future__ import annotations

from typing import Any


EXPECTED_FRAME_WIDTH = 1280
EXPECTED_FRAME_HEIGHT = 720
EXPECTED_FRAME_SIZE = (EXPECTED_FRAME_WIDTH, EXPECTED_FRAME_HEIGHT)
COORDINATE_CONTRACT = "1280x720 landscape, absolute pixel coordinates, Box(x, y, width, height)"


def get_frame_size(frame: Any) -> tuple[int, int] | None:
    """Return a frame's width and height without importing an image library."""

    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return None
    try:
        return int(shape[1]), int(shape[0])
    except (TypeError, ValueError):
        return None


def frame_matches_coordinate_contract(frame: Any) -> bool:
    return get_frame_size(frame) == EXPECTED_FRAME_SIZE
