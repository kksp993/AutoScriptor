# tasks — 任务脚本层

所有任务脚本，也就是「任务」本身：一个被 `@register_task` 装饰的 Python 函数。

本层只放任务脚本；什么时候执行、按什么顺序执行、失败怎么办，由 `orchestrator/` 决定。

## 内容

| 位置 | 说明 |
| --- | --- |
| `每日任务/`、`每周任务/`、`其他任务/` | 任务分类 |
| `村庄/`、`天庭/`、`极北/`、`荒古万界/`、`本命空间/` 等 | 功能分组 |
| `宠物培养.py` 这类中文文件 | 任务本体，文件名就是显示路径的最后一段 |
| `_活动流程.py`、`_仙术表.py` 这类下划线开头的文件 | 辅助模块：随目录一起导入，但不注册任务 |
| `task_register.py` | `@register_task` 装饰器与 `TaskRegistry` 注册表（同一个文件持有两者） |
| `task_schedule.py` | 调度契约：`reschedule` 归一、用户覆盖与基础周期时间 |
| `task_params.py` | 参数契约：签名 → 默认值 / 表单描述 / 执行解码 |
| `task_state.py` | 按账号、角色、任务隔离的周期状态与续跑请求 |
| `battle_task_params.py` | 战斗流程枚举与职业参数 |
| `time.py` | 时间辅助 |

**源码位置决定显示路径**，不需要任何映射：

```text
tasks/每日任务/村庄/宠物培养.py          →  每日任务/村庄/宠物培养
data/custom_task/背包清空/进阶仙宝.py    →  自定义任务/背包清空/进阶仙宝
```

打开 `tasks/` 看到的就是 WebUI 任务树的样子，路径逐段相同，所以没有路径参数。

用户自定义任务放在运行数据目录 `data/custom_task/`，由 `orchestrator/catalog.py` 载入；
WebUI 编辑器保存的脚本也落在那里，同样按位置决定路径。

## 作者的声明字段

正式字段全部写在装饰器里，`ensure_in` 必填：

- `id`：身份。`cfg["tasks"]` 和 `task_ordering` 都以它为键。默认取文件名去掉 `.py`，
  **换目录不影响它**；只有重命名文件时才写 `id="旧任务名"`。
- `reschedule`：下次什么时候再来。不写 = 一次性；`"daily"` / `"weekly"` / 整数小时 /
  带 `window`、`weekdays` 的字典。
- `debug`：调试直跑的默认值，用户可以在 WebUI 里覆盖。
- `description`：一句话简介。长说明写在函数 docstring 里。
- `params_doc`：函数参数名到中文标签的字典，例如 `params_doc={"diff": "难度", "hundun_diff": "混沌难度"}`。
  内置任务给所有参数填写；自定义脚本可省略，缺少标签时显示参数原名。键必须是函数参数，值必须是非空字符串。
  仅存注册表并下发前端，不写账号配置；重载按源码更新。表格内部列名仍由 `TableParam.column_labels` 提供。
- `deprecated`：系统属性。源码和元数据保留，但不写配置、不进 UI。
- `ensure_in`：源码的真实起始导航目标，字符串或非空字符串列表/元组，必须是已注册导航名。
  例如 `ensure_in="天庭#-1"`；执行包装层先定位，再进入正文，不再在任务开头重复调用。
  列表表示任一地点均满足正文前置条件，不是按参数选择不同目标；分支专用导航仍放分支里。
- `ANYWHERE`：由 `ZmxyOL` 导出，用 `ensure_in=ANYWHERE` 声明任意位置；`ensure_in(ANYWHERE)` 立即返回。
- `preferred_locations`：自动调度地点偏好。省略时继承真实入口，ANYWHERE 默认无偏好；显式 `[]` 清空。
- `after_tasks`：自动调度前置任务的稳定 ID，只在前置当前仍待执行时阻塞。

注册加载不操作设备，声明只保存在 `TaskRegistry`，不写用户 cfg。每次实际执行（含 debug、重试、续跑）
都经同一包装函数导航；失败/取消不执行正文，保留现有恢复与清理。装饰器返回同一包装函数并保留签名。
现场调试、外部 App、设备恢复或必须先准备凭据的任务用 `ensure_in=ANYWHERE`，不识别、不启动 App、不改导航缓存。
旧 `None`、省略、空值、未知地点和 ANYWHERE 与具体地点混用均拒绝。debug 只控制登录/恢复，不绕过入口声明。
`get_ensure_in(path)` 返回列表副本，ANYWHERE 投影为 `["任意位置"]`；`None` 仅表示任务不可见。
内部 fixture 的 `register()` 默认 ANYWHERE。计算图显示“任意位置”，不把它加入真实地图距离矩阵。
中途换图、重进副本、领奖和收尾导航必须保留；共享 helper 的 `entry_ready=True` 仅复用已确认的首次入口，后续仍导航。

其余 `key=value` 只用于任务私有数据（例如 `last_buy_time`）。官方字段名写错会直接报错，
不会静默留在用户配置里。

## 任务脚本约定

每个任务脚本就是一个被 `@register_task` 装饰的函数，一个文件一个任务。

识别目标在哪里用，就在哪里写：`T(...)`、`I(...)`、`B(...)` 及区域直接写在操作/判断/提取调用中，不提前定义按钮变量，不为复用集中到常量、字典或辅助函数。重复目标也保持调用处展开；识别结果和业务计算值可以保留变量。

| 约定　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 原因　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| ---------------------------------------------------------------------------| ---------------------------------------------------------------------------------|
| 文件名用中文显示名　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 文件名去掉扩展名就是任务名，既是默认的 `id`，也是显示路径最后一段　　　　　　　 |
| 共享代码放同目录的下划线开头文件　　　　　　　　　　　　　　　　　　　　　| `_` 前缀表示「是模块不是任务」，不会被注册　　　　　　　　　　　　　　　　　　　|
| 放到分类对应的目录下（`每日任务` / `每周任务` / `其他任务`）　　　　　　　| 目录路径就是显示路径；放错分类会落到错误的树节点　　　　　　　　　　　　　　　 |
| 新建分组目录直接用中文名　　　　　　　　　　　　　　　　　　　　　　　　　| 目录名会原样成为显示路径的中间层级　　　　　　　　　　　　　　　　　　　　　　 |
| 参数名用 ASCII　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 参数名是 `params` 的持久化键和表单键；中文标签在各任务的 `params_doc` 中声明 |
| 必须声明 `description`　　　　　　　　　　　　　　　　　　　　　　　　　　| 它是任务列表上的一句话简介；长说明写函数 docstring　　　　　　　　　　　　　　　|
| 不写 `if __name__ == "__main__"` 尾巴，也不包 `try/except` + `traceback`　| 现场验证走 WebUI 直接执行或 `debug` 设置，共用同一套调度、日志和停止语义　　　　 |
| 周期任务声明 `reschedule`，一次性任务不写　　　　　　　　　　　　　　　　　| 调度只认这一个字段，不看目录名　　　　　　　　　　　　　　　　　　　　　　　　|
| 停用任务用 `deprecated=True`，不要删源码　　　　　　　　　　　　　　　　　| 源码和注册元数据保留，但不写 cfg、不出现在 WebUI 和调度列表　　　　　　　　　　 |
| 重命名文件时把 `id` 钉在旧任务名上　　　　　　　　　　　　　　　　　　　　| 用户配置、拖拽顺序和运行状态都跟着 `id` 走；换目录不用写 `id`　　　　　　　　　 |

这些约定由 `test/task_domain/test_task_conventions.py`、`test_task_entry_metadata.py` 和 `test_task_params_doc.py` 检查，
新增任务和 deprecated 任务都会纳入入口及参数标签审计。

## 一个任务的生命周期

```text
@register_task 装饰      按 id 写 cfg 条目（on / next_exec_time / params）+ 写 TaskRegistry（fn / 参数 spec）
调度器收集               on=True、已注册、到 next_exec_time、在 reschedule 的窗口和星期内、未被人工接管冷却
TaskManager 执行         还原实参 → 包装层 ensure_in → 正文 → 检查 progress
执行后                   有续跑请求则保存等待时间；否则按 reschedule 收尾，一次性任务关闭 on
```

分阶段任务保留 `reschedule="daily"`，在需要继续时调用 `set_task_next_run(3 * 60)`。
此函数由 `ZmxyOL` 导出，只能在任务执行线程内使用；不等待、不退出函数，仍须正常返回。
本次收尾成功后才保存续跑计划，异常或取消会丢弃请求。等待期间执行其他任务，
不计完成、不消耗失败重试次数；最终完成时不再调用，恢复原有日常周期。
续跑会重新调用整个任务函数，业务进度通过 `get_task_status` / `set_task_status` 保存。
自动续跑要求任务已启用且调度器运行；手动直跑不会自行启动调度器。

标记名自行命名，值支持 JSON 类型。例如确认左侧种植成功后调用
`set_task_status("left_planted", True)`，后续通过
`get_task_status("left_planted", False)` 选择策略；`progress` 是执行器管理的特殊字段，
不要拿它当业务标记。读取列表/字典会得到副本，修改后须再次 set。

所有标记按生效的 `reschedule` 到期，而非 `set_task_next_run`：daily 每日 05:00，
weekly 周一 05:00；小时周期从本轮执行起算，最终完成后与正常下次时间对齐；
一次性任务不自动到期。04:58 保存、05:01 续跑时旧标记已失效，即使执行窗口推迟也一样。
读 API 只过滤过期值，不在轮询时写盘；执行或写入时清理。正常标记立即保存，
后续步骤失败不会撤销已确认的进度；周期规则变更、重新启用或手动重置会清理对应状态。
旧周期状态没有时间凭据时视作过期，避免把昨天的完成标记沿用到今天。

任务只描述「做什么」；「什么时候做、失败了怎么办」在 `orchestrator/`。详细规则见
[任务脚本编写](../docs/AutoScriptor/tasks/script-authoring.md)。

## 与 `ZmxyOL/__init__.py` 的耦合

`ZmxyOL` 对外导出 `register_task` / `task_registry` / `BattleFlowName` 等名字，来源指向本包。两点必须一起看：

- `ZmxyOL.__all__` 在 `ZmxyOL` 或 `tasks` 的包初始化期间必须不可用，否则会形成
  `tasks/__init__` → `task_register` → `ZmxyOL` → `tasks` 的循环导入。
- 本包的导出是**急切**的：`task_register` 里的 `from ZmxyOL import *` 会把 `register_task`
  解析回本包，惰性解析会重入正在初始化的模块。

`tasks/__init__.py` 导出的 `task_registry` 就是 `task_register.py` 里的那一个实例，全项目只有一份。

改动这两处的导入顺序时要一起验证。

## 不负责

- 导航、战斗流程、职业脚本 → `ZmxyOL/`
- 定时、重试、排序、派发 → `orchestrator/`
