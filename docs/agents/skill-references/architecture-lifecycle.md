# Architecture and lifecycle checklist

Read [architecture](../../AutoScriptor/architecture.md), [runtime](../../AutoScriptor/runtime/lifecycle.md), [scheduler](../../AutoScriptor/schedule/scheduler.md) and [authoring](../../AutoScriptor/tasks/script-authoring.md) before changes.

## Identity and reload

Registry: functions/metadata by display path; flat account config: stable IDs; progress/status: paths. Moves preserve file-stem ID; rename pins old `id`; duplicates fail. Only `retarget_ordering_overlay()` translates ordering IDs to paths. Projection/flattening share `INJECTED_TASK_FIELDS`, separating runtime/user fields. Tests replace registry functions, never cfg. Tree leaf: `'on' in node`.

ParamSpec drives defaults/forms/decoding; TableParam cells preserve edits. Registered wrapper owns ensure_in before body, including debug/continuations; ANYWHERE no-ops. Empty registry never permits pruning; `normalize_task_table()` preserves nonempty input.

Reload preserves registry/authoring singletons (`task_register`, `task_params`, `task_state`, `time`), rebuilds tasks/battle enums, refreshes character modules, clears lazy ZmxyOL exports, preserves TableParam identity. Verify `force_reload_tasks()`/[tests](../../../test/task_domain/test_task_reload_contract.py). Static no-call searches do not prove dynamic/star-import APIs unused.

## Runtime and state

`runtime_ctx` owns live controls/background; no imported snapshots. Readiness checks launch errors, ADB `device`, boot completion. Preserve `MuMuStartupError`; startup archives exclude stale frames/runtime probes. Shared gate separates activation/occupancy. Mutations use `RuntimeController.guard_idle()`; cancellation is cooperative.

Atomic replace; no direct-write fallback/unconditional fsync. Global saves exclude accounts; internal JSON rebaselines watchers, not scripts. Calendar transient; daily restart persists globally in runtime_state, not character status.

## Validation seams

Readiness/role availability/waits share planning; no static topology priority/persisted projections. Exhaustion survives automatic recovery/reload and never unblocks predecessors; count exhausted tasks, not attempts, toward scheduler errors. Incomplete progress is not success; takeover cooldown expires. Enforce startup-error limits inside pipelines; preserve retries/cancellation. Completed automatic cross-character runs return/login to first valid dispatch character; direct/debug-only runs skip.

Use scoped background callbacks/shared frames/bounded waits; battle/device rules remain in domain docs. No host-priority/power workaround or global capture/input lock.
