"""Compare PaddleOCR model profiles on identical screenshots or cropped ROIs."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AutoScriptor.recognition.paddle_ocr_compat import (  # noqa: E402
    OCR_MODEL_PROFILES,
    CompatiblePaddleOCR,
    get_paddleocr_version,
)


DEFAULT_MODEL_PROFILES = ("PP-OCRv4", "PP-OCRv6_small")


def _parse_roi(value: str) -> tuple[int, int, int, int]:
    try:
        left, top, width, height = (int(part.strip()) for part in value.split(","))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "ROI must use left,top,width,height integer format"
        ) from error
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(
            "ROI left/top must be non-negative and width/height must be positive"
        )
    return left, top, width, height


def _read_image(
    image_path: Path,
    roi: tuple[int, int, int, int] | None,
) -> np.ndarray:
    encoded_image = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to read image: {image_path}")
    if roi is None:
        return image

    left, top, width, height = roi
    right = min(image.shape[1], left + width)
    bottom = min(image.shape[0], top + height)
    if left >= right or top >= bottom:
        raise ValueError(f"ROI {roi} is outside image bounds for {image_path}")
    return image[top:bottom, left:right]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = round((len(sorted_values) - 1) * percentile)
    return sorted_values[index]


def _serialize_lines(normalized_result: list[list[Any]]) -> list[dict[str, Any]]:
    lines = normalized_result[0] if normalized_result else []
    serialized_lines: list[dict[str, Any]] = []
    for bounding_points, text_result in lines:
        text, confidence = text_result
        serialized_lines.append(
            {
                "text": str(text),
                "confidence": round(float(confidence), 6),
                "bounding_points": bounding_points,
            }
        )
    return serialized_lines


def _build_target_matches(
    targets: list[str],
    recognized_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recognized_texts = [line["text"] for line in recognized_lines]
    return [
        {
            "target": target,
            "matched": any(target in recognized_text for recognized_text in recognized_texts),
        }
        for target in targets
    ]


def _run_model_worker(arguments: argparse.Namespace) -> None:
    model_profile_name = arguments.models[0]
    images = [
        (image_path, _read_image(image_path, arguments.roi))
        for image_path in arguments.images
    ]

    initialization_started_at = time.perf_counter()
    engine = CompatiblePaddleOCR(
        model_profile_name=model_profile_name,
        language="ch",
        use_gpu=arguments.use_gpu,
    )
    initialization_seconds = time.perf_counter() - initialization_started_at

    for _ in range(arguments.warmup):
        for _, image in images:
            engine.ocr(image)

    image_results: list[dict[str, Any]] = []
    all_inference_seconds: list[float] = []
    for image_path, image in images:
        inference_seconds: list[float] = []
        normalized_result: list[list[Any]] = [[]]
        for _ in range(arguments.repeat):
            inference_started_at = time.perf_counter()
            normalized_result = engine.ocr(image)
            inference_seconds.append(time.perf_counter() - inference_started_at)

        all_inference_seconds.extend(inference_seconds)
        recognized_lines = _serialize_lines(normalized_result)
        image_results.append(
            {
                "image": str(image_path),
                "shape": list(image.shape),
                "inference_seconds": [round(value, 6) for value in inference_seconds],
                "median_seconds": round(statistics.median(inference_seconds), 6),
                "recognized_lines": recognized_lines,
                "target_matches": _build_target_matches(arguments.targets, recognized_lines),
            }
        )

    worker_result = {
        "model": model_profile_name,
        "paddleocr_version": get_paddleocr_version(),
        "device": "gpu:0" if arguments.use_gpu else "cpu",
        "initialization_seconds": round(initialization_seconds, 6),
        "median_inference_seconds": round(statistics.median(all_inference_seconds), 6),
        "p95_inference_seconds": round(_percentile(all_inference_seconds, 0.95), 6),
        "images": image_results,
    }
    arguments.worker_output.write_text(
        json.dumps(worker_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_worker_command(
    arguments: argparse.Namespace,
    model_profile_name: str,
    worker_output: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        *(str(image_path) for image_path in arguments.images),
        "--model",
        model_profile_name,
        "--repeat",
        str(arguments.repeat),
        "--warmup",
        str(arguments.warmup),
        "--worker-output",
        str(worker_output),
    ]
    if arguments.roi is not None:
        command.extend(["--roi", ",".join(str(value) for value in arguments.roi)])
    if arguments.use_gpu:
        command.append("--gpu")
    for target in arguments.targets:
        command.extend(["--target", target])
    return command


def _run_comparison(arguments: argparse.Namespace) -> None:
    model_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="autoscriptor-ocr-benchmark-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        for model_index, model_profile_name in enumerate(arguments.models):
            worker_output = temporary_path / f"model-{model_index}.json"
            print(f"Running {model_profile_name}...", flush=True)
            subprocess.run(
                _build_worker_command(arguments, model_profile_name, worker_output),
                cwd=PROJECT_ROOT,
                check=True,
            )
            model_results.append(json.loads(worker_output.read_text(encoding="utf-8")))

    comparison_result = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "roi": list(arguments.roi) if arguments.roi is not None else None,
        "targets": arguments.targets,
        "repeat": arguments.repeat,
        "warmup": arguments.warmup,
        "models": model_results,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(comparison_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for model_result in model_results:
        print(
            f"{model_result['model']}: init={model_result['initialization_seconds']:.3f}s, "
            f"median={model_result['median_inference_seconds']:.3f}s, "
            f"p95={model_result['p95_inference_seconds']:.3f}s"
        )
    print(f"Benchmark report: {arguments.output}")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare PP-OCRv4 and PP-OCRv6 with isolated model processes.",
    )
    parser.add_argument("images", nargs="+", type=Path, help="Screenshot image paths")
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        choices=tuple(OCR_MODEL_PROFILES),
        help="Model profile; repeat to compare multiple models",
    )
    parser.add_argument("--target", dest="targets", action="append", default=[])
    parser.add_argument("--roi", type=_parse_roi, help="left,top,width,height")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--gpu", dest="use_gpu", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs") / "ocr-model-benchmark.json",
    )
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> None:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    if arguments.repeat <= 0:
        parser.error("--repeat must be positive")
    if arguments.warmup < 0:
        parser.error("--warmup must be non-negative")
    if arguments.models is None:
        arguments.models = list(DEFAULT_MODEL_PROFILES)
    if arguments.worker_output is not None:
        if len(arguments.models) != 1:
            parser.error("worker mode requires exactly one --model")
        _run_model_worker(arguments)
        return
    _run_comparison(arguments)


if __name__ == "__main__":
    main()
