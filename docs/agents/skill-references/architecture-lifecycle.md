# Architecture And Lifecycle Reference

Read this when changing task registration, scheduling, runtime context, OCR/background recognition, or VLM target APIs.

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
- Custom task scripts live in `data/custom_task/` and must use explicit `path_cn`.
- Runtime battle character scripts live in `data/battle_character/`; old YAML profiles are not the active battle-flow path.

Useful docs:

- `docs/AutoScriptor/refactor/task_registry_decouple.md`
- `test/test_task_registry/`

## Runtime Context

- `services.core.runtime_context.runtime_ctx` owns `mixctrl`, `mumu`, background monitor, and VLM client lifecycle.
- WebUI startup, refresh, normal polling, and default diagnostics must not initialize device sessions.
- Do not patch stale global controls directly when runtime refresh is required.
- Scheduler and direct execution paths should use `runtime_ctx.refresh()` or the established lifecycle service.
- Use `RuntimeController.guard_idle()` before config/task/account writes that cannot happen during execution.
- Stop paths are cooperative: `TaskManager.request_cancel()`, `Scheduler.request_stop()`, and cancellable `AutoScriptor.sleep()`.

Useful docs:

- `docs/AutoScriptor/runtime/lifecycle.md`
- `docs/AutoScriptor/refactor/runtime_context_api.md`

## OCR And Background Performance

- OCR default scale is `1.0`; old scale fallback behavior was removed.
- `_raw_ocr_cached()` provides short frame-level cache behavior.
- Background monitor should share one screenshot per round where possible.
- Background monitor default interval is `1.0` second.
- Use `bg.scope()` for task-local callbacks and `bg.protect_clear()` around battle critical sections.
- `allow_concurrent` callbacks scan before ordinary priority-sorted callbacks.
- `ui_T`/`locate` support screenshot reuse.
- Avoid per-box OCR loops when batch extraction can preserve shape.

Useful docs:

- `docs/AutoScriptor/refactor/ocr_optimize.md`
- `docs/AutoScriptor/refactor/bg_monitor_reform.md`
- `test/test_perf_optimize/`

## VLM Target API

- Use `V("description", box=Box(...))` as the VLM positioning entry, parallel to `I()`, `T()`, and `B()`.
- Do not add alternate VLM target factories unless the existing target API cannot express the use case.

Useful docs:

- `docs/AutoScriptor/refactor/vlm_target_api.md`

## Scheduler And Progress

- Red human-takeover state is a cooldown, not a permanent block; once `next_exec_time` expires, automatic scheduling can collect the task again.
- A task function returning normally is only success when observable `progress` is complete or absent.
- Incomplete progress after retry exhaustion should become `human_takeover_error`, preserving the progress display.
- `MAX_CONSECUTIVE_ERRORS = 3` is a scheduler-level error pause for ordinary repeated failures, not a replacement for per-task progress/human-takeover semantics.
- Automatic cross-character scheduling should return to the first valid `dispatch_queue` character and confirm login after the full pipeline finishes; direct runs and debug-only runs skip this.

Useful docs:

- `docs/AutoScriptor/schedule/scheduler.md`


