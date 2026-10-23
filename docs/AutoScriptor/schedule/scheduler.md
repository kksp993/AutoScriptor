# Scheduler 与任务执行生命周期

本文记录当前调度器、任务注册、重试、人工接管和 WebUI 状态投影的实际约定。它是维护跳表，不是旧实现说明。

## 组件边界

| 组件 | 职责 |
|------|------|
| `tasks/task_register.py` | 任务注册：`@register_task` 注册任务身份（`id`）与显示路径，按 `id` 维护用户配置条目，`TaskRegistry` 保存运行时元数据 `fn/param_specs/description/doc_flow`（不持久化，`param_meta` 由 spec 现算） |
| `tasks/task_schedule.py` | 调度契约：`reschedule` 的取值与 `normalize_reschedule()` 归一 |
| `tasks/task_params.py` | 参数契约：签名 → 默认值 / 表单描述 / 执行解码的唯一出处 |
| `orchestrator/catalog.py` | 启动时发现任务模块、按源码路径排序导入、归一化并装配任务配置平表 |
| `orchestrator/model.py` | 任务配置形态判定、全局排序投影、到期判定与时间窗口（纯查询） |
| `orchestrator/scheduler.py` | 后台线程、动态等待、跨角色收集到期任务、调度周期 retry、状态机 |
| `orchestrator/task_manager.py` | 单任务执行、参数恢复、任务内 retry、进度判定、人工接管标记、执行后时间更新 |
| `tasks/task_state.py` | 当前任务本地状态 API，例如 `progress` |
| `orchestrator/projection.py` / `backend/webui/server.py` | 将任务树投影为 WebUI 状态、进度、到期与错误展示 |

## 任务注册与数据归属

任务是一个被 `@register_task` 装饰的 Python 函数。内置任务来自 `tasks/`；自定义任务来自 `data/custom_task/`。两者的显示路径都由源码位置决定，没有路径参数。

注册数据分两层。`cfg["tasks"]` 是**以任务 `id` 为键的平表**；`id` 就是任务名（文件名去掉 `.py`），换目录不改身份，所以移动任务不动用户数据，重命名时用 `@register_task(id="旧任务名")` 把身份钉住。

| 数据 | 保存位置 | 持久化 | 说明 |
|------|----------|--------|------|
| `on`、`next_exec_time`、`params`，以及用户覆盖的 `reschedule` / `debug` | `cfg["tasks"]`（键为任务 `id`） | 是 | 用户数据 |
| `fn`、`param_specs`、`doc_flow`、`description`、`custom`，以及作者声明的 `reschedule` / `debug` 默认值 | `TaskRegistry` | 否 | 运行时元数据，重载任务时重建；WebUI 投影时由 spec 现算 `param_meta` / `param_keys` |
| `progress` 等任务运行状态 | `cfg["status"]["tasks"][task_path]` | 是 | 跟随账号/角色配置 |

首次注册一个新任务条目时默认 `on=False`、`next_exec_time=0`；已有任务会保留用户配置，并就地清掉旧版本遗留字段。WebUI 保存任务时会剥离 `param_meta/param_keys/custom/_due/id` 等投影字段——`debug` 和 `reschedule` 是用户数据，会原样存下来。

## 任务配置条目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `on` | bool | 是否启用任务 |
| `next_exec_time` | float | 下次可执行 Unix 时间戳，`0` 表示立即可执行 |
| `params` | dict | 任务函数参数，执行前按 `param_meta` 恢复枚举和 `TableParam` |
| `reschedule` | 可选 | 用户覆盖的调度规则；写了就用它，没写就用作者声明的默认值。取值见 `tasks/task_schedule.py` |
| `debug` | bool | 用户覆盖的调试开关；写了就用它，没写就用作者声明的默认值 |
| `human_takeover` / `human_takeover_error` / `human_takeover_at` | bool/str/float | 人工接管标记；到期前显示红色，到期后可自动再试 |
| 任务私有字段 | 任意 JSON | 作者通过 `@register_task` 的其余 `key=value` 声明，例如 `last_buy_time` |

## 执行后时间规则

`TaskManager._update_next_exec_time()` 负责执行后调度：

| `reschedule` 生效值 | 执行后行为 |
|---------------------|----------------|
| 不写（一次性） | 关闭 `on=False`，不排下一次 |
| `"daily"` | 下一个 05:00 |
| `"weekly"` | 下周一 05:00 |
| 整数 N | 当前时间 + N 小时 |
| 带 `window` 的规则 | 算出的时间点被夹进可执行窗口 |
| 带 `weekdays` 的规则 | 到期但不在允许日时，`next_exec_time` 推迟到下一允许日 05:00 |

生效值 = 用户在 cfg 里覆盖 → 作者声明的默认值 → 一次性。任务位于哪个目录不再影响调度。判据只此一处，所以「同一个任务换个目录就换了调度行为」这种坑不会再出现。

## 状态机

调度器状态只有三种：

| 状态 | 含义 | 自动执行 |
|------|------|----------|
| `pending` | 未激活或已手动停止 | 否 |
| `running` | 已激活，后台线程会收集并执行到期任务 | 是 |
| `error` | 连续错误达到阈值，调度暂停 | 否 |

关键点：

- `activate()` 只会从非错误态进入 `running`；如果当前是 `error`，直接调用 `activate()` 不会恢复。
- `error` 会自愈：静默 30 分钟后主循环自动 `reset()` + `activate()`（见「重试与错误状态」）。
- `running` 表示调度长期启用，不表示当前正在执行任务。`status.enabled=true` 对应该激活态；只有调度取得共享执行闸门时 `status.executing/busy=true`。
- 恢复错误态可调用 `reset()`、使用 WebUI“恢复调度”，或通过统一终止入口恢复；三者都重置错误额度，终止入口额外保留 cooperative cancel。
- `request_stop()` 会通知 `TaskManager` cooperative cancel，把状态切回 `pending`，清零连续错误次数并清除本调度周期 retry 耗尽记录；它不会清除取消信号。
- `wake()` 只打断等待，让后台线程重新检查；它本身不改变状态。

## 执行互斥

调度激活状态和设备执行权是两个独立生命周期。调度器、任务列表直接执行和 Editor 设备操作共享一个执行闸门：

```text
调度 running + 闸门空闲
  ├─ 手动任务/Editor 先取得闸门 → 调度到期后阻塞等待
  └─ 调度先取得闸门 → 手动入口等待本轮结束后重试

手动执行释放闸门
  └─ 等待中的调度继续收集到期任务，state 仍为 running
```

调度 `_check_and_run()` 阻塞取得闸门，并在取得后再次检查状态；如果等待期间被停止，则直接释放闸门，不再启动任务。任务列表和 Editor 使用非阻塞取得，避免请求线程长期悬挂；冲突返回 `409 runtime_busy`，但提示用户等待当前执行结束，而不是要求关闭调度。预检和闸门取得必须同时存在：预检提供准确状态提示，闸门负责消除两个入口同时通过预检的竞态。

## 到期判定

一个任务会被调度收集，必须同时满足：

1. `on=True`
2. 任务路径存在于 `TaskRegistry`
3. 当前时间 `now >= next_exec_time`
4. 未处于人工接管冷却期：存在 `human_takeover_error` 但 `now < next_exec_time` 时不收集
5. 当前时间在生效 `reschedule` 的 `window` 内；不在时会推迟 `next_exec_time`
6. 当前星期在生效 `reschedule` 的 `weekdays` 内；不在时会推迟 `next_exec_time`
7. 没有在原计划内耗尽 retry：任务被排到更晚的时间点后跳过自动失效（见「retry 跳过的有效期」）

收集到的到期任务会再按全局 `task_ordering` 投影排序后执行。有效顺序来自确定性总排序：先把存储里的 `id` 键 overlay 换成显示路径，再递归展开 WebUI 拖拽保存的 `items` 分组顺序（`user_order` 是展平后的兼容投影），最后回退到当前注册顺序和路径字典序。旧版 `hard_edges`、`layout`、`group_order` 会被规范化忽略，不再表示偏序规则或业务成功依赖。

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

有效时间来自生效 `reschedule` 的 `window`、`weekdays`，以及当前调度周期内 retry 耗尽的任务。配置文件、账号文件、自定义任务目录或职业目录变化时，`ConfigWatcher` 会触发重载；如果正在执行任务，则延迟到安全边界再重载。调度器自身保存任务状态、进度或 `next_exec_time` 后，会把已处理的配置/账号 JSON 写入标记为已见，避免下一轮把内部持久化误判为外部热重载请求；自定义任务和职业脚本目录仍继续监听。

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
  │    ├─ 非任务列表直跑时确认角色登录；任务列表来源直接复用当前游戏状态
  │    ├─ TaskManager.execute_tasks([task], max_attempts=1, attempt_offset=retry_round)
  │    ├─ 成功：累计成功，清除连续错误
  │    ├─ 人工接管冷却：计入失败展示，但不增加连续错误
  │    ├─ 普通失败且仍有 retry：放入下一轮 retry 队列
  │    └─ retry 耗尽：计入失败，调度周期内跳过该任务
  ├─ 每个任务后保存配置并标记任务投影更新；若存在 _reload_deferred，则应用完整延迟重载
  └─ 有真实执行结果时发送 Windows 桌面/配置通知，再回到首个调度角色并执行 post_execution 收尾
```

调度器不会在同一轮里反复撞同一个失败任务。失败任务会等本轮其他任务结束后进入下一 retry 轮；用满 `max_attempts` 后，在同一份计划内跳过（见「retry 跳过的有效期」）。

任务失败后的设备恢复由 `TaskManager._try_recover_app()` 负责：关闭并重新拉起 App，第一次失败时
再重启 ADB。若连续 3 次恢复后 App 仍没进入 `running`，改为重启 MuMu 实例并重建设备会话；两次
MuMu 重启至少间隔 10 分钟，任务成功会清零计数。它只处理设备/App 启动失败，不改变任务自身的
retry 计数或调度尝试次数。详见 [runtime/lifecycle.md](../runtime/lifecycle.md#设备会话)。

任务列表页的三个直接执行入口通过 `execution_source=task_list` 进入 `run_direct(skip_character_login=True)`。这条策略只跳过登录缓存失效和 `_ensure_character_logged_in()`；普通任务的每日重启检查、设备/App 就绪、retry、状态保存、通知和 `post_execution` 都保持原语义。默认 `run_direct()`、自动调度和跨角色切换仍失效登录缓存并校验目标角色，显式 `force_login=True` 始终覆盖跳过策略。

## 角色结果通知

共用管线通过 `CharacterReports` 记录每个 run id 的最后结果。转向其他角色且原角色无待重试项时
发布报告；管线 `finally` 收束剩余报告，取消/异常标为中断。重试覆盖原结果，空管线不发消息。
角色身份及队列序号在管线内冻结，QQ 发送在独立线程中完成，不读取切换后的 cfg，也不影响游戏重试。
配置入口为 WebUI“QQ 通知”，不替代原有整轮桌面/YAML 汇总，详见 [QQ 通知](../operations/qq-notifications.md)。

## 单任务执行语义

`TaskManager._execute_single_task()` 的成功标准不是“函数返回了”这么简单：

1. 执行前设置当前任务路径，任务内可用 `set_task_status()` / `get_task_status()`。
2. 执行前清空当前任务 `progress`。
3. 调用 `fn(**params)`。
4. 函数返回后检查 `progress`；如果是未完成进度，例如 `"5/6"`，会转成 `TaskRequireReTry`。
5. 只有函数返回且没有未完成进度，才算成功，并更新 `next_exec_time` / 清除人工接管标记。

任务状态 API：

```python
from tasks.task_state import set_task_status, get_task_status, clear_task_status

set_task_status("progress", "5/6")
progress = get_task_status("progress")
clear_task_status("progress")
```

`progress` 支持 `"5/6"`、`[5, 6]`、`{"done": 5, "total": 6}` 等可解析形态。不可解析的状态只展示，不参与“未完成”判定。

## 重试与错误状态

项目里有两层 retry，共用同一个上限 `cfg["app"]["max_attempts"]`：

| 层级 | 位置 | 说明 |
|------|------|------|
| 任务内 retry | `TaskManager._execute_single_task()` | 直接调用 `execute_tasks()` 且未指定 `max_attempts` 参数时，在函数内连续跑到上限 |
| 调度周期 retry | `Scheduler._run_task_pipeline()` | 调度器传 `max_attempts=1`，失败任务先让出队列，下一 retry 轮按 `attempt_offset` 接着数 |

`max_attempts` 的含义是**一个任务最多跑几遍，含第一遍**——不是「失败后再来几次」。
它以前叫 `max_retry`，同一个数字换了含义，所以配置层做了一次换算
（`attempts = retry + 1`，见 `app_config._migrate_renamed_app_keys`）；直接沿用旧值
会让每个任务少跑一遍。界面上对应「最多尝试次数」，默认 3，也就是最多跑 3 次。

`MAX_CONSECUTIVE_ERRORS = 3` 仍存在，但不是“任意任务失败三次立刻停止”的简单规则。

会增加连续错误计数的情况：

- retry 耗尽后的普通失败通过 `record_result(0, failed, task_key)` 计入，但**同一个
  任务反复失败只算一次**：连续错误衡量的是环境是否成片出问题（模拟器起不来、断网），
  不是某个任务好不好用。一个必失败的任务（某期活动页改版之类）自己的重试上限已由
  retry 跳过兜住，不该把整个调度停掉——2026-10-06 就是它一个（1 主跑 + 2 重试）把
  调度送进 `error`，之后所有到期任务全停。
- 模拟器启动失败。
- 调度管线意外崩溃。

不会增加连续错误计数的情况：

- 任务失败但还会进入下一 retry 轮。
- 上一次失败也是同一个任务（按同一故障计）。
- `RequestHumanTakeover` 或进度未完成后被标记为人工接管冷却。
- 用户手动停止导致的 cooperative cancel。

连续错误达到 3 后进入 `error`，调度暂停，并同步发送 Windows 桌面/配置通知。

**`error` 不是终点**：静默 `ERROR_AUTO_RECOVER_SECONDS`（30 分钟）后主循环会自动
`reset()` + `activate()` 重来一轮。没有它，一次夜间故障会让之后所有到期任务都不跑，
直到有人发现并手点「恢复调度」——用户看到的就是“任务到期了却不继续”。错误态期间的
等待间隔被钳到 `ERROR_WAKE_INTERVAL`（60 秒），否则会按“睡到下一个任务时间”一觉
睡到明天，冷却形同虚设。环境没恢复时只会再次进入错误态，等下一个冷却期。

也可以手动恢复：调用 `reset()`、使用 WebUI“恢复调度”按钮，或点击总览/调度/任务列表
任一“终止”按钮恢复到 `pending` 并获得新的 3 次连续错误额度；终止还会清除 retry 跳过
记录。单纯调用 `activate()` 不会从 `error` 自动恢复。任务仍在协作退出时，取消信号保持
有效，其随后上报的失败不重新计入连续错误。

### retry 跳过的有效期

任务在“同一份计划”里耗尽 retry 后，会被跳过**直到它被排到下一次执行时间**
（`_is_retry_exhausted` 比较当前 `next_exec_time` 与打标记的时刻）。这解决的是另一
半问题：标记以前只在重新激活调度时清除，而用户往往一直开着调度不点停止，于是昨天
失败过的任务今天到期了也被永久跳过。失败后 `next_exec_time` 没被推进时标记继续有效，
这是它本来的用途——挡住同一计划内的无限重试。

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

错误态任务可在 WebUI 任务列表点击状态徽章，确认后执行“关闭并重新开启”：清除 `human_takeover*`、进度状态，并将 `next_exec_time` 设为 `0` 后自动保存。普通启用切换（由关闭重新打开）也会走同样的重置逻辑。

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
- retry 跳过是否只作用于「同一份计划」（`next_exec_time` 未推进期间），避免永久“到期但永不执行”。
- 同一个任务反复失败是否按同一故障计，不会把调度送进 `error`。
- `error` 冷却自动恢复是否仍生效，且错误态下等待间隔被钳到 `ERROR_WAKE_INTERVAL`。
- `cfg["tasks"]` 只保存用户配置，`TaskRegistry` 只保存运行时元数据。
- 相关测试：`test/task_domain/test_decouple_cfg.py` 与 `test/webui/test_webui_contracts.py`。
