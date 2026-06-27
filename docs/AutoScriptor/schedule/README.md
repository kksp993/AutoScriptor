# 调度与任务系统索引

本目录只保留当前调度事实和性能边界，旧实现说明不作为维护依据。

| 文档 | 内容 |
|------|------|
| [scheduler.md](scheduler.md) | 任务注册、跨角色调度、retry、人工接管、progress、WebUI 状态投影 |
| [perf.md](perf.md) | 源码运行的主机性能策略边界和已移除的 boost 行为 |

## 快速判断任务为什么没执行

按顺序检查：

1. 调度器是否为 `running`，且不在 `error`。
2. 当前账号是否有 `dispatch_queue`；调度器只执行队列内角色。
3. 任务路径是否存在于 `TaskRegistry`；未注册叶子不会显示/执行。
4. 任务是否 `on=True`。
5. `next_exec_time` 是否到期。
6. 是否被 `sched_window_hours` 或 `allowed_weekdays` 推迟。
7. 是否处于人工接管冷却：`human_takeover_error` 存在且 `now < next_exec_time`。
8. 是否在本次调度激活周期内 retry 耗尽。

## 立即执行一个任务

WebUI 直接运行会走 `Scheduler.run_direct()`，复用同一登录、设备和 retry 管线，但不会激活后台调度器。

代码内需要把任务设为下一轮自动拾取时用：

```python
scheduler.task_call("每日任务/村庄/宠物培养")
```

它会开启任务、清除人工接管标记、把 `next_exec_time` 设为当前时间并 `wake()`。

## 新任务默认值

首次注册新叶节点默认：

```json
{"on": false, "next_exec_time": 0, "params": {...}}
```

已有任务保留用户配置。WebUI 保存会剥离运行时字段。

## 相关文档

- [任务编写](../tasks/script-authoring.md)
- [后台监听](../runtime/background.md)
- [运行生命周期](../runtime/lifecycle.md)
