# Scheduler 与任务执行生命周期

本文记录当前调度器、任务注册、重试、人工接管和 WebUI 状态投影的实际约定。它是维护跳表，不是旧实现说明。

## 组件边界

| 组件 | 职责 |
|------|------|
| `ZmxyOL/task/task_register.py` | `@register_task` 注册任务路径，维护用户配置叶节点，并把运行时元数据写入 `TaskRegistry` |
| `AutoScriptor/utils/task_registry.py` | 运行时注册表，保存 `fn/order/param_meta/doc/debug_mode`，不持久化 |
| `services/core/scheduler.py` | 后台线程、动态等待、跨角色收集到期任务、调度周期 retry、状态机 |
| `services/core/task_manager.py` | 单任务执行、参数恢复、任务内 retry、进度判定、人工接管标记、执行后时间更新 |
| `AutoScriptor/utils/task_state.py` | 当前任务本地状态 API，例如 `progress` |
| `services/webui/task_tree_service.py` / `server.py` | 将任务树投影为 WebUI 状态、进度、到期与错误展示 |

## 任务注册与数据归属

任务是一个被 `@register_task` 装饰的 Python 函数。内置任务来自 `ZmxyOL/task/`；自定义任务来自 `data/custom_task/`，并需要显式 `path_cn`。

注册数据分两层：

| 数据 | 保存位置 | 持久化 | 说明 |
|------|----------|--------|------|
| `on`、`next_exec_time`、`params`、`next_exec_offset_hours`、`sched_window_hours`、`allowed_weekdays` | `cfg["tasks"]` | 是 | 用户配置和调度配置 |
| `fn`、`order`、`param_meta`、`param_keys`、`beta`、`custom`、`doc_flow`、`description`、`debug_mode` | `TaskRegistry` | 否 | 运行时元数据，重载任务时重建，WebUI 投影为 `task_doc_flow` / `task_description` 等字段 |
| `progress` 等任务运行状态 | `cfg["status"]["tasks"][task_path]` | 是 | 跟随账号/角色配置 |

首次注册一个新任务叶节点时默认 `on=False`、`next_exec_time=0`；已有任务会保留用户配置，并补齐缺失字段。WebUI 保存任务时会剥离 `fn/order/param_meta/_due` 等运行时字段。

## 任务叶节点字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `on` | bool | 是否启用任务 |
| `next_exec_time` | float | 下次可执行 Unix 时间戳，`0` 表示立即可执行 |
| `params` | dict | 任务函数参数，执行前按 `param_meta` 恢复枚举和 `TableParam` |
| `next_exec_offset_hours` | int | 可选，成功/人工接管后按 N 小时后再试 |
| `sched_window_hours` | tuple/list | 可选，本地时间可执行窗口 `[start, end)` |
| `allowed_weekdays` | list[int] | 可选，允许星期，`1=周一 ... 7=周日` |
| `human_takeover` / `human_takeover_error` / `human_takeover_at` | bool/str/float | 人工接管标记；到期前显示红色，到期后可自动再试 |

## 执行后时间规则

`TaskManager._update_next_exec_time()` 负责执行后调度：

| 任务类别 | 默认执行后行为 |
|----------|----------------|
| `每日任务` | 下一个 05:00 |
| `活动任务` | 下一个 05:00 |
| `每周任务` | 下一个周一 05:00 |
| `自定义任务` | 下一个 05:00 |
| `一般任务` | 执行后关闭 `on=False` |
| 设置了 `next_exec_offset_hours` | 优先按当前时间 + N 小时 |

如果任务设置了 `sched_window_hours`，执行后时间会被夹到可执行窗口内。到期但不在 `allowed_weekdays` 时，调度器会把 `next_exec_time` 推迟到下一允许日 05:00。

## 状态机

调度器状态只有三种：

| 状态 | 含义 | 自动执行 |
|------|------|----------|
| `pending` | 未激活或已手动停止 | 否 |
| `running` | 已激活，后台线程会收集并执行到期任务 | 是 |
| `error` | 连续错误达到阈值，调度暂停 | 否 |

关键点：

- `activate()` 只会从非错误态进入 `running`；如果当前是 `error`，直接调用 `activate()` 不会恢复。
- 恢复错误态必须先 `reset()`，WebUI 对应 `/api/scheduler/reset` 和“恢复调度”按钮。
- `request_stop()` 会通知 `TaskManager` cooperative cancel，并把状态切回 `pending`。
- `wake()` 只打断等待，让后台线程重新检查；它本身不改变状态。

## 到期判定

一个任务会被调度收集，必须同时满足：

1. `on=True`
2. 任务路径存在于 `TaskRegistry`
3. 当前时间 `now >= next_exec_time`
4. 未处于人工接管冷却期：存在 `human_takeover_error` 但 `now < next_exec_time` 时不收集
5. 当前时间在 `sched_window_hours` 内；不在时会推迟 `next_exec_time`
6. 当前星期在 `allowed_weekdays` 内；不在时会推迟 `next_exec_time`
7. 没有在本次调度激活周期内耗尽 retry

人工接管标记不是永久冻结。`human_takeover_error` 存在时：

- `now < next_exec_time`：WebUI 显示红色，调度器跳过。
- `now >= next_exec_time`：WebUI 显示待执行，调度器会再次收集执行。
- 后续执行成功会清除 `human_takeover*` 字段。
- 手动 `task_call()` 会清除 `human_takeover*` 并立即设为到期。

## 动态等待

后台线程用 `Event.wait(interval)` 等到最近的有效执行时间：

```python
times = scheduler._collect_active_times()
if not times:
    interval = CHECK_INTERVAL  # 3600 秒
elif any(t <= now for t in times):
    interval = 0
else:
    interval = min(times) - now
```

有效时间会考虑 `sched_window_hours`、`allowed_weekdays` 和当前调度周期内 retry 耗尽的任务。配置文件、账号文件、自定义任务目录或职业目录变化时，`ConfigWatcher` 会触发重载；如果正在执行任务，则延迟到安全边界再重载。调度器自身保存任务状态、进度或 `next_exec_time` 后，会把已处理的配置/账号 JSON 写入标记为已见，避免下一轮把内部持久化误判为外部热重载请求；自定义任务和职业脚本目录仍继续监听。

## 跨角色调度

调度器按当前账号的 `dispatch_queue` 顺序调度角色。每轮会切换到第一个存在到期任务的角色；若队列为空，则不会执行自动调度。

切换角色后会：

- `TaskManager.switch_character()`；没有 task manager 时直接 `cfg.switch_character()`
- `invalidate_login()`
- 标记任务投影更新
- 重新收集当前角色任务

这个切换只更新账号/角色配置和 WebUI 投影，不重建任务注册表，也不重载职业脚本。只有脚本目录变更、启动初始化、Editor 保存自定义任务或延迟热重载安全边界才走完整 reload。

自动调度模式中，整轮跨角色任务执行完成后会切回 `dispatch_queue` 的第一个有效角色，并再次确认游戏内登录到该角色。这样首角色在空档期保持在线挂机，也让后续人工操作从固定角色开始。单任务直跑和纯 debug 任务不会触发这个收尾。

总览页的“所有角色下次执行”也使用同一套有效时间计算，避免显示和实际调度不一致。

## 执行管线

调度模式和单任务模式共用 `_run_task_pipeline()`：

```text
进入 pipeline
  ├─ 未验证角色？跳过
  ├─ 收集到期任务或使用显式任务列表
  ├─ 对每个任务:
  │    ├─ 非 debug 任务先做每日重启检查
  │    ├─ runtime_ctx.refresh() 确保设备与 App 可用
  │    ├─ 非 debug 任务确认角色登录
  │    ├─ TaskManager.execute_tasks([task], max_attempts=1, attempt_offset=retry_round)
  │    ├─ 成功：累计成功，清除连续错误
  │    ├─ 人工接管冷却：计入失败展示，但不增加连续错误
  │    ├─ 普通失败且仍有 retry：放入下一轮 retry 队列
  │    └─ retry 耗尽：计入失败，调度周期内跳过该任务
  ├─ 每个任务后保存配置并标记任务投影更新；若存在 _reload_deferred，则应用完整延迟重载
  └─ 有真实执行结果时发送 Windows 桌面/配置通知，再回到首个调度角色并执行 post_execution 收尾
```

调度器不会在同一轮里反复撞同一个失败任务。失败任务会等本轮其他任务结束后进入下一 retry 轮；达到 `max_retry` 后，在本次调度激活周期内跳过，直到重新启动调度或 reset 清理 retry exhaustion。

## 单任务执行语义

`TaskManager._execute_single_task()` 的成功标准不是“函数返回了”这么简单：

1. 执行前设置当前任务路径，任务内可用 `set_task_status()` / `get_task_status()`。
2. 执行前清空当前任务 `progress`。
3. 调用 `fn(**params)`。
4. 函数返回后检查 `progress`；如果是未完成进度，例如 `"5/6"`，会转成 `TaskRequireReTry`。
5. 只有函数返回且没有未完成进度，才算成功，并更新 `next_exec_time` / 清除人工接管标记。

任务状态 API：

```python
from AutoScriptor import set_task_status, get_task_status
from AutoScriptor.utils.task_state import clear_task_status

set_task_status("progress", "5/6")
progress = get_task_status("progress")
clear_task_status("progress")
```

`progress` 支持 `"5/6"`、`[5, 6]`、`{"done": 5, "total": 6}` 等可解析形态。不可解析的状态只展示，不参与“未完成”判定。

## 重试与错误状态

项目里有两层 retry：

| 层级 | 位置 | 说明 |
|------|------|------|
| 任务内 retry | `TaskManager._execute_single_task()` | 直接调用 `execute_tasks()` 且未指定 `max_attempts` 时，会按 `cfg["app"]["max_retry"]` 在函数内循环 |
| 调度周期 retry | `Scheduler._run_task_pipeline()` | 调度器传 `max_attempts=1`，失败任务先让出队列，下一 retry 轮再试 |

`MAX_CONSECUTIVE_ERRORS = 3` 仍存在，但不是“任意任务失败三次立刻停止”的简单规则。

会增加连续错误计数的情况：

- retry 耗尽后的普通失败通过 `record_result(0, failed)` 计入。
- 模拟器启动失败。
- 调度管线意外崩溃。

不会增加连续错误计数的情况：

- 任务失败但还会进入下一 retry 轮。
- `RequestHumanTakeover` 或进度未完成后被标记为人工接管冷却。
- 用户手动停止导致的 cooperative cancel。

连续错误达到 3 后进入 `error`，调度暂停，并同步发送 Windows 桌面/配置通知。必须先调用 `reset()` 或通过 WebUI “恢复调度”按钮恢复；单纯调用 `activate()` 不会从 `error` 自动恢复。

## 人工接管与进度

`RequestHumanTakeover` 或外部同名异常会写入：

```json
{
  "human_takeover": true,
  "human_takeover_error": "...",
  "human_takeover_at": 1771794000.0
}
```

同时调用 `_update_next_exec_time()`，所以红色不是永久停止，而是“到下次时间前需要人工关注”。典型进度失败生命周期：

```text
黄色待执行
  → 执行中写入 progress=3/6
  → 返回但 progress=5/6：视为未完成，进入 retry
  → retry 耗尽且 progress 仍未完成：标记 human_takeover_error，显示红色 5/6
  → next_exec_time 到期：重新变为待执行，可自动再试
  → 后续成功：清除 progress 与 human_takeover*
```

普通失败如果没有可解析的未完成进度，不会自动变红；它只按 retry/错误计数处理。

## WebUI 状态投影

任务行状态由后端和前端共同投影：

| 展示 | 条件 |
|------|------|
| disabled | `on=False` |
| error | `error` 字段存在，或人工接管标记存在且尚未到期 |
| pending | `on=True` 且到期 |
| scheduled | `on=True` 且未来执行 |

`progress_display` 会显示在任务状态旁，例如红色 `5/6` 或黄色 `5/6`。这只是展示层，不替代调度判定；调度判定仍以 `progress_incomplete()`、`next_exec_time` 和人工接管冷却为准。

错误态任务可在 WebUI 任务树点击状态徽章，确认后执行“关闭并重新开启”：清除 `human_takeover*`、进度状态，并将 `next_exec_time` 设为 `0` 后自动保存。普通启用切换（由关闭重新打开）也会走同样的重置逻辑。

## post_execution 收尾

配置位置：`data/config.json -> emulator.post_execution`

| 值 | 行为 |
|----|------|
| `none` / `null` | 不额外关闭游戏或模拟器 |
| `close_game_only` | 关闭游戏应用，模拟器保留 |
| `close_mumu` | 关闭游戏并关闭模拟器 |
| `goto_main` | 尝试回到主界面 |

收尾和任务完成通知只在本次 pipeline 有真实成功或失败统计时触发一次；失败标题为“任务失败”，全成功标题为“任务完成”。若本轮只执行 debug 任务，则跳过 `post_execution`，方便保留现场调试。

## 维护检查清单

修改调度、任务状态或 WebUI 投影时，至少核对：

- `is_task_due()`、`_collect_due()`、`TaskTreeService._task_status()` 是否一致。
- `human_takeover_error` 到期前/到期后是否分别显示红色/待执行。
- `progress` 未完成是否会把正常返回转为 retry 失败。
- retry 耗尽是否只影响本次调度激活周期，避免永久“到期但永不执行”。
- `cfg["tasks"]` 只保存用户配置，`TaskRegistry` 只保存运行时元数据。
- 相关测试：`test/test_task_registry/test_decouple_cfg.py` 与 `test/test_webui_contracts.py`。
