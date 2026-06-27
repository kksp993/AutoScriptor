# Architecture And Lifecycle Reference

Read this when changing task registration, scheduling, runtime context, or OCR/background recognition.

## TaskRegistry And Task Config

- Runtime task data lives in `AutoScriptor.utils.task_registry.task_registry`.
- User task config lives in `cfg["tasks"]`; task status/progress lives under `cfg["status"]["tasks"]`.
- Link both by slash path, for example `每日任务/村庄/宠物培养`.
- Do not store or read `fn`, `order`, `param_meta`, `param_keys`, `beta`, `custom`, `debug_mode`, `task_description`, `task_doc_flow`, `_due`, or `progress_display` from persisted `cfg["tasks"]`.
- Leaf detection is `TaskTree.is_leaf(node)` or `'on' in node`.
- `Scheduler._collect_due` must filter with `task_registry.has_task(path)`.
- `TaskTreeService.inject_public_task_fields()` hides unregistered leaf tasks in WebUI projections.
- Test task function replacement should use `task_registry.set_fn(path, fn)` or registry helpers, not cfg mutation.
- Reload path clears and rebuilds the registry; check `force_reload_tasks()` before changing reload semantics.
- `ZmxyOL/task/**/_order.txt` is an explicit source ordering input; task loading should not rewrite those files during normal startup.
- Custom task scripts live in `data/custom_task/` and must use explicit `path_cn`.
- Runtime battle character scripts live in `data/battle_character/`; old YAML profiles are not the active battle-flow path.
- MuMu adapter attributes and task-authoring helpers may be reached dynamically through `BaseMumuControl.__getattr__`, `from AutoScriptor import *`, or user scripts; static no-call evidence alone is not deletion proof.

Useful docs:

- `docs/AutoScriptor/architecture.md`
- `docs/AutoScriptor/tasks/script-authoring.md`
- `test/test_task_registry/`

## Runtime Context

- `services.core.runtime_context.runtime_ctx` owns `mixctrl`, `mumu`, and background monitor lifecycle.
- WebUI startup, refresh, normal polling, and default diagnostics must not initialize device sessions.
- Do not patch stale global controls directly when runtime refresh is required.
- Scheduler and direct execution paths should use `runtime_ctx.refresh()` or the established lifecycle service.
- Treat `MuMuManager launch` success as command acceptance only; wait for the configured ADB device and Android boot completion before package resolution, App launch, or other Android-side checks.
- Treat NemuIpc as a single native IPC lane. Background screenshots, task clicks, touch release, and connection release must use the `NemuIpc` wrapper methods so the native calls are serialized instead of hidden behind extra retries.
- Do not reintroduce host-level boost for runtime stability. Source execution must not change Windows power state, CPU affinity, process priority, thread priority, or MuMu process priority, and must not restore `AutoScriptor.utils.perf` as a compatibility shell.
- Use `RuntimeController.guard_idle()` before config/task/account writes that cannot happen during execution.
- Stop paths are cooperative: `TaskManager.request_cancel()`, `Scheduler.request_stop()`, and cancellable `AutoScriptor.sleep()`.

Useful docs:

- `docs/AutoScriptor/runtime/lifecycle.md`

## OCR And Background Performance

- OCR default scale is `1.0`; explicit non-`1.0` calls may retry at `1.0` when no target is found.
- `_raw_ocr_cached()` provides short frame-level cache behavior.
- Background monitor should share one screenshot per round where possible.
- Background monitor default interval is `1.0` second.
- Use `bg.scope()` for task-local callbacks and `bg.protect_clear()` around battle critical sections.
- `allow_concurrent` callbacks scan before ordinary priority-sorted callbacks.
- `ui_T`/`locate` support screenshot reuse.
- `click(..., until=...)` owns the default 0.5 second polling interval when callers omit `interval`; do not spread that default through task scripts. Plain `click()` remains immediate by default.
- `Hero.way_to_exit()` should keep exit detection in `bg.scope()` and keep movement in the main thread: reach the far right, move left near the exit, check for an immediate hit, pulse-search, hold briefly on an exit sign, and micro-adjust only after a failed hold. Do not move OCR throttling, target classification, or private detector threads back into this method.
- Avoid per-box OCR loops when batch extraction can preserve shape.

Useful docs:

- `docs/AutoScriptor/runtime/background.md`
- `test/test_perf_optimize/test_bg_monitor.py`

## Scheduler And Progress

- Red human-takeover state is a cooldown, not a permanent block; once `next_exec_time` expires, automatic scheduling can collect the task again.
- A task function returning normally is only success when observable `progress` is complete or absent.
- Incomplete progress after retry exhaustion should become `human_takeover_error`, preserving the progress display.
- `MAX_CONSECUTIVE_ERRORS = 3` is a scheduler-level error pause for ordinary repeated failures, not a replacement for per-task progress/human-takeover semantics.
- Automatic cross-character scheduling should return to the first valid `dispatch_queue` character and confirm login after the full pipeline finishes; direct runs and debug-only runs skip this.

Useful docs:

- `docs/AutoScriptor/schedule/scheduler.md`


