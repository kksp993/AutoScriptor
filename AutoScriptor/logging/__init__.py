"""Logging, error-archive and diagnostic helpers.

Groups the runtime diagnostics layer in one place:

``logger``
    Rich/plain console + file handlers, per-task prefix, source-path rewriting.
``log_archiver``
    Task error archives (recent log lines, runtime context, screenshots).
``tracer``
    Annotated debug screenshots of click/OCR results.
``recognition_trace``
    Bounded per-thread record of recent recognition operations.

Exports stay lazy (PEP 562): importing ``AutoScriptor.logging`` must not pull in
the richer modules until something actually asks for a symbol. Note that this
package name intentionally matches the stdlib module it wraps; Python 3 resolves
``import logging`` inside these files to the standard library, never here.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # console / file logging
    "logger": ("AutoScriptor.logging.logger", "logger"),
    "log_flush": ("AutoScriptor.logging.logger", "log_flush"),
    "setup_logfile": ("AutoScriptor.logging.logger", "setup_logfile"),
    "set_current_task": ("AutoScriptor.logging.logger", "set_current_task"),
    # annotated debug screenshots
    "save_debug_screenshot": ("AutoScriptor.logging.tracer", "save_debug_screenshot"),
    "clear_debug_screenshots": ("AutoScriptor.logging.tracer", "clear_debug_screenshots"),
    # error archives
    "archive_error": ("AutoScriptor.logging.log_archiver", "archive_error"),
    "collect_default_context": (
        "AutoScriptor.logging.log_archiver",
        "collect_default_context",
    ),
    "register_context_provider": (
        "AutoScriptor.logging.log_archiver",
        "register_context_provider",
    ),
    # recognition diagnostics
    "RecognitionResult": (
        "AutoScriptor.logging.recognition_trace",
        "RecognitionResult",
    ),
    "RECOGNITION_TRACE_LIMIT": (
        "AutoScriptor.logging.recognition_trace",
        "RECOGNITION_TRACE_LIMIT",
    ),
    "create_recognition_result": (
        "AutoScriptor.logging.recognition_trace",
        "create_recognition_result",
    ),
    "record_recognition_result": (
        "AutoScriptor.logging.recognition_trace",
        "record_recognition_result",
    ),
    "get_recent_recognition_results": (
        "AutoScriptor.logging.recognition_trace",
        "get_recent_recognition_results",
    ),
    "serialize_recognition_results": (
        "AutoScriptor.logging.recognition_trace",
        "serialize_recognition_results",
    ),
}

# Addressable as attributes, e.g. ``AutoScriptor.logging.tracer``.
_SUBMODULES = (
    "log_archiver",
    "logger",
    "recognition_trace",
    "task_video_recorder",
    "tracer",
)

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attr_name = target
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_SUBMODULES))
