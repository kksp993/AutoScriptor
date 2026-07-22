# Recognition baselines

This directory is the tracked, versioned fixed-frame corpus for recognition
regression tests. Every screenshot must use the AutoScriptor coordinate
contract: 1280x720 landscape with absolute `Box(x, y, width, height)` pixels.

Do not add screenshots containing account names, chat messages, or other
private data. Keep generated benchmark reports under `logs/`, not here.

## Template case

```json
{
  "id": "unique-stable-id",
  "operation": "template",
  "screenshot": "cases/unique-stable-id/screenshot.png",
  "template": "cases/unique-stable-id/template.png",
  "confidence": 0.9,
  "expected": {
    "matched": true,
    "boxes": [{"left": 10, "top": 20, "width": 30, "height": 40}],
    "tolerance": 2
  }
}
```

## OCR case

```json
{
  "id": "unique-ocr-id",
  "operation": "ocr",
  "screenshot": "cases/unique-ocr-id/screenshot.png",
  "box": [10, 20, 100, 30],
  "expected": {"value": "expected text"}
}
```

Bump `library_version` whenever reviewed expectations or sample images change.
An empty initial manifest is intentional: real game baselines must be curated
from approved, privacy-safe frames rather than fabricated expectations. An
empty manifest reports `status=empty`, leaves `pass_rate` unset, and makes the
CLI exit with code 2; zero samples are never reported as a passing regression.
