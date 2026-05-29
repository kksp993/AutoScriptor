# Online Screenshot Testing

When the user asks to "截张图测一下", "在线测一下", "拿当前页面跑一下", or otherwise test code against the live emulator/device screen, treat it as an online screenshot test.

## Workflow

1. Capture one live screenshot first, save it under the current logs root with a timestamp (`logs/` in source mode; `data/logs/` in packaged runtime), and reuse that exact frame for all locate/OCR/extract calls in the test. Do not mix multiple implicit screenshots unless the test is explicitly about UI transitions.
2. Use `.venv\Scripts\python.exe`. In PowerShell, prefer UTF-8 output with `$env:PYTHONIOENCODING='utf-8'` or `python -X utf8`.
3. Put temporary test scripts, crops, overlays, and result JSON/text in a new `<logs-root>/<topic>_<timestamp>/` folder unless the user asks to modify source. Do not change production code for a pure online test.
4. Record screenshot size and coordinate convention before interpreting boxes. Confirm whether `Box` means `(x, y, w, h)` or `(x1, y1, x2, y2)` in the current helper.
5. For crop-sensitive work, save debug crops or an overlay with boxes. Prove the crop is correct before judging recognition quality. Classify errors as crop/coordinate, recognition, or post-processing failures.
6. Prefer batch calls for OCR/extraction over per-box loops. Preserve input shape: `Box -> value`, `list[Box] -> list`, `list[list[Box]] -> nested list`. Empty or unreadable slots stay as `None`.
7. Reuse the same frame through APIs that support it, such as `screenshot=frame` for locate calls and `screenshot_frame=frame` for extract/OCR calls.
8. Measure timings with `time.perf_counter()`. Report capture time, recognition/code time, and total time when useful. Separate warm-up from measured runs.
9. For irreversible game actions, do not guess from low-confidence or inconsistent OCR. Return `None`, pause, or ask for confirmation.
10. Final results should include the saved screenshot/debug folder, exact boxes or grid, recognized values with missing values preserved, elapsed time, and the accuracy basis if checked.

## Notes

- Prefer package imports such as `from AutoScriptor.utils.box_grid import make_box_grid, indexof`; top-level `tools` can be shadowed after PaddleOCR imports.
- Keep OCR semantics separate from business semantics.
- If the user says not to peek at a newly added difficult screenshot before implementation, implement first, then inspect it for validation.
