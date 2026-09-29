# tasks — 任务脚本层

所有任务脚本，也就是「任务」本身：一个被 `@register_task` 装饰的 Python 函数，加上它的路径、参数和说明。

本层只放任务脚本；什么时候执行、按什么顺序执行、失败怎么办，由 `orchestrator/` 决定。

## 内容

| 位置 | 说明 |
| --- | --- |
| `daily_task/`、`event_task/`、`normal_task/`、`weekly_task/` | 内置任务实现 |
| `task_register.py` | `@register_task` 装饰器与 cfg 叶节点维护 |
| `task_registry.py` | 运行时注册表（fn / order / 参数 spec），不持久化 |
| `task_params.py` | 参数契约：签名 → 默认值 / 表单描述 / 执行解码 |
| `task_state.py` | 任务本地状态 API，例如 `progress` |
| `_order.txt` | 内置任务注册顺序的 seed（由编排层读取） |
| `battle_task_params.py` | 战斗流程枚举与职业参数 |
| `time.py`、`translations.py` | 时间辅助与路径中文化 |

任务路径用 slash 表示，例如 `每日任务/村庄/宠物培养`。用户自定义任务放在运行数据目录 `data/custom_task/`，
由 `orchestrator/catalog.py` 载入；`test/scripts/` 是测试脚本，不属于本层。

## 与 `ZmxyOL/__init__.py` 的耦合

`ZmxyOL` 对外导出 `register_task` / `task_registry` / `BattleFlowName` 等名字，来源指向本包。两点必须一起看：

- `ZmxyOL.__all__` 在 `ZmxyOL` 或 `tasks` 的包初始化期间必须不可用，否则会形成
  `tasks/__init__` → `task_register` → `ZmxyOL` → `tasks` 的循环导入。
- 本包的导出是**急切**的：`task_register` 里的 `from ZmxyOL import *` 会把 `register_task`
  解析回本包，惰性解析会重入正在初始化的模块。

改动这两处的导入顺序时要一起验证。

## 不负责

- 导航、战斗流程、职业脚本 → `ZmxyOL/`
- 定时、重试、排序、派发 → `orchestrator/`
