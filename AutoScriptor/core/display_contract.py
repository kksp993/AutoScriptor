from __future__ import annotations

from typing import Any


MUMU_SIZE_1280_720 = (1280, 720)
MUMU_SIZE_720_1280 = (720, 1280)
EXPECTED_FRAME_WIDTH, EXPECTED_FRAME_HEIGHT = MUMU_SIZE_1280_720
EXPECTED_FRAME_SIZE = MUMU_SIZE_1280_720
COORDINATE_CONTRACT = "1280x720 landscape, absolute pixel coordinates, Box(x, y, width, height)"
_configured_frame_size = EXPECTED_FRAME_SIZE


def setFrameSize(frame_size: tuple[int, int]) -> None:
    """Set the frame size used by APIs whose region bounds are implicit."""
    if (
        not isinstance(frame_size, (tuple, list))
        or len(frame_size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in frame_size)
        or any(value <= 0 for value in frame_size)
    ):
        raise ValueError(f"frame_size 必须是两个正整数，收到 {frame_size!r}")

    global _configured_frame_size
    _configured_frame_size = int(frame_size[0]), int(frame_size[1])


def getFrameSize() -> tuple[int, int]:
    """Return the frame size configured for implicit region bounds."""
    return _configured_frame_size


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
