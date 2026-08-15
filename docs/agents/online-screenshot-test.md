# Online Screenshot Testing

When the user asks to "截张图测一下", "在线测一下", "拿当前页面跑一下", or otherwise test code against the live emulator/device screen, treat it as an online screenshot test.

## Workflow

1. Capture one live screenshot first, save it under the current logs root with a timestamp (`logs/` in source mode), and reuse that exact frame for all locate/OCR/extract calls in the test. Do not mix multiple implicit screenshots unless the test is explicitly about UI transitions or timeout behavior.
2. Use `.venv\Scripts\python.exe`. In PowerShell, prefer UTF-8 output with `$env:PYTHONIOENCODING='utf-8'` or `python -X utf8`.
3. Put temporary test scripts, crops, overlays, and result JSON/text in a new `<logs-root>/<topic>_<timestamp>/` folder unless the user asks to modify source. Do not change production code for a pure online test.
4. Record screenshot size and coordinate convention before interpreting boxes. Confirm whether `Box` means `(x, y, w, h)` or `(x1, y1, x2, y2)` in the current helper.
5. For crop-sensitive work, save debug crops or an overlay with boxes. Prove the crop is correct before judging recognition quality. Classify errors as crop/coordinate, recognition, or post-processing failures.
6. Prefer batch calls for OCR/extraction over per-box loops. Preserve input shape: `Box -> value`, `list[Box] -> list`, `list[list[Box]] -> nested list`. Empty or unreadable slots stay as `None`.
7. Reuse the same frame through APIs that support it, such as `screenshot=frame` for locate calls and `screenshot_frame=frame` for extract/OCR calls.
8. Measure timings with `time.perf_counter()`. Report capture time, recognition/code time, and total time when useful. Separate warm-up from measured runs.
9. For irreversible game actions, do not guess from low-confidence or inconsistent OCR. Return `None`, pause, or ask for confirmation.
10. Final results should include the saved screenshot/debug folder, exact boxes or grid, recognized values with missing values preserved, elapsed time, and the accuracy basis if checked.

## Transition And Timeout Bug Validation

Use this workflow when verifying bugs like "after entering a page, X does not appear within N seconds".

1. Define the observable target before acting: expected page, target text/UI key/template, timeout, sampling interval, and whether any navigation step could consume resources.
2. Save a timeline under one new logs folder. Each frame must be saved separately, and each frame's OCR/template checks must use only that same frame.
3. Prefer registered UI template checks (`ui_key`/registered image) over OCR for stylized game text. Use OCR as supporting evidence when templates are unavailable.
4. Record at least: relative timestamp, screenshot path, detector values, confidence/recognized text, pass/fail state, and any blocking page or popup detected.
5. On timeout, classify the failure before editing: navigation/state mismatch, target/crop coordinate issue, recognition/template issue, waiting condition bug, or task/runtime lifecycle bug.
6. For fixes, keep the failure timeline as evidence, make the smallest targeted change, then rerun the same scenario/spec and compare before/after timings.
7. Do not perform clicks, battles, purchases, item use, sweep/challenge, reward claim, or other resource-consuming actions unless the user explicitly confirms that specific step.

## Notes

- Prefer package imports such as `from AutoScriptor.utils.box_grid import make_box_grid, indexof`; top-level `tools` can be shadowed after PaddleOCR imports.
- Keep OCR semantics separate from business semantics.
- If the user says not to peek at a newly added difficult screenshot before implementation, implement first, then inspect it for validation.
