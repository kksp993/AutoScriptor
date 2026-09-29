---
name: autoscriptor-live-check
description: Runs read-only live checks against the current emulator screen through AutoScriptor's own APIs — capture a frame, run target OCR, check registered UI templates, watch whether a target appears within N seconds. Use when the user asks to online test the current game screen, compare game state, capture a screenshot, verify a UI appears within a timeout, or inspect recognition on the live device.
---

# AutoScriptor Live Check

Read-only live checks run in-process against `AutoScriptor`, using the same device
session and recognition helpers that tasks use. There is no separate CLI: a probe
is a short Python script run with the project venv.

## Required rules

- Follow `docs/agents/project-rules.md` and `docs/agents/online-screenshot-test.md` before live work.
- Record the observed failure or stale evidence first, then fix or rerun.
- One frame per fixed-frame test. Capture once, then pass that frame to every locate/OCR/extract call in the same test. Transition and timeout checks save each sampled frame separately and evaluate each frame only against itself.
- No clicks, task runs, battles, purchases, inventory use, point-currency actions, or other resource-consuming actions without explicit user confirmation for that exact step.
- When OCR confidence is unclear, prefer registered UI template checks (`ui_key` / `mode="img"`); report uncertainty and ask before acting.

## Command setup

Run from the repository root with UTF-8 output:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -X utf8 <probe>.py
```

Put probe scripts, frames, crops, overlays, and result JSON under a fresh
`<logs-root>/<topic>_<timestamp>/` folder (`logs/` in source mode).

## Entry points

### Device session

```python
from AutoScriptor.core.runtime_context import runtime_ctx

mixctrl, mumu = runtime_ctx.ensure_device_session(reason="live check", launch_app=False)
frame = mixctrl.screenshot()          # BGR ndarray, 1280x720 in the landscape contract
runtime_ctx.status_dict()             # {"initialized", "has_mixctrl", "has_mumu", "has_bg"}
```

`launch_app=False` connects without starting the configured game, which is what a
screenshot-only check wants. Standalone scripts that need their own session use
`AutoScriptor.init(start_emulator=..., launch_app=...)` instead.

Frame size is the current device width/height; `AutoScriptor.core.api.getFrameSize()`
returns the convention the helpers assume. `Box(x, y, width, height)` is xywh,
and `box.margin()` expands it before recognition.

### OCR

`ocr()` matches targets and returns boxes; `ocr_for_box()` returns the raw text of
one region.

```python
from AutoScriptor.core.box import Box
from AutoScriptor.recognition.ocr_rec import ocr, ocr_for_box

hits = ocr(frame, ["浏览器", "游戏中心"])   # list[list[Box]], one inner list per target
text = ocr_for_box(frame, Box(0, 0, 1280, 720))
```

Keep the input shape when batching: `Box -> value`, `list[Box] -> list`,
`list[list[Box]] -> nested list`; unreadable slots stay `None`.

### Fixed-frame recognition

Calls that would otherwise take a fresh screenshot accept an injected frame:

| Call | Parameter |
|------|-----------|
| `locate(target, screenshot=frame)` | one frame for the lookup |
| `ui_T(target, screenshot=frame)` | one frame for the presence check |
| `extract_info(target, screenshot_frame=frame)` | one frame for text/image extraction |

`extract_info(..., mode="both")` checks registered `ui_map` images first and runs
OCR only where the image match misses.

### Registered UI templates

Registered keys come from the UI map (`ui_map.csv`), reachable as
`ZmxyOL.nav.map_manager.mm`. Prefer these over OCR for stylized game text; use
OCR as supporting evidence when a key is unavailable.

## Transition And Timeout Checks

For "after entering page A, target B should appear within N seconds":

1. Define the observable target, expected page, timeout, sampling interval, and whether any navigation step consumes resources.
2. Sample on an interval, saving each frame separately with its own overlay and result.
3. Evaluate each frame only against itself; record relative timestamp, frame path, recognized value or template score, and pass/fail.
4. Classify a timeout before editing: navigation/state mismatch, crop/coordinate issue, recognition issue, waiting-condition bug, or task/runtime lifecycle bug.
5. Keep the timeline as evidence, make the smallest targeted change, rerun the same scenario, and compare timings.

## Reporting

```markdown
在线检查结果：通过 / 未通过 / 不确定
- 目录：<logs-root>/<topic>_<timestamp>/
- 帧：screenshot.png（1280x720，xywh）
- 区域：name -> 识别值 / 期望 / 结果
- 耗时：capture ...s，recognition ...s，total ...s
- 安全说明：未执行点击或任务；如需点击或运行任务，需要用户确认。
```
