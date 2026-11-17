# 任务编写

## 注册与身份

Imports: AutoScriptor/ZmxyOL; import ANYWHERE before registration. `_*.py` unregistered. Filename ID survives moves; renames pin ID. Registry=paths, storage=IDs; `retarget_ordering_overlay()` translates.

`ensure_in`: actual registered entry/nonempty OR-list/tuple; wrapper navigates before attempts/continuations/debug. No redundant entry/detour; retain transitions/recovery. `ANYWHERE` (ZmxyOL, 任意位置) returns without recognition/App/cache access; replaces None, cannot mix locations. Registration=device-free. Preferences inherit real entries; ANYWHERE=empty. [Planning](task-ordering-graph-plan.md).

description=docstring headline; remainder=help. deprecated hides/prunes. Private kwargs persist; official typos fail. debug/reschedule: user>author. [Lifecycle](../schedule/scheduler.md).

## 分次执行

`set_task_next_run(180)`: continuation seconds; last wins, normal uncancelled return commits. Final stage omits request. Reschedule unchanged; task enabled/scheduler running required.

ZmxyOL `set_task_status("left_planted", True)` / `get_task_status("left_planted", False)`: arbitrary JSON tags, account/character/task-isolated; saved immediately, survive retries/reload. Checkpoint verified results, not clicks. Reads copy; persist edits with set. `progress` is executor-managed.

Expiry follows reschedule: daily 05:00, weekly Monday 05:00, N-hours from execution/reanchored at completion, once manual reset. Continuation/windows/weekdays never postpone expiry: 04:58+180s reads defaults. Reads hide expiry without writes; execution/write clears it. Changed mode/hours or undated periodic tags invalidate cycles. [Source](../../../tasks/task_state.py).

## 参数

[ParamSpec](../../../tasks/task_params.py): signature → json_default/describe/decode. value/enum/enum_list/table embed options. Storage: enum names/lists/table dict-of-dicts; decode restores types. New cells preserve edits. Extend specs; set_enum_option_filter filters.

`params_doc={"diff": "难度"}`: signature keys → nonempty labels, required for built-ins. Omitted=keys; invalid=reject before mutation. Registry-only/reloadable/stripped on save. Tables: `column_labels`. [Tests](../../../test/task_domain/test_task_params_doc.py).

## Editor 与识别

Debug: authorized registered runs/evidence/repair/rerun. [Procedure](../../agents/online-screenshot-test.md).

Snippets generate declaration/signature/enums/defaults/docstring/params_doc, not navigation; UTF-8/full reload. custom_task_load_errors blocks pruning/save; repair, never clear data.

Inline T/I/B/margins; native coordinates; portrait `frame_size`, never global `setFrameSize`.

[API](../reference/API.md): seq_click verifies successor/final state. Editor lists: commas/click/refresh; simulation=marks, real input requires unlock/gate; elsewhere insertion-only. Coordinates≠rendering.

[Safety](script-authoring-safety.md), [battle](battle-flows.md).
