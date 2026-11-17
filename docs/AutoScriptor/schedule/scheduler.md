# 调度与任务生命周期

[Source](../../../orchestrator/scheduler.py), [executor](../../../orchestrator/task_manager.py), [model](../../../orchestrator/model.py), [authoring](../tasks/script-authoring.md), [planning](../tasks/task-ordering-graph-plan.md), [runtime](../runtime/lifecycle.md).

## 时间与状态

Defaults on=False/next_exec_time=0; preserve edits. reschedule: user > author > once. Once disables; daily=next local 05:00, weekly=Monday 05:00, integer=hours. window=[start,end), weekdays=1..7 defer execution. Invalid registration fails; directories never schedule.

Due=enabled/registered/elapsed/allowed window/day, no takeover cooldown/exhaustion. Event.wait nearest time/default3600s; wake interrupts only. dispatch_queue: empty=no execution, otherwise first due character; invalidate login/projection, preserve registry. Auto completion logs into first valid character; direct/debug skip.

pending=off,running=activated,error=paused; running≠busy. activate cannot leave error. Manual reset/start clears exhaustion; automatic 30min recovery resets environment errors only. Error wakes≤60s.

## 管线与重试

Verified characters: refresh/login/execute/save/project, boundary reload. Locate after readiness/login; ambiguity=unknown. Unconfirmed candidates use list/selected policy; poll last_selection.

task_list preserves queue/login cache, skips login/daily restart; force_login wins. Debug skips login/restart/recovery/retry, debug-only post_execution, not readiness; user override wins. Neither bypasses registered ensure_in: wrapper navigates before body, failures use existing retry/cancel handling; ANYWHERE preserves scene.

max_attempts=3 including first; migrate max_retry+1. Executor inline retries; scheduler max_attempts=1/attempt_offset rounds. Exhaustion survives reload/recovery until next_exec_time advances. Count exhausted tasks, not attempts. Three distinct failures/startup/crashes pause; repeats/pending retries/takeover/cancel excluded. Success clears errors. [Tests](../../../test/orchestration/test_scheduler_retry_rounds.py).

Startup: auto waits 10/20s, stop third regardless attempts/plan; inactive direct fails once. Archive stage=device_startup without stale frames/OCR; cancel never retries/counts/archives.

## 进度与收尾

Clear progress per attempt. Incomplete "5/6", [5,6], {done,total} → TaskRequireReTry; unparseable=display-only. Exhausted incomplete/RequestHumanTakeover → human_takeover/error/at+reschedule. Cooldown red, due pending; success clears takeover/progress. Ordinary failure not red. Re-enable/reset clears takeover/status/cycle/continuation/time=0.

task_state tags/task_cycles share task_schedule base periods; reads filter expiry, execution/writes clear it. Continuation/windows/weekdays never extend deadlines. [Semantics](../tasks/script-authoring.md).

set_task_next_run(seconds): normal uncancelled return commits continuation_pending/next_exec_time/progress; no success/failure count. Obey windows/weekdays, block successors only. Survives restart/reload; final stage retains reschedule. Direct runs never activate scheduler. [Tests](../../../test/orchestration/test_task_continuation.py).

Completed/failed totals trigger notification/post_execution; continuation-only preserves scene. none/null keeps scene, close_game_only closes App, close_mumu both, goto_main home. CharacterReports freezes identity/run-id, replaces retries; deferred≠interrupted/completed. Async delivery never affects retries. [QQ](../operations/qq-notifications.md).
