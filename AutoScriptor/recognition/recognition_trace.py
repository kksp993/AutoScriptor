from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable


RECOGNITION_TRACE_LIMIT = 32
_SUMMARY_COLLECTION_LIMIT = 20
_SUMMARY_TEXT_LIMIT = 300
_thread_state = threading.local()


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """A lightweight internal record for one recognition operation.

    Public recognition APIs continue to return their existing domain values.
    This object is stored only in the bounded diagnostic side channel below.
    """

    operation: str
    success: bool
    target_summary: Any
    result_summary: Any
    elapsed_ms: float
    frame_source: str
    frame_shape: tuple[int, ...] | None = None
    engine: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "success": self.success,
            "target_summary": self.target_summary,
            "result_summary": self.result_summary,
            "elapsed_ms": self.elapsed_ms,
            "frame_source": self.frame_source,
            "frame_shape": list(self.frame_shape) if self.frame_shape is not None else None,
            "engine": self.engine,
            "error": self.error,
            "metadata": dict(self.metadata),
            "recorded_at": self.recorded_at,
        }


def record_recognition_result(result: RecognitionResult) -> RecognitionResult:
    """Append a result to the current thread's bounded recognition trace."""

    _get_trace_buffer().append(result)
    return result


def get_recent_recognition_results(limit: int = RECOGNITION_TRACE_LIMIT) -> list[RecognitionResult]:
    """Return the newest records without exposing the mutable trace buffer."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"limit must be an integer, got {type(limit).__name__}")
    if limit <= 0:
        return []
    return list(_get_trace_buffer())[-limit:]


def get_last_recognition_result() -> RecognitionResult | None:
    trace_buffer = _get_trace_buffer()
    return trace_buffer[-1] if trace_buffer else None


def clear_recognition_trace() -> None:
    _get_trace_buffer().clear()


def summarize_recognition_value(value: Any, *, _depth: int = 0) -> Any:
    """Convert recognition inputs and outputs to small JSON-safe summaries."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)

    box_summary = _summarize_box_like(value)
    if box_summary is not None:
        return box_summary

    if _depth >= 3:
        return _truncate_text(repr(value))

    if isinstance(value, dict):
        summarized_items = list(value.items())[:_SUMMARY_COLLECTION_LIMIT]
        result = {
            _truncate_text(str(key)): summarize_recognition_value(item, _depth=_depth + 1)
            for key, item in summarized_items
        }
        if len(value) > _SUMMARY_COLLECTION_LIMIT:
            result["__omitted_items__"] = len(value) - _SUMMARY_COLLECTION_LIMIT
        return result

    if isinstance(value, (list, tuple)):
        summarized_values = [
            summarize_recognition_value(item, _depth=_depth + 1)
            for item in value[:_SUMMARY_COLLECTION_LIMIT]
        ]
        if len(value) > _SUMMARY_COLLECTION_LIMIT:
            summarized_values.append({"__omitted_items__": len(value) - _SUMMARY_COLLECTION_LIMIT})
        return summarized_values

    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            return {
                "type": type(value).__name__,
                "shape": [int(dimension) for dimension in shape],
            }
        except (TypeError, ValueError):
            pass

    return _truncate_text(repr(value))


def get_frame_shape(frame: Any) -> tuple[int, ...] | None:
    shape = getattr(frame, "shape", None)
    if shape is None:
        return None
    try:
        return tuple(int(dimension) for dimension in shape)
    except (TypeError, ValueError):
        return None


def create_recognition_result(
    *,
    operation: str,
    success: bool,
    target: Any,
    result: Any,
    started_at: float,
    frame_source: str,
    frame: Any = None,
    engine: str | None = None,
    error: BaseException | None = None,
    metadata: dict[str, Any] | None = None,
) -> RecognitionResult:
    elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
    error_summary = None
    if error is not None:
        error_summary = f"{type(error).__name__}: {_truncate_text(str(error))}"
    return RecognitionResult(
        operation=operation,
        success=success,
        target_summary=summarize_recognition_value(target),
        result_summary=summarize_recognition_value(result),
        elapsed_ms=round(elapsed_ms, 3),
        frame_source=frame_source,
        frame_shape=get_frame_shape(frame),
        engine=engine,
        error=error_summary,
        metadata=dict(metadata or {}),
    )


def serialize_recognition_results(results: Iterable[RecognitionResult]) -> list[dict[str, Any]]:
    return [result.to_dict() for result in results]


def _get_trace_buffer() -> deque[RecognitionResult]:
    trace_buffer = getattr(_thread_state, "recognition_trace", None)
    if trace_buffer is None:
        trace_buffer = deque(maxlen=RECOGNITION_TRACE_LIMIT)
        _thread_state.recognition_trace = trace_buffer
    return trace_buffer


def _summarize_box_like(value: Any) -> dict[str, int] | None:
    coordinate_names = ("left", "top", "width", "height")
    if not all(hasattr(value, coordinate_name) for coordinate_name in coordinate_names):
        return None
    try:
        return {
            coordinate_name: int(getattr(value, coordinate_name))
            for coordinate_name in coordinate_names
        }
    except (TypeError, ValueError):
        return None


def _truncate_text(value: str) -> str:
    if len(value) <= _SUMMARY_TEXT_LIMIT:
        return value
    return value[:_SUMMARY_TEXT_LIMIT] + "..."
