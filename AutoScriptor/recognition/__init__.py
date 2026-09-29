"""Lazy public exports for ``AutoScriptor.recognition``.

Importing a lightweight submodule such as ``AutoScriptor.recognition.locate``
must not start the Paddle OCR runtime or the background engine thread owned by
``ocr_rec``. Star imports still expose the recognition API; those symbols are
resolved on first access. Recognition diagnostics live in
``AutoScriptor.logging.recognition_trace``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # locating targets on a frame
    "imgOnScreen": ("AutoScriptor.recognition.locate", "imgOnScreen"),
    "locate_on_screen": ("AutoScriptor.recognition.locate", "locate_on_screen"),
    "get_box_color": ("AutoScriptor.recognition.locate", "get_box_color"),
    "BoxTargetLayout": ("AutoScriptor.recognition.locate", "BoxTargetLayout"),
    "extract_registered_image_keys": (
        "AutoScriptor.recognition.locate",
        "extract_registered_image_keys",
    ),
    # OCR engine facade and its process-level configuration snapshot
    "ocr": ("AutoScriptor.recognition.ocr_rec", "ocr"),
    "ocr_for_box": ("AutoScriptor.recognition.ocr_rec", "ocr_for_box"),
    "get_ocr_engine": ("AutoScriptor.recognition.ocr_rec", "get_ocr_engine"),
    "ocr_manager": ("AutoScriptor.recognition.ocr_rec", "ocr_manager"),
    "get_ocr_runtime_status": ("AutoScriptor.recognition.ocr_rec", "get_ocr_runtime_status"),
    "ocr_runtime_config": ("AutoScriptor.recognition.ocr_rec", "ocr_runtime_config"),
    "read_configured_ocr_runtime": (
        "AutoScriptor.recognition.ocr_rec",
        "read_configured_ocr_runtime",
    ),
    "OCRRuntimeConfig": ("AutoScriptor.recognition.ocr_rec", "OCRRuntimeConfig"),
    # PP-OCRv6 engine and its model-profile table
    "PPOCRv6Engine": ("AutoScriptor.recognition.ocr_engine", "PPOCRv6Engine"),
    "OCR_MODEL_PROFILES": (
        "AutoScriptor.recognition.ocr_engine",
        "OCR_MODEL_PROFILES",
    ),
    "normalize_ocr_result": (
        "AutoScriptor.recognition.ocr_engine",
        "normalize_ocr_result",
    ),
    "resolve_model_profile": (
        "AutoScriptor.recognition.ocr_engine",
        "resolve_model_profile",
    ),
    "get_paddleocr_version": (
        "AutoScriptor.recognition.ocr_engine",
        "get_paddleocr_version",
    ),
}

# Addressable as attributes, e.g. ``AutoScriptor.recognition.ocr_rec.ocr``.
_SUBMODULES = (
    "locate",
    "ocr_engine",
    "ocr_rec",
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
