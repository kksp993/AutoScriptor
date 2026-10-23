# Architecture And Lifecycle Reference

Read this when changing task registration, scheduling, runtime context, or OCR/background recognition.

## TaskRegistry And Task Config

- Runtime task data lives in `tasks.task_register.task_registry`, keyed by display path.
- User task config lives in `cfg["tasks"]` keyed by task **id**; task status/progress lives under `cfg["status"]["tasks"]` keyed by display path.
- Two names per task, never conflated: `id` is the identity (keys `cfg["tasks"]` and `task_ordering`, survives rename), `path` is the display location (tree, execution order, parameter labels), for example `每日任务/村庄/宠物培养`. `id` is the task name (the file stem), so moving a task between folders keeps identity; only a file rename needs `@register_task(id=...)` to pin it. Registering a duplicate id must fail loudly.
- The two key spaces meet only in `retarget_ordering_overlay()`; do not add a second translation point.
- `cfg["tasks"]` is a flat table, not a nested tree. `TaskTreeService.build_task_tree()` builds the WebUI tree from display paths and `flatten_payload_tasks()` flattens it back on save; `catalog.normalize_task_table()` rewrites a legacy nested table at load, before the first `@register_task` runs.
- Do not store or read `fn`, `param_meta`, `param_keys`, `custom`, `task_description`, `task_doc_flow`, `_due`, `id`, or `progress_display` from persisted `cfg["tasks"]`; the injected list lives in `ZmxyOL.accounts.account_store.INJECTED_TASK_FIELDS`. `debug` and `reschedule` are user data and must persist.
- Parameter specs (`tasks/task_params.py`) are the single definition behind the JSON default, the WebUI form description, and execution decoding; `param_meta` is computed from them at projection time and never persisted.
- `TaskTree.is_leaf(node)` / `'on' in node` still identifies a task entry body; it is what the tree builder and payload flattener agree on.
- `Scheduler._collect_due` must filter with `task_registry.has_task(path)`.
- `TaskTreeService.inject_public_task_fields()` hides unregistered tasks in WebUI projections.
- Test task function replacement should use `task_registry.set_fn(path, fn)` or registry helpers, not cfg mutation.

## Reload Boundary

- A task reload re-imports task scripts and rebuilds `tasks` plus `tasks.battle_task_params` (the flow enum aggregates character-script `@flow` registrations).
- It keeps `tasks.task_register` (the registry singleton readers already hold) and the authoring plumbing (`task_params`, `task_state`, `time`). `orchestrator/catalog.py` holds the list.
- `ZmxyOL` is not purged: it owns cross-boundary types such as `TableParam`, and character scripts are refreshed by `reload_character_modules()`. `ZmxyOL.drop_cached_exports()` clears lazily bound re-exports so a star-import serves the post-reload enum.
- The stale-entry prune refuses to run on an empty registry: that state means registration did not reach the registry being read, and pruning there deletes every entry. `normalize_task_table()` never writes an empty table for a non-empty input.
- Reload path clears and rebuilds the registry; check `force_reload_tasks()` before changing reload semantics.
- Built-in task order is the registration order, which is the sorted source path under `tasks/`; there is no per-task order parameter and no order file. The user's drag order lives in `task_ordering`, keyed by task id.
- Custom task scripts live in `data/custom_task/`; their display path is their location there under the `自定义任务` root, so there is no path parameter.
- Runtime battle character scripts live in `data/character/`; old YAML profiles are not the active battle-flow path.
- MuMu adapter attributes and task-authoring helpers may be reached dynamically through `BaseMumuControl.__getattr__`, `from AutoScriptor import *`, or user scripts; static no-call evidence alone is not deletion proof.

Useful docs:

- `docs/AutoScriptor/architecture.md`
- `docs/AutoScriptor/tasks/script-authoring.md`
- `test/task_domain/`

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
- `test/performance/test_bg_monitor.py`

## Scheduler And Progress

- Red human-takeover state is a cooldown, not a permanent block; once `next_exec_time` expires, automatic scheduling can collect the task again.
- A task function returning normally is only success when observable `progress` is complete or absent.
- Incomplete progress after retry exhaustion should become `human_takeover_error`, preserving the progress display.
- `MAX_CONSECUTIVE_ERRORS = 3` is a scheduler-level error pause for ordinary repeated failures, not a replacement for per-task progress/human-takeover semantics.
- Automatic cross-character scheduling should return to the first valid `dispatch_queue` character and confirm login after the full pipeline finishes; direct runs and debug-only runs skip this.

Useful docs:

- `docs/AutoScriptor/schedule/scheduler.md`
