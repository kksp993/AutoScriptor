# Task Authoring And Code Style Reference

Read this when changing task scripts, task APIs, operator dispatch patterns, or project-local coding style.

## Task Authoring

- Write `T(...)`, `I(...)`, `B(...)` and their regions directly where the task uses them: `click`, `seq_click`, `ui_T/ui_F`, waits and `extract_info`. Do not predeclare target variables (such as `awakening_entry`, `water_button` or `amount_button`), collect targets at the function top, or hide them behind constants/dictionaries/helpers merely to deduplicate. Repeat the target at each call site; OCR results, computed counts and real business state still belong in descriptive variables.
- Keep recognition semantics separate from business semantics.
- OCR edge parsing uses the public, device-independent `pretext/posttext/prenum/postnum` callbacks: strip, anchored regex, integers for numeric results. Keep editor preview, immediate globals and saved-task star imports on the same implementation; never define generated callbacks only inside a route or substitute 0 for a failed match. These callbacks handle scalar strings, not grids.
- A task function returning normally is not always business success if observable progress or completion state says otherwise.
- Use task status/progress APIs when a task can partially complete:
  - `set_task_status("progress", "5/6")`
  - `get_task_status("progress")`
- Import `clear_task_status` from `tasks.task_state`; it is not exported by `from AutoScriptor import *`.
- Prefer `RequestHumanTakeover` for conditions that require user attention or game-state intervention.
- Prefer `TaskRequireReTry` for transient recoverable failures.
- Wrap multiple recognition targets in tuple/list for `locate`, `ui_T`, `wait_for_appear`, and `click`; a second positional argument is usually a timeout or click option, not another target.
- Popup recovery must retain all X candidates (both `x` and `x-in` across the frame), click one located Box and re-detect, and rotate away from already attempted overlapping positions. A visible background X may be blocked by a foreground dialog. Keep the shared 20-close budget, read-only final check, and bounded loading wait; test two-layer pages at different positions rather than only a single matching X.
- For targets that appear sequentially, use `seq_click([...])`: each step has its own timeout (default 10 seconds), waits for its successor, and only the final step receives the caller's `until`. Preserve the transition Box for the next first click, but re-locate on retries. A plain B is always present, not proof of a page change; a colored B still requires detection. Editor sequence-target generation clicks once through the existing guarded remote path (virtual mode only marks), without adding a second click statement; generation inside `until` never clicks.
- Incomplete progress after retry exhaustion is expected to become `human_takeover_error`; do not treat "function finished" as success if progress remains `5/6`.
- A custom task's display path is its location under `data/custom_task/`, prefixed with the `自定义任务` root, so `data/custom_task/背包清空/进阶仙宝.py` registers as `自定义任务/背包清空/进阶仙宝`. There is no path parameter.
- Built-in tasks maintained by source Git should live in `tasks/`; user-editable local experiments belong in `data/custom_task/`.
- Do not leave incomplete debug placeholders registered as built-in tasks. Scripts that hard-stop with `raise Stop here`, print internal tables, or keep the real flow unreachable should be deleted or kept unregistered.
- Do not add task-file direct-run wrappers with broad `try/except`, `traceback.print_exc()`, `bg.stop()`, or `exit(0)`; use WebUI direct run and the task's `debug` setting for on-device debugging.
- The authoring surface is `id`, `reschedule`, `debug`, `description`, `deprecated`, required `ensure_in`, and optional `preferred_locations` / `after_tasks`. Long documentation belongs in the function docstring; remaining key=value arguments are task-private data. Declare the real registered entrypoint, including helper navigation, not the directory or final return location. Only scene-preserving/external-App debug tasks may explicitly use `ensure_in=None`; missing/empty entries are errors. Declaration does not navigate; omitted preferences default to it, while explicit preferences remain separate. The graph builds dependency backbones, then attaches independent cards by directed entrypoint distance; these visual attachments never add dependencies or promise an execution route.

Useful docs:

- `docs/AutoScriptor/tasks/script-authoring.md`
- `docs/AutoScriptor/tasks/script-authoring-safety.md`

## Register-Dispatch Pattern

Use this pattern only where the codebase already has operator-like dispatch:

- Register via decorator.
- Function name is the default operator name; pass an explicit name only when needed.
- Consumer calls a single `dispatch(name, instance, ...)`.
- Route by instance type in the dispatcher.
- Keep dispatcher parameters at the end with defaults.
- Export public operators from `__init__.py` when that package already uses explicit `__all__`.

## Local Style Guidance

Use judgment; do not apply these as mechanical lint rules.

- Prefer one semantic action per line.
- Remove duplicate variable names for the same semantic value.
- Prefer context propagation through existing kwargs or context objects over new globals.
- Avoid redundant `str()`/`int()`/`float()` coercions when the source type is guaranteed.
- Do not wrap code in broad defensive `try/except` without a recovery action.
- Use `assert` only for programmer invariants, not user/game/runtime recoverable states.
- Delete dead code instead of preserving commented branches.
