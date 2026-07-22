from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AutoScriptor.core.display_contract import EXPECTED_FRAME_SIZE


REQUIRED_COLUMNS = {"key", "text", "left", "top", "width", "height", "img"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def audit_ui_assets(assets_directory: Path) -> dict[str, Any]:
    """Audit UI-map references and image metadata without changing source files."""

    assets_directory = assets_directory.resolve()
    ui_map_path = assets_directory / "config" / "ui_map.csv"
    pictures_directory = assets_directory / "pic"
    issues: list[dict[str, Any]] = []
    referenced_images: Counter[str] = Counter()
    seen_keys: dict[str, int] = {}
    row_count = 0

    if not ui_map_path.is_file():
        _append_issue(
            issues,
            severity="error",
            code="MISSING_UI_MAP",
            message=f"UI map does not exist: {ui_map_path}",
        )
        return _build_report(assets_directory, row_count, referenced_images, issues)

    try:
        with ui_map_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            available_columns = set(reader.fieldnames or [])
            missing_columns = sorted(REQUIRED_COLUMNS - available_columns)
            if missing_columns:
                _append_issue(
                    issues,
                    severity="error",
                    code="CSV_HEADER",
                    message=f"UI map is missing columns: {', '.join(missing_columns)}",
                )
                return _build_report(assets_directory, row_count, referenced_images, issues)
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        _append_issue(
            issues,
            severity="error",
            code="CSV_READ_FAILED",
            message=f"Failed to read UI map: {error}",
        )
        return _build_report(assets_directory, row_count, referenced_images, issues)

    for row_number, row in enumerate(rows, start=2):
        row_count += 1
        key = (row.get("key") or "").strip()
        text = (row.get("text") or "").strip()
        image_name = (row.get("img") or "").strip().replace("\\", "/")

        if not key:
            _append_issue(
                issues,
                severity="error",
                code="EMPTY_KEY",
                message="UI map key is empty.",
                row=row_number,
            )
        elif key in seen_keys:
            _append_issue(
                issues,
                severity="error",
                code="DUP_KEY",
                message=f"Duplicate key {key!r}; first declared on row {seen_keys[key]}.",
                row=row_number,
                key=key,
            )
        else:
            seen_keys[key] = row_number

        parsed_box = _parse_box(row, row_number, key, issues)
        if parsed_box is not None:
            left, top, width, height = parsed_box
            canvas_width, canvas_height = EXPECTED_FRAME_SIZE
            box_is_outside_canvas = (
                left < 0
                or top < 0
                or left + width > canvas_width
                or top + height > canvas_height
            )
            if box_is_outside_canvas:
                _append_issue(
                    issues,
                    severity="warning",
                    code="BOX_OUT_OF_CANVAS",
                    message=(
                        f"Box ({left}, {top}, {width}, {height}) exceeds the "
                        f"{canvas_width}x{canvas_height} coordinate contract."
                    ),
                    row=row_number,
                    key=key,
                )

        if not text and not image_name:
            _append_issue(
                issues,
                severity="warning",
                code="EMPTY_SOURCE",
                message="UI entry has neither OCR text nor an image reference.",
                row=row_number,
                key=key,
            )

        if not image_name:
            continue

        referenced_images[image_name] += 1
        image_path = _resolve_picture_path(pictures_directory, image_name)
        if image_path is None:
            _append_issue(
                issues,
                severity="error",
                code="IMAGE_OUTSIDE_PIC",
                message=f"Image reference escapes the pic directory: {image_name}",
                row=row_number,
                key=key,
            )
            continue
        if not image_path.is_file():
            _append_issue(
                issues,
                severity="error",
                code="MISSING_PIC",
                message=f"Referenced image does not exist: {image_name}",
                row=row_number,
                key=key,
                path=image_name,
            )
            continue

        image_metadata = _read_image_metadata(image_path)
        if image_metadata is None:
            _append_issue(
                issues,
                severity="error",
                code="UNREADABLE_PIC",
                message=f"OpenCV cannot decode image: {image_name}",
                row=row_number,
                key=key,
                path=image_name,
            )
            continue

        image_width, image_height, channel_count = image_metadata
        if image_width <= 0 or image_height <= 0:
            _append_issue(
                issues,
                severity="error",
                code="ZERO_SIZE_PIC",
                message=f"Image has invalid dimensions: {image_name}",
                row=row_number,
                key=key,
                path=image_name,
            )
        elif image_width < 4 or image_height < 4:
            _append_issue(
                issues,
                severity="warning",
                code="TINY_TEMPLATE",
                message=f"Template is only {image_width}x{image_height}: {image_name}",
                row=row_number,
                key=key,
                path=image_name,
            )

        if channel_count not in {1, 3, 4}:
            _append_issue(
                issues,
                severity="warning",
                code="UNUSUAL_CHANNELS",
                message=f"Image has {channel_count} channels: {image_name}",
                row=row_number,
                key=key,
                path=image_name,
            )

    for image_name, reference_count in sorted(referenced_images.items()):
        if reference_count > 1:
            _append_issue(
                issues,
                severity="warning",
                code="DUP_IMG_REF",
                message=f"Image is referenced by {reference_count} UI entries: {image_name}",
                path=image_name,
            )

    if pictures_directory.is_dir():
        referenced_image_names = set(referenced_images)
        for image_path in sorted(pictures_directory.rglob("*")):
            if not image_path.is_file() or image_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                continue
            relative_name = image_path.relative_to(pictures_directory).as_posix()
            if relative_name not in referenced_image_names:
                _append_issue(
                    issues,
                    severity="warning",
                    code="ORPHAN_PIC",
                    message=f"Image is not referenced by ui_map.csv: {relative_name}",
                    path=relative_name,
                )

    return _build_report(assets_directory, row_count, referenced_images, issues)


def write_audit_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _parse_box(
    row: dict[str, str],
    row_number: int,
    key: str,
    issues: list[dict[str, Any]],
) -> tuple[int, int, int, int] | None:
    try:
        left = int((row.get("left") or "").strip())
        top = int((row.get("top") or "").strip())
        width = int((row.get("width") or "").strip())
        height = int((row.get("height") or "").strip())
    except ValueError:
        _append_issue(
            issues,
            severity="error",
            code="BAD_BOX",
            message="Box coordinates must be integers.",
            row=row_number,
            key=key,
        )
        return None

    if width <= 0 or height <= 0:
        _append_issue(
            issues,
            severity="error",
            code="BAD_BOX",
            message=f"Box width and height must be positive; got {width}x{height}.",
            row=row_number,
            key=key,
        )
        return None
    return left, top, width, height


def _resolve_picture_path(pictures_directory: Path, image_name: str) -> Path | None:
    pictures_root = pictures_directory.resolve()
    image_path = (pictures_root / image_name).resolve()
    try:
        image_path.relative_to(pictures_root)
    except ValueError:
        return None
    return image_path


def _read_image_metadata(image_path: Path) -> tuple[int, int, int] | None:
    try:
        encoded_image = np.fromfile(str(image_path), dtype=np.uint8)
        decoded_image = cv2.imdecode(encoded_image, cv2.IMREAD_UNCHANGED)
    except (OSError, ValueError, cv2.error):
        return None
    if decoded_image is None:
        return None
    image_height, image_width = decoded_image.shape[:2]
    channel_count = 1 if decoded_image.ndim == 2 else int(decoded_image.shape[2])
    return int(image_width), int(image_height), channel_count


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    row: int | None = None,
    key: str | None = None,
    path: str | None = None,
) -> None:
    issue: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if row is not None:
        issue["row"] = row
    if key:
        issue["key"] = key
    if path:
        issue["path"] = path
    issues.append(issue)


def _build_report(
    assets_directory: Path,
    row_count: int,
    referenced_images: Counter[str],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "assets_directory": str(assets_directory),
        "coordinate_contract": {
            "width": EXPECTED_FRAME_SIZE[0],
            "height": EXPECTED_FRAME_SIZE[1],
            "orientation": "landscape",
            "box_mode": "xywh",
        },
        "summary": {
            "rows": row_count,
            "referenced_images": len(referenced_images),
            "errors": error_count,
            "warnings": warning_count,
            "passed": error_count == 0,
        },
        "issues": issues,
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit AutoScriptor UI-map assets.")
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=PROJECT_ROOT / "ZmxyOL" / "assets",
        help="Assets directory containing config/ui_map.csv and pic/.",
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
        output_path = PROJECT_ROOT / "logs" / f"ui-asset-audit-{timestamp}.json"

    report = audit_ui_assets(arguments.assets_dir)
    written_path = write_audit_report(report, output_path)
    summary = report["summary"]
    print(
        f"素材审计完成：{summary['errors']} 个错误，{summary['warnings']} 个警告；"
        f"报告：{written_path}"
    )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
