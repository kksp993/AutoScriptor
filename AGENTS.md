# Agent Rules

## Online Screenshot Testing / 在线截图测试

When the user asks to "截张图测一下", "在线测一下", "拿当前页面跑一下", or otherwise test code against the live emulator/device screen, treat it as an online screenshot test.

Use this workflow:

1. Capture one live screenshot first, save it under `logs/` with a timestamp, and reuse that exact frame for all locate/OCR/extract calls in the test. Do not mix multiple implicit screenshots unless the test is explicitly about UI transitions.
2. Use the project virtualenv Python: `.venv\Scripts\python.exe`. In PowerShell, prefer UTF-8 output (`$env:PYTHONIOENCODING='utf-8'` or `python -X utf8`) so Chinese item names and OCR text are not misread as file corruption.
3. Put temporary test scripts, crops, overlays, and result JSON/text in a new `logs/<topic>_<timestamp>/` folder unless the user asks to modify source. Do not change production code for a pure online test.
4. Record the screenshot size and coordinate convention before interpreting boxes. For `Box`, confirm whether values mean `(x, y, w, h)` or `(x1, y1, x2, y2)` in the current helper.
5. For crop-sensitive work, save debug crops or an overlay image with boxes drawn. First prove the crop is correct, then judge recognition quality. If a result is wrong, classify it as crop/coordinate failure, recognition failure, or post-processing failure.
6. Prefer batch calls for OCR/extraction over per-box loops. Preserve input shape: `Box -> value`, `list[Box] -> list`, `list[list[Box]] -> nested list`. Empty or unreadable slots should stay as `None`, not be deleted or compacted.
7. Reuse the same screenshot frame through APIs that support it, such as passing `screenshot=frame` to locate-style calls and `screenshot_frame=frame` to extract/OCR-style calls. This avoids UI drift between separate captures.
8. Measure timings with `time.perf_counter()`. Report capture time, recognition/code time, and total time separately when useful. If there is model warm-up, say which run is warm-up and which run is measured.
9. For irreversible game actions, do not silently guess from low-confidence or inconsistent OCR. Return `None`, pause, or ask for confirmation instead. When there is no oracle, compare independent evidence such as row stitching, per-cell crops, and raw OCR/confidence.
10. In final results, include the saved screenshot/debug folder, the exact boxes or grid used, the recognized values with missing values preserved, elapsed time, and the accuracy basis if visible/manual ground truth was checked.

Useful project-specific notes:

- Prefer package imports such as `from AutoScriptor.utils.box_grid import make_box_grid, indexof`; top-level `tools` can be shadowed by third-party packages after PaddleOCR imports.
- For inventory counts, keep recognition semantics separate from business semantics: a missing item can become `0` at the inventory layer, while a present item with no numeric badge can become `1`; the OCR layer should still return `None` for an empty unreadable badge.
- If the user says not to peek at a newly added difficult screenshot before implementation, do not inspect it until after the implementation is complete.
