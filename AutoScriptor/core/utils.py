"""Data-only helpers behind core.api; no device, config or execution ownership.

Dependencies point to Box/Target, never back to api. Runtime clocks and
cancellation are supplied by callers; waiting/capture/input remain in api.
Legacy result helpers are re-exported there to preserve existing imports.
"""

from typing import Any, Callable

from AutoScriptor.core.box import Box
from AutoScriptor.core.targets import BoxTarget, ImageTarget, Target, TextTarget


# Argument validation. Keep each operation's existing acceptance rules.

def _validate_timeout(timeout, caller: str) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        hint = ""
        if isinstance(timeout, Target):
            hint = "；多个目标请用 tuple/list 包起来，例如 wait_for_appear((T(...), T(...)))"
        raise TypeError(
            f"{caller} 的 timeout 必须是数字秒数，收到 {type(timeout).__name__}: {timeout!r}{hint}"
        )


def _validate_target(target, caller: str) -> None:
    """Reject bare Box before its namedtuple fields are parsed as targets."""
    if isinstance(target, Box):
        raise TypeError(
            f"{caller} 的 target 收到裸 Box({target})：Box 是 namedtuple，会被当成多目标"
            "元组逐元素解析。要点击/识别一块区域请用 B(...) 包一层：B(Box(...)) 或"
            " B(x, y, w, h)；只要文本或图片时用 T(...)/I(...)。"
        )


def _validate_swipe_duration(duration_s: float, caller: str) -> None:
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
        raise TypeError(
            f"{caller} 的 duration_s 必须是数字秒数，收到 "
            f"{type(duration_s).__name__}: {duration_s!r}"
        )
    if duration_s <= 0:
        raise ValueError(f"{caller} 的 duration_s 必须大于 0，收到 {duration_s!r}")


def _normalize_dynamic_arguments(target, min_area, interval, threshold, timeout):
    """Validate locate_dyn options without applying stricter rules to locate."""
    from math import isfinite

    _validate_target(target, "locate_dyn")
    targets = [target] if isinstance(target, Target) else target
    if not isinstance(targets, list) or not targets or not all(isinstance(item, Target) for item in targets):
        raise TypeError("locate_dyn 需要 Target 或非空 list[Target]")
    minimum_size = (min_area, min_area) if isinstance(min_area, int) else min_area
    if not isinstance(minimum_size, tuple) or len(minimum_size) != 2 or any(type(side) is not int or side <= 0 for side in minimum_size):
        raise ValueError("locate_dyn min_area 必须是正整数或 (正整数宽, 正整数高)")
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("locate_dyn threshold 必须是 1..255 的整数")
    _validate_timeout(interval, "locate_dyn interval")
    _validate_timeout(timeout, "locate_dyn")
    if not isfinite(interval) or interval < 0 or not isfinite(timeout) or timeout <= 0:
        raise ValueError("locate_dyn 需要有限的 interval >= 0、timeout > 0")
    return targets, minimum_size


# Result matrices. Preserve empty values, return shapes and in-place behavior.

def first(box_matrixes: list[list[Box] | list[Box] | None]) -> Box | None:
    """Return the first matched Box, or None for an empty result."""
    if not box_matrixes:
        return None
    if not any(isinstance(box_matrix, list) for box_matrix in box_matrixes):
        return first([box_matrixes])
    for box_matrix in box_matrixes:
        if not box_matrix:
            continue
        for box in box_matrix:
            if box:
                return box
    return None


def simple(box_matrixes: list[list[Box]] | list[Box] | None) -> list[Box]:
    """Keep each slot's first match, truncating the input matrix in place."""
    if not box_matrixes:
        return None
    for position in range(len(box_matrixes)):
        if box_matrixes[position] and len(box_matrixes[position]) > 1:
            box_matrixes[position] = box_matrixes[position][:1]
    return [matches[0] if matches else None for matches in box_matrixes]


def full(box_matrixes: list[list[Box]]) -> bool:
    for position in range(len(box_matrixes)):
        if not box_matrixes[position]:
            return False
    return True


def count(box_matrixes: list[list[Box]]) -> list[int]:
    return [
        0 if not box_matrix else len(box_matrix) if not isinstance(box_matrix, Box) else 1
        for box_matrix in box_matrixes
    ]


def index(box_matrixes: list[list[Box]]) -> int:
    if not box_matrixes:
        return -1
    for position, box in enumerate(box_matrixes):
        if box:
            return position
    return -1


def stable(boxes1: list[list[Box]], boxes2: list[list[Box]]) -> bool:
    if not boxes1 or not boxes2:
        return False
    assert len(boxes1) == len(boxes2)
    for position in range(len(boxes1)):
        first_matches, second_matches = boxes1[position], boxes2[position]
        if bool(first_matches) != bool(second_matches):
            return False
        if not first_matches or not second_matches:
            continue
        for first_box, second_box in zip(first_matches, second_matches):
            if not first_box.sim_box(second_box):
                return False
        if len(first_matches) != len(second_matches):
            return False
    return True


def contains_information(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(contains_information(item) for item in value)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


# Target descriptions only: no screenshot acquisition or recognition here.

def _generate_target_source(target):
    if isinstance(target, ImageTarget | TextTarget):
        return target.get_source(), target.ui.box, target.ui.color
    elif isinstance(target, BoxTarget):
        return target.box, target.box, target.color
    else:
        raise ValueError(
            f"Unsupported target type: {type(target)}"
            "；识别目标只能是 T()/I()/B() 的返回值（裸 Box 是 namedtuple，"
            "会被当成多目标元组逐元素解析）"
        )


def _format_match_path(path: tuple[int, ...]) -> str:
    """Format a nested target index path, e.g. [1.0] or [2]."""
    if not path:
        return "[?]"
    return "[" + ".".join(str(position) for position in path) + "]"


def _flatten_target_paths(target: Target | list[Target] | tuple[Target, ...]) -> list[tuple[tuple[int, ...], Target]]:
    """Flatten a target tree to (index path, leaf target), retaining order."""
    if isinstance(target, Target):
        return [((), target)]
    if isinstance(target, (tuple, list)):
        flattened: list[tuple[tuple[int, ...], Target]] = []
        for position, child in enumerate(target):
            if isinstance(child, Target):
                flattened.append(((position,), child))
            elif isinstance(child, (tuple, list)):
                for subpath, leaf_target in _flatten_target_paths(child):
                    flattened.append(((position,) + subpath, leaf_target))
            else:
                raise TypeError(f"locate 目标必须是 Target 或嵌套序列，收到 {type(child)!r}: {child!r}")
        return flattened
    raise TypeError(f"locate 目标类型不支持: {type(target)!r}")


def _first_hit_path(boxes: list, target: Target | list[Target] | tuple[Target, ...]) -> str | None:
    """Return the first hit's target path, following first(boxes) order."""
    paths = _flatten_target_paths(target)
    if len(paths) != len(boxes):
        for position, matches in enumerate(boxes):
            if matches and first([matches]) is not None:
                return _format_match_path((position,))
        return None
    for position, matches in enumerate(boxes):
        if matches and first([matches]) is not None:
            return _format_match_path(paths[position][0])
    return None


# Deadline checks: the caller keeps ownership of clocks, cancellation and sleep.

def make_deadline_check(
    deadline: float,
    message: str,
    *,
    clock: Callable[[], float],
    cancel_check: Callable[[], None],
) -> Callable[[], float]:
    """Bind an absolute deadline without restarting its budget; cancel wins."""
    def check_deadline() -> float:
        cancel_check()
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(message)
        return remaining

    return check_deadline
