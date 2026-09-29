# orchestrator — 编排层

以任务为核心的调度管理。业务层（`ZmxyOL/`）定义「任务是什么」，本层决定「何时、按什么顺序、在哪个角色、以什么重试策略执行」。

## 现有来源（当前散落在 `services/`）

| 文件 | 职责 |
| --- | --- |
| `services/core/scheduler.py` | 定时等待、跨角色收集到期任务、调度周期 retry、状态机 |
| `services/core/task_manager.py` | 单任务执行、任务内 retry、进度判定、人工接管、执行后时间更新 |
| `services/core/task_tree.py` | 任务树 |
| `services/core/task_ordering.py` | 全局排序投影 |
| `services/core/runtime_context.py` | 设备会话生命周期（mixctrl / mumu / bg） |
| `services/webui/runtime_controller.py` | 执行闸门与 owner |
| `services/webui/lifecycle_service.py` | 运行生命周期、延迟 reload |
| `services/webui/task_tree_service.py` | 任务树投影（供 WebUI 读取） |

## 不负责

- 消息通知、QQ 机器人、更新器、单实例、远程访问 → `backend/`
- HTTP / WebSocket / 页面 → `backend/`、`frontend/`
- 任务函数本身、导航、战斗 → `ZmxyOL/`

## 搬迁前必须切断的两个反向依赖

当前 `services/core` 与 `ZmxyOL` 互相 import，抽出本层时要一并断开：

- `services/core` → `ZmxyOL`：`task_registry`、`task_state`、`table_param`、`nav`、`character`
- `ZmxyOL` → `services`：`task/custom_task_loader.py` → `services.core.task_tree`；`task/normal_task/restart.py` → `services.core.runtime_context`

复用现有做法（`set_account_backend()` 式的运行时注册），不要新建契约层。
