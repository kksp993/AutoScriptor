from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AutoScriptor.core.display_contract import EXPECTED_FRAME_SIZE, get_frame_size
from AutoScriptor.recognition.img_rec import imgOnScreen


SUPPORTED_SCHEMA_VERSION = 1
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "test" / "fixtures" / "recognition_baselines" / "manifest.json"
)


def run_recognition_baselines(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    started_at = time.perf_counter()
    case_results: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()

    for case in manifest["cases"]:
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            raise ValueError("Every recognition baseline case must have a non-empty id.")
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate recognition baseline case id: {case_id}")
        seen_case_ids.add(case_id)
        case_results.append(_run_case(case, manifest_path.parent))

    passed_count = sum(case_result["passed"] for case_result in case_results)
    failed_count = len(case_results) - passed_count
    elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    if not case_results:
        status = "empty"
    elif failed_count:
        status = "failed"
    else:
        status = "passed"
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "library_version": manifest["library_version"],
        "manifest_path": str(manifest_path),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "coordinate_contract": manifest["coordinate_contract"],
        "summary": {
            "status": status,
            "total": len(case_results),
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(passed_count / len(case_results), 4) if case_results else None,
            "elapsed_ms": elapsed_ms,
        },
        "cases": case_results,
    }


def write_baseline_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid baseline manifest JSON: {error}") from error

    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported recognition baseline schema_version: "
            f"{manifest.get('schema_version')!r}; expected {SUPPORTED_SCHEMA_VERSION}."
        )
    library_version = str(manifest.get("library_version") or "").strip()
    if not library_version:
        raise ValueError("Recognition baseline manifest must declare library_version.")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Recognition baseline manifest cases must be a list.")

    coordinate_contract = manifest.get("coordinate_contract")
    expected_contract = {
        "width": EXPECTED_FRAME_SIZE[0],
        "height": EXPECTED_FRAME_SIZE[1],
        "orientation": "landscape",
        "box_mode": "xywh",
    }
    if coordinate_contract != expected_contract:
        raise ValueError(
            "Recognition baseline coordinate_contract must exactly match "
            f"{expected_contract!r}; got {coordinate_contract!r}."
        )
    return manifest


def _run_case(case: dict[str, Any], manifest_directory: Path) -> dict[str, Any]:
    case_id = str(case["id"])
    operation = str(case.get("operation") or "").strip()
    started_at = time.perf_counter()
    try:
        screenshot_path = _resolve_case_path(
            manifest_directory,
            case.get("screenshot"),
            field_name="screenshot",
        )
        screenshot = _read_image(screenshot_path)
        actual_size = get_frame_size(screenshot)
        if actual_size != EXPECTED_FRAME_SIZE:
            raise ValueError(
                f"Baseline frame must be {EXPECTED_FRAME_SIZE[0]}x{EXPECTED_FRAME_SIZE[1]}, "
                f"got {actual_size}."
            )

        if operation == "template":
            evaluation = _run_template_case(case, manifest_directory, screenshot)
        elif operation == "ocr":
            evaluation = _run_ocr_case(case, screenshot)
        else:
            raise ValueError(
                f"Unsupported baseline operation {operation!r}; expected 'template' or 'ocr'."
            )
    except Exception as error:
        return {
            "id": case_id,
            "operation": operation,
            "passed": False,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
            "error": f"{type(error).__name__}: {error}",
        }

    evaluation.update(
        {
            "id": case_id,
            "operation": operation,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        }
    )
    return evaluation


def _run_template_case(
    case: dict[str, Any],
    manifest_directory: Path,
    screenshot: np.ndarray,
) -> dict[str, Any]:
    template_path = _resolve_case_path(
        manifest_directory,
        case.get("template"),
        field_name="template",
    )
    template = _read_image(template_path)
    confidence = float(case.get("confidence", 0.9))
    matched_boxes = imgOnScreen(screenshot, [template], confidence=confidence)[0]
    actual_boxes = [_box_to_dict(box) for box in matched_boxes]
    expected = case.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("Template baseline expected must be an object.")

    expected_matched = bool(expected.get("matched"))
    actual_matched = bool(actual_boxes)
    passed = expected_matched == actual_matched
    expected_boxes = expected.get("boxes", [])
    tolerance = int(expected.get("tolerance", 0))
    if passed and expected_boxes:
        if not isinstance(expected_boxes, list):
            raise ValueError("Template expected.boxes must be a list.")
        passed = all(
            any(_boxes_are_close(actual_box, expected_box, tolerance) for actual_box in actual_boxes)
            for expected_box in expected_boxes
        )

    return {
        "passed": passed,
        "expected": expected,
        "actual": {
            "matched": actual_matched,
            "boxes": actual_boxes,
        },
    }


def _run_ocr_case(case: dict[str, Any], screenshot: np.ndarray) -> dict[str, Any]:
    from AutoScriptor.recognition.ocr_rec import ocr_for_box
    from AutoScriptor.utils.box import Box

    box_values = case.get("box")
    if not isinstance(box_values, list) or len(box_values) != 4:
        raise ValueError("OCR baseline box must be [left, top, width, height].")
    target_box = Box(*(int(value) for value in box_values))
    actual_value = ocr_for_box(screenshot, target_box, ttl=0)
    expected = case.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("OCR baseline expected must be an object.")

    if "value" in expected:
        passed = actual_value == expected["value"]
    elif "pattern" in expected:
        passed = re.fullmatch(str(expected["pattern"]), str(actual_value or "")) is not None
    else:
        raise ValueError("OCR expected must declare value or pattern.")
    return {
        "passed": passed,
        "expected": expected,
        "actual": {"value": actual_value},
    }


def _read_image(image_path: Path) -> np.ndarray:
    try:
        encoded_image = np.fromfile(str(image_path), dtype=np.uint8)
        decoded_image = cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)
    except (OSError, ValueError, cv2.error) as error:
        raise ValueError(f"Cannot read image {image_path}: {error}") from error
    if decoded_image is None:
        raise ValueError(f"OpenCV cannot decode image: {image_path}")
    return decoded_image


def _resolve_case_path(
    manifest_directory: Path,
    relative_path: Any,
    *,
    field_name: str,
) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError(f"Baseline case {field_name} must be a non-empty relative path.")
    manifest_root = manifest_directory.resolve()
    resolved_path = (manifest_root / relative_path).resolve()
    try:
        resolved_path.relative_to(manifest_root)
    except ValueError as error:
        raise ValueError(f"Baseline case {field_name} escapes the manifest directory.") from error
    if not resolved_path.is_file():
        raise ValueError(f"Baseline case {field_name} does not exist: {resolved_path}")
    return resolved_path


def _box_to_dict(box) -> dict[str, int]:
    return {
        "left": int(box.left),
        "top": int(box.top),
        "width": int(box.width),
        "height": int(box.height),
    }


def _boxes_are_close(
    actual_box: dict[str, int],
    expected_box: dict[str, Any],
    tolerance: int,
) -> bool:
    coordinate_names = ("left", "top", "width", "height")
    try:
        return all(
            abs(actual_box[coordinate_name] - int(expected_box[coordinate_name])) <= tolerance
            for coordinate_name in coordinate_names
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "Each expected template box must contain integer left, top, width and height fields."
        )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed-frame recognition baselines.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Versioned recognition baseline manifest.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON report path. Defaults to a timestamped file under logs/.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    output_path = arguments.output
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT / "logs" / f"recognition-baseline-{timestamp}.json"

    report = run_recognition_baselines(arguments.manifest)
    written_path = write_baseline_report(report, output_path)
    summary = report["summary"]
    print(
        f"识别基准完成：{summary['passed']}/{summary['total']} 通过；"
        f"耗时 {summary['elapsed_ms']} ms；报告：{written_path}"
    )
    if summary["status"] == "empty":
        print("识别基准清单没有样本；未执行回归检查，请先添加审核过的固定帧。")
        return 2
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
