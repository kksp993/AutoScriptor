# Task Authoring And Code Style Reference

Read this when changing task scripts, task APIs, operator dispatch patterns, or project-local coding style.

## Task Authoring

- Keep recognition semantics separate from business semantics.
- A task function returning normally is not always business success if observable progress or completion state says otherwise.
- Use task status/progress APIs when a task can partially complete:
  - `set_task_status("progress", "5/6")`
  - `get_task_status("progress")`
- Import `clear_task_status` from `AutoScriptor.utils.task_state`; it is not currently exported by `from AutoScriptor import *`.
- Prefer `RequestHumanTakeover` for conditions that require user attention or game-state intervention.
- Prefer `TaskRequireReTry` for transient recoverable failures.
- Incomplete progress after retry exhaustion is expected to become `human_takeover_error`; do not treat "function finished" as success if progress remains `5/6`.
- When adding custom tasks under `data/custom_task/`, register them with explicit `@register_task(path_cn="自定义任务/...")`.
- Use `task_doc`, `description`, `beta`, and `debug_mode` metadata instead of persisting UI-only fields into config.

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

