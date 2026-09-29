# tasks — 任务脚本层

所有任务脚本，也就是「任务」本身：一个被 `@register_task` 装饰的 Python 函数，加上它的路径、参数和说明。

本层只放任务脚本；什么时候执行、按什么顺序执行、失败怎么办，由 `orchestrator/` 决定。

## 内容

| 位置 | 说明 |
| --- | --- |
| `daily_task/`、`event_task/`、`normal_task/`、`weekly_task/` | 一级分类目录，分别对应 `每日任务/`、`活动任务/`、`一般任务/`、`每周任务/` |
| `bmkj/`、`village/`、`heaven/`、`hyper/`、`hgwj/` 等 | 功能分组目录，对应 `本命空间/`、`村庄/`、`天庭/`、`极北/`、`荒古万界/` |
| `游玩任务脚本.py`（中文文件名） | 任务本体，文件名即 cfg 里的任务名 |
| `task_register.py` | `@register_task` 装饰器与 cfg 叶节点维护 |
| `task_registry.py` | 运行时注册表（fn / order / 参数 spec），不持久化 |
| `task_params.py` | 参数契约：签名 → 默认值 / 表单描述 / 执行解码 |
| `task_state.py` | 任务本地状态 API，例如 `progress` |
| `_order.txt` | 内置任务注册顺序的 seed（由编排层读取） |
| `battle_task_params.py` | 战斗流程枚举与职业参数 |
| `time.py` | 时间辅助 |
| `translations.py` | 目录名 ↔ 中文 cfg 键的映射表 |

目录结构与 cfg 任务树一一对应，只是目录用英文、cfg 用中文：

```text
tasks/daily_task/village/宠物培养.py   →  每日任务/村庄/宠物培养
        └ 分类 ┘ └ 分组 ┘ └ 显示名 ┘
```

**任务脚本的文件名就是它的中文显示名**，打开目录看到的就是任务树里的名字。分类和分组目录的
英文名由 `translations.py` 翻译，所以内置任务不需要写 `path_cn`。

用户自定义任务放在运行数据目录 `data/custom_task/`，由 `orchestrator/catalog.py` 载入；
`test/scripts/` 是独立开发脚本，不属于本层。

## 任务脚本约定

每个任务脚本就是一个被 `@register_task` 装饰的函数，一个文件一个任务。

| 约定 | 原因 |
| --- | --- |
| 文件名用中文显示名 | 文件名去掉扩展名后直接成为 cfg 键，也是 `_order.txt` 里的条目 |
| 放到分类对应的目录下（`daily_task` / `weekly_task` / `event_task` / `normal_task`） | cfg 路径首段由目录推导；放错分类会落到错误的树节点 |
| 新增目录时登记到 `translations.py` | 未登记的目录名会原样进入中文任务树 |
| 参数名用 ASCII | 参数名同时是 `params` 的持久化键和 WebUI 表单键；中文标签由前端的参数标签表提供 |
| 必须声明 `description`，`task_doc` 可选 | 不传 `task_doc` 时取函数 docstring 首段；两者都不给则 WebUI 的补充说明为空 |
| 不写 `if __name__ == "__main__"` 尾巴，也不包 `try/except` + `traceback` | 现场验证走 WebUI 直接执行或 `debug_mode` 元数据，共用同一套调度、日志和停止语义 |
| 每个目录下的 `_order.txt` 列出该层全部任务文件和子目录 | 它是导入/注册顺序的 seed；漏列或写错名字会让任务排到末尾而不是它写定的位置 |
| 停用任务用 `deprecated=True`，不要删源码 | 源码和注册元数据保留，但不写 cfg、不出现在 WebUI 和调度列表 |
| 改名任务在注册里写 `legacy_path_cn="旧路径"` | 注册时把旧路径上的用户配置搬到新路径，是唯一的改名通道 |

这些约定由 `test/test_tasks/test_task_conventions.py` 检查，新增任务会自动纳入。

## 一个任务的生命周期

```text
@register_task 装饰      写 cfg 叶节点（on / next_exec_time / params）+ 写 TaskRegistry（fn / 参数 spec）
调度器收集               on=True、已注册、到 next_exec_time、在窗口和允许星期内、未被人工接管冷却
TaskManager 执行         按参数 spec 还原实参 → 调函数 → 检查 progress
执行后                   更新 next_exec_time、清人工接管标记，并按类别决定下次时间
```

任务只描述「做什么」；「什么时候做、失败了怎么办」在 `orchestrator/`。详细规则见
[任务脚本编写](../docs/AutoScriptor/tasks/script-authoring.md)。

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
