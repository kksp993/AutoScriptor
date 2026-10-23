import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.run_recognition_baselines import run_recognition_baselines


def _write_image(image_path: Path, image: np.ndarray) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    encoded, buffer = cv2.imencode(image_path.suffix, image)
    if not encoded:
        raise RuntimeError(f"Failed to encode test image: {image_path}")
    buffer.tofile(str(image_path))


def _write_manifest(manifest_path: Path, cases: list[dict]) -> None:
    manifest = {
        "schema_version": 1,
        "library_version": "test-version",
        "coordinate_contract": {
            "width": 1280,
            "height": 720,
            "orientation": "landscape",
            "box_mode": "xywh",
        },
        "cases": cases,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


class RecognitionBaselineTests(unittest.TestCase):
    def test_empty_manifest_is_not_reported_as_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_directory = Path(temporary_directory)
            manifest_path = baseline_directory / "manifest.json"
            _write_manifest(manifest_path, [])

            report = run_recognition_baselines(manifest_path)

            self.assertEqual(report["summary"]["status"], "empty")
            self.assertEqual(report["summary"]["total"], 0)
            self.assertIsNone(report["summary"]["pass_rate"])

    def test_template_case_runs_against_a_fixed_frame(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_directory = Path(temporary_directory)
            screenshot_path = baseline_directory / "screenshot.png"
            template_path = baseline_directory / "template.png"
            manifest_path = baseline_directory / "manifest.json"

            random_generator = np.random.default_rng(seed=20260713)
            template = random_generator.integers(
                low=0,
                high=256,
                size=(24, 32, 3),
                dtype=np.uint8,
            )
            screenshot = np.zeros((720, 1280, 3), dtype=np.uint8)
            screenshot[200:224, 300:332] = template
            _write_image(screenshot_path, screenshot)
            _write_image(template_path, template)
            _write_manifest(
                manifest_path,
                [
                    {
                        "id": "synthetic-template-smoke",
                        "operation": "template",
                        "screenshot": screenshot_path.name,
                        "template": template_path.name,
                        "confidence": 0.99,
                        "expected": {"matched": True},
                    }
                ],
            )

            report = run_recognition_baselines(manifest_path)

            self.assertEqual(report["summary"]["total"], 1)
            self.assertEqual(report["summary"]["passed"], 1)
            self.assertEqual(report["summary"]["failed"], 0)
            self.assertTrue(report["cases"][0]["actual"]["matched"])

    def test_non_contract_frame_is_reported_as_a_failed_case(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_directory = Path(temporary_directory)
            screenshot_path = baseline_directory / "wrong-size.png"
            template_path = baseline_directory / "template.png"
            manifest_path = baseline_directory / "manifest.json"

            _write_image(
                screenshot_path,
                np.zeros((360, 640, 3), dtype=np.uint8),
            )
            _write_image(
                template_path,
                np.zeros((20, 20, 3), dtype=np.uint8),
            )
            _write_manifest(
                manifest_path,
                [
                    {
                        "id": "wrong-coordinate-contract",
                        "operation": "template",
                        "screenshot": screenshot_path.name,
                        "template": template_path.name,
                        "expected": {"matched": False},
                    }
                ],
            )

            report = run_recognition_baselines(manifest_path)

            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("Baseline frame must be 1280x720", report["cases"][0]["error"])


if __name__ == "__main__":
    unittest.main()
