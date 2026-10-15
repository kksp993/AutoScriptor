import csv
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.audit_ui_assets import audit_ui_assets


UI_MAP_FIELDS = ["key", "text", "left", "top", "width", "height", "img"]


def _write_ui_map(assets_directory: Path, rows: list[dict[str, str]]) -> None:
    config_directory = assets_directory / "config"
    config_directory.mkdir(parents=True, exist_ok=True)
    with (config_directory / "ui_map.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=UI_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_image(image_path: Path, image: np.ndarray) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    encoded, buffer = cv2.imencode(image_path.suffix, image)
    if not encoded:
        raise RuntimeError(f"Failed to encode test image: {image_path}")
    buffer.tofile(str(image_path))


def _snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        file_path.relative_to(root).as_posix(): file_path.read_bytes()
        for file_path in root.rglob("*")
        if file_path.is_file()
    }


class UiAssetAuditTests(unittest.TestCase):
    def test_valid_assets_pass_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            assets_directory = Path(temporary_directory) / "assets"
            _write_ui_map(
                assets_directory,
                [
                    {
                        "key": "valid",
                        "text": "",
                        "left": "10",
                        "top": "20",
                        "width": "16",
                        "height": "12",
                        "img": "valid.png",
                    }
                ],
            )
            _write_image(
                assets_directory / "pic" / "valid.png",
                np.full((12, 16, 3), 127, dtype=np.uint8),
            )
            before = _snapshot_files(assets_directory)

            report = audit_ui_assets(assets_directory)

            self.assertTrue(report["summary"]["passed"])
            self.assertEqual(report["summary"]["errors"], 0)
            self.assertEqual(report["summary"]["warnings"], 0)
            self.assertEqual(_snapshot_files(assets_directory), before)

    def test_broken_assets_report_errors_and_warnings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            assets_directory = Path(temporary_directory) / "assets"
            _write_ui_map(
                assets_directory,
                [
                    {
                        "key": "duplicate",
                        "text": "",
                        "left": "1270",
                        "top": "710",
                        "width": "20",
                        "height": "20",
                        "img": "missing.png",
                    },
                    {
                        "key": "duplicate",
                        "text": "",
                        "left": "0",
                        "top": "0",
                        "width": "bad",
                        "height": "10",
                        "img": "",
                    },
                ],
            )
            _write_image(
                assets_directory / "pic" / "orphan.png",
                np.zeros((10, 10, 3), dtype=np.uint8),
            )

            report = audit_ui_assets(assets_directory)
            issue_codes = {issue["code"] for issue in report["issues"]}

            self.assertFalse(report["summary"]["passed"])
            self.assertTrue(
                {"DUP_KEY", "BAD_BOX", "MISSING_PIC", "BOX_OUT_OF_CANVAS", "ORPHAN_PIC"}
                <= issue_codes
            )


if __name__ == "__main__":
    unittest.main()
