# Architecture And Lifecycle Reference

Read this when changing task registration, scheduling, runtime context, or OCR/background recognition.

## TaskRegistry And Task Config

- Runtime task data lives in `tasks.task_registry.task_registry`.
- User task config lives in `cfg["tasks"]`; task status/progress lives under `cfg["status"]["tasks"]`.
- Link both by slash path, for example `每日任务/村庄/宠物培养`.
- Do not store or read `fn`, `order`, `param_meta`, `param_keys`, `beta`, `custom`, `debug_mode`, `task_description`, `task_doc_flow`, `_due`, or `progress_display` from persisted `cfg["tasks"]`.
- Parameter specs (`tasks/task_params.py`) are the single definition behind the JSON default, the WebUI form description, and execution decoding; `param_meta` is computed from them at projection time and never persisted.
- Leaf detection is `TaskTree.is_leaf(node)` or `'on' in node`.
- `Scheduler._collect_due` must filter with `task_registry.has_task(path)`.
- `TaskTreeService.inject_public_task_fields()` hides unregistered leaf tasks in WebUI projections.
- Test task function replacement should use `task_registry.set_fn(path, fn)` or registry helpers, not cfg mutation.

## Reload Boundary

- A task reload re-imports task scripts and rebuilds `tasks` plus `tasks.battle_task_params` (the flow enum aggregates character-script `@flow` registrations).
- It keeps `tasks.task_registry` (the registry singleton readers already hold) and the authoring plumbing (`task_params`, `task_register`, `task_state`, `translations`, `time`). `orchestrator/catalog.py` holds the list.
- `ZmxyOL` is not purged: it owns cross-boundary types such as `TableParam`, and character scripts are refreshed by `reload_character_modules()`. `ZmxyOL.drop_cached_exports()` clears lazily bound re-exports so a star-import serves the post-reload enum.
- The stale-leaf prune refuses to run on an empty registry: that state means registration did not reach the registry being read, and pruning there deletes every leaf.
- Reload path clears and rebuilds the registry; check `force_reload_tasks()` before changing reload semantics.
- `tasks/**/_order.txt` is an explicit source ordering input; task loading should not rewrite those files during normal startup.
- Custom task scripts live in `data/custom_task/` and must use explicit `path_cn`.
- Runtime battle character scripts live in `data/character/`; old YAML profiles are not the active battle-flow path.
- MuMu adapter attributes and task-authoring helpers may be reached dynamically through `BaseMumuControl.__getattr__`, `from AutoScriptor import *`, or user scripts; static no-call evidence alone is not deletion proof.

Useful docs:

- `docs/AutoScriptor/architecture.md`
- `docs/AutoScriptor/tasks/script-authoring.md`
- `test/test_task_registry/`

## Runtime Context

- `AutoScriptor.core.runtime_context.runtime_ctx` owns `mixctrl`, `mumu`, and background monitor lifecycle.
- WebUI startup, refresh, normal polling, and default diagnostics must not initialize device sessions.
- Do not patch stale global controls directly when runtime refresh is required.
- Scheduler and direct execution paths should use `runtime_ctx.refresh()` or the established lifecycle service.
- Treat `MuMuManager launch` success as command acceptance only; wait for the configured ADB device and Android boot completion before package resolution, App launch, or other Android-side checks.
- NemuIpc is two lanes: `NemuIpcImpl.io_lock` guards connect/disconnect/reconnect and the reused capture buffer, while `NemuIpc._ipc_lock` serialises compound gestures only. Screenshots and input can run concurrently (verified), so keep background screenshots, task clicks, touch release, and connection release on the `NemuIpc` wrapper methods, but do not add a global cross-instance lock or extra fallback sleeps.
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
- `Hero.way_to_exit()` should keep exit detection in `bg.scope()` and keep movement in the main thread: reach the far right, move left near the exit, register the `战斗-离开标记` countdown marker only after positioning, pulse-search, hold on the countdown `秒`, and micro-adjust only after a failed hold. Use `mumu` for these exit long-press movements and switch back to `nemu` after each movement for recognition. Do not use `还有`/`秒` as the completion `until`, and do not move OCR throttling, target classification, or private detector threads back into this method.
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
