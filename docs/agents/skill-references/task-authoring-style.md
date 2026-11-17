# Task authoring checklist

Read [authoring](../../AutoScriptor/tasks/script-authoring.md), [safety](../../AutoScriptor/tasks/script-authoring-safety.md) and [API](../../AutoScriptor/reference/API.md).

- Inline `T/I/B/Box(...).margin()` at click/sequence/predicate/wait/extraction sites; no hoisted targets/constants/dictionaries/wrappers. Name OCR/counts/business state descriptively.
- Required `ensure_in`: actual entry/OR-list/imported `ANYWHERE`, never None. Wrapper navigates before attempts/debug/continuations; remove duplicates/detours, retain transitions/recovery. Helper `entry_ready=True` reuses confirmed entry only. Registration=device-free.
- Built-in parameters require task-local `params_doc`; no frontend label maps. Validation/fallback/table columns: authoring.
- Built-ins `tasks/`; locals `data/custom_task/` -> `自定义任务/...`. Shared underscore helpers: adjacent/full imports/unregistered. No placeholders/unreachable flows/catch-print-exit tails; [registered runs/evidence](../online-screenshot-test.md), not click clones.
- Prefer aggregate APIs; `tasks.task_state.clear_task_status` clears tags. Incomplete progress≠success. `TaskRequireReTry`=recoverable; `RequestHumanTakeover`=intervention, never permanent exclusion.
- Expected wait: `set_task_next_run(seconds)` then return; not sleep/retry/reschedule mutation. Omit only after verified completion.
- Tags: get/set_task_status, not locals/progress. Verify actions; test expiry/cross-05:00/reload/isolation. Background callbacks capture task_path on the execution thread and pass it explicitly.
- Separate OCR/business defaults. Scalar `pretext/posttext/prenum/postnum` fail unmatched, never invent zero; preview/execution/saved scripts share implementation.
- Multiple targets use tuple/list; second argument=timeout/options. `seq_click`: per-step timeout/successor checks/final-only `until`; B never proves transition. Popup closing: all x/x-in, located Box, re-detect/rotate overlaps, 20-close budget, read-only final check/bounded loading.

## Style and dispatch

One action/line, including generated Python: no wrapped arguments. Use `ascli transform` for `.as`; test complete transitions, not isolated clicks. No aliases/redundant coercions/new globals/dead code/unrecovered broad catches. Assertions are programmer invariants, not recoverable runtime states. Preserve native portrait dimensions.

Extend existing dispatch: decorator/function-name identity, `dispatch(name, instance, ...)`, instance-type routing, trailing defaults, established `__all__`; not compulsory abstraction.
