---
name: autoscriptor-live-check
description: Validates AutoScriptor scripts through existing registered task execution and failure logs, screenshots, and recordings; performs read-only fixed-frame OCR/template checks when requested. Use for task failures, script debugging, live emulator testing, screenshot recognition, or target timeouts. Reuses login/navigation helpers and the backend execution gate instead of rebuilding workflows as individual clicks; requires authorization for real actions.
---

# AutoScriptor Live Check

应该复用现有函数直接执行任务，失败后查日志、截图和录屏，而不是重新拼一套单步点击。

Task debugging and read-only recognition are different workflows. Use the existing
registered execution lifecycle for the former; fixed-frame project APIs for the
latter. This skill is automatically applicable to both, not permission to run tasks.

## Required rules

- Follow [shared rules](../../../docs/agents/project-rules.md) and the
  [live-check contract](../../../docs/agents/online-screenshot-test.md).
- Record the observed failure or stale evidence first, then fix or rerun.
- Check occupancy. An existing backend owns device access: use its execution gate,
  never a second controller or standalone device session alongside it.
- One frame per fixed-frame test. Capture once, then pass that frame to every locate/OCR/extract call in the same test. Transition and timeout checks save each sampled frame separately and evaluate each frame only against itself.
- Read-only inspection grants no action permission. Confirm the requested task,
  character, parameters, resource cost and authorized scope before execution.
  Debug is real execution, not a dry run; navigation-only approval does not allow
  awakening, watering, claiming, purchases or other consumption. If unclear, stop.
- When OCR confidence is unclear, prefer registered UI template checks (`ui_key` / `mode="img"`); report uncertainty and ask before acting.

## Task/script debugging: execute first, inspect failure evidence

1. Locate the registered task and its existing login, `ensure_in`, navigation and
   business helpers. Reuse them unchanged for the first authorized reproduction.
   Do not clone the task into Editor snippets, remove its decorator with AST,
   replay its clicks, or create another command-line task runner.
2. Inspect existing logs/archives before another run. If current evidence already
   isolates the failure, avoid repeating resource-consuming steps just to observe
   it again. Otherwise run only the requested task, not the scheduler's full queue.
3. Use the running WebUI backend at its configured address. Check
   `GET /api/runtime/snapshot`; preserve credential unlock, registration, parameter
   decoding, the shared gate, cancellation, tracing and normal status projection.
   HTTP 403/409 is a blocker, not permission to bypass the lifecycle.
4. For a single diagnostic attempt, use the task's effective `debug` setting.
   A user override takes precedence over the decorator default. If a temporary
   override is necessary, remember its original value AND whether it existed;
   save through existing task configuration APIs, never raw account/config writes.
   Debug skips ordinary failure recovery/retries and debug-only post-execution
   cleanup; it does not suppress device readiness, business actions or task status
   persistence. It normally skips automatic login: when login is required, reuse
   the approved existing login path and verify the intended character first.
5. Use the existing task execution endpoint: `POST /api/run` with the registered
   task path and `activate_scheduler=false`. Set `execution_source="task_list"`
   only when deliberately preserving the correct current login/scene. Do not add
   unsupported overrides such as HTTP `force_login`, or invoke a registry function
   directly outside its executor. Verify the current implementation before use.
6. Wait for completion through `/api/run/status` and the runtime snapshot. An
   accepted run request, client exit code, delivered input or absent new archive
   is NOT business success. Match this run's task/time to its completion log,
   progress, failure and observable game result.
7. On failure, inspect `error.log`, traceback, `current_screenshot.png`, relevant
   `debug_screenshots/`, recognition/action traces and any retained recording.
   Use logged artifact paths under the resolved logs root, not the newest unrelated
   directory. Ordinary exceptions are archived; cancellation, requested retries
   and human takeover have different paths. Successful runs may discard recordings;
   missing video is not proof of success or permission to fabricate evidence.
8. Name the violated assumption, make the smallest fix in the existing task/helper,
   and rerun through the SAME execution entrypoint with comparable conditions.
   Offline mocks must not assume the disputed page transition or recognition always
   succeeds. Label offline regression and live business completion separately.
9. In `finally`, wait until this run has released occupancy before restoring any
   temporary debug override through the existing config lifecycle. Read fresh
   state, verify account/character/task identity and restore only the owned field;
   do not replay a stale full config or overwrite intervening edits. Preserve real
   progress/status changes. Stop only this owned run if necessary; disclose failed
   cleanup, unresolved conflicts, remaining overrides or occupied workers.

Sources: [task endpoints](../../../backend/webui/routes/tasks.py),
[task executor](../../../orchestrator/task_manager.py),
[debug resolution](../../../orchestrator/model.py),
[lifecycle semantics](../../../docs/AutoScriptor/schedule/scheduler.md).
These are the implementation references, not scripts to execute directly.

## Read-only recognition: setup

Run from the repository root with UTF-8 output:

```powershell
$env:PYTHONIOENCODING='utf-8'
& ".venv/Scripts/python.exe" -X utf8 "<logs-root>/<topic>_<timestamp>/probe.py"
```

Put probe scripts, frames, crops, overlays, and result JSON under a fresh
`<logs-root>/<topic>_<timestamp>/` folder (`logs/` in source mode).
Resolve the root through `AutoScriptor.utils.paths.get_logs_root()`. Do not commit
runtime evidence, account identifiers or secrets. A thin HTTP client may submit and
monitor an existing task; it must not contain a replacement game-control workflow.

## Read-only entry points

### Device session

The following standalone example is allowed only when no existing backend owns
the device. Otherwise use its gated Editor/recognition APIs in that process.

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

Registered keys come from `ZmxyOL/assets/config/ui_map.csv` and the current
`AutoScriptor.utils.ui_map.ui_manager.get_ui()` table. Prefer `I(key)` for stylized
game text; use OCR as supporting evidence when a template is unavailable.

## Transition And Timeout Checks

Only use a targeted probe after the task's existing evidence leaves a specific
question unresolved, or for an explicitly requested read-only recognition check.
State that question and the missing reusable API first. Reuse existing navigation;
never explore unrelated pages by trial clicks or build a parallel business flow.
Any additional real action still requires authorization.

For "after entering page A, target B should appear within N seconds":

1. Define the observable target, expected page, timeout, sampling interval, and whether any navigation step consumes resources.
2. Sample on an interval, saving each frame separately with its own overlay and result.
3. Evaluate each frame only against itself; record relative timestamp, frame path, recognized value or template score, and pass/fail.
4. Classify a timeout before editing: navigation/state mismatch, crop/coordinate issue, recognition issue, waiting-condition bug, or task/runtime lifecycle bug.
5. Keep the timeline as evidence, make the smallest targeted change, rerun the same scenario, and compare timings.

## Reporting

For task runs, report task/entrypoint, authorized scope, actual business result,
failing stage, log/screenshot/video paths (or their absence), fix/rerun evidence,
and whether overrides and occupancy were restored. Never call a mock-only fix a
live pass. For read-only checks, use:

```markdown
在线检查结果：通过 / 未通过 / 不确定
- 目录：<logs-root>/<topic>_<timestamp>/
- 帧：screenshot.png（1280x720，xywh）
- 区域：name -> 识别值 / 期望 / 结果
- 耗时：capture ...s，recognition ...s，total ...s
- 安全说明：未执行点击或任务；如需点击或运行任务，需要用户确认。
```
