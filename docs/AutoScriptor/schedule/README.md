# 调度索引

[Scheduler](scheduler.md) · [Planning](../tasks/task-ordering-graph-plan.md) · [Runtime](../runtime/lifecycle.md) · [Performance](perf.md) · [Authoring](../tasks/script-authoring.md) · [Background](../runtime/background.md)

未执行：running/error → dispatch_queue → registered/enabled → due/window/weekdays → takeover → retry exhaustion → predecessors。

run_direct never activates; task-list preserves scene. task_call(path) enables/clears takeover/makes due/wakes. New tasks off.
