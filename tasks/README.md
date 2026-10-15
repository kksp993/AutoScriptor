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
| `task_schedule.py` | 调度契约：`reschedule` 的取值与归一 |
| `task_params.py` | 参数契约：签名 → 默认值 / 表单描述 / 执行解码 |
| `task_state.py` | 任务本地状态 API，例如 `progress` |
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

## 作者的五个字段

一个任务的声明只有五个，全部写在装饰器里：

| 字段 | 作用 |
| --- | --- |
| `id` | 身份。`cfg["tasks"]` 和 `task_ordering` 都以它为键。默认取任务名（文件名去掉 `.py`），**换目录不影响它**；只有重命名文件时才写 `id="旧任务名"` |
| `reschedule` | 下次什么时候再来。不写 = 一次性；`"daily"` / `"weekly"` / 整数小时 / 带 `window`、`weekdays` 的字典 |
| `debug` | 调试直跑的默认值，用户可以在 WebUI 里覆盖 |
| `description` | 一句话简介。长说明写在函数 docstring 里 |
| `deprecated` | 系统属性。源码和元数据保留，但不写配置、不进 UI |

其余 `key=value` 只用于任务私有数据（例如 `last_buy_time`）。官方字段名写错会直接报错，
不会静默留在用户配置里。

## 任务脚本约定

每个任务脚本就是一个被 `@register_task` 装饰的函数，一个文件一个任务。

| 约定　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 原因　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| ---------------------------------------------------------------------------| ---------------------------------------------------------------------------------|
| 文件名用中文显示名　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 文件名去掉扩展名就是任务名，既是默认的 `id`，也是显示路径最后一段　　　　　　　 |
| 共享代码放同目录的下划线开头文件　　　　　　　　　　　　　　　　　　　　　| `_` 前缀表示「是模块不是任务」，不会被注册　　　　　　　　　　　　　　　　　　　|
| 放到分类对应的目录下（`每日任务` / `每周任务` / `其他任务`）　　　　　　　| 目录路径就是显示路径；放错分类会落到错误的树节点　　　　　　　　　　　　　　　 |
| 新建分组目录直接用中文名　　　　　　　　　　　　　　　　　　　　　　　　　| 目录名会原样成为显示路径的中间层级　　　　　　　　　　　　　　　　　　　　　　 |
| 参数名用 ASCII　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 参数名同时是 `params` 的持久化键和 WebUI 表单键；中文标签由前端的参数标签表提供 |
| 必须声明 `description`　　　　　　　　　　　　　　　　　　　　　　　　　　| 它是任务列表上的一句话简介；长说明写函数 docstring　　　　　　　　　　　　　　　|
| 不写 `if __name__ == "__main__"` 尾巴，也不包 `try/except` + `traceback`　| 现场验证走 WebUI 直接执行或 `debug` 设置，共用同一套调度、日志和停止语义　　　　 |
| 周期任务声明 `reschedule`，一次性任务不写　　　　　　　　　　　　　　　　　| 调度只认这一个字段，不看目录名　　　　　　　　　　　　　　　　　　　　　　　　|
| 停用任务用 `deprecated=True`，不要删源码　　　　　　　　　　　　　　　　　| 源码和注册元数据保留，但不写 cfg、不出现在 WebUI 和调度列表　　　　　　　　　　 |
| 重命名文件时把 `id` 钉在旧任务名上　　　　　　　　　　　　　　　　　　　　| 用户配置、拖拽顺序和运行状态都跟着 `id` 走；换目录不用写 `id`　　　　　　　　　 |

这些约定由 `test/test_tasks/test_task_conventions.py` 检查，新增任务会自动纳入。

## 一个任务的生命周期

```text
@register_task 装饰      按 id 写 cfg 条目（on / next_exec_time / params）+ 写 TaskRegistry（fn / 参数 spec）
调度器收集               on=True、已注册、到 next_exec_time、在 reschedule 的窗口和星期内、未被人工接管冷却
TaskManager 执行         按参数 spec 还原实参 → 调函数 → 检查 progress
执行后                   按 reschedule 决定下次时间；一次性任务关闭 on
```

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
