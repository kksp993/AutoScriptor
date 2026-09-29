# orchestrator — 编排层

以任务为核心的调度管理。`tasks/` 定义「任务是什么」，本层决定「何时、按什么顺序、在哪个角色、以什么重试策略执行」。

## 入口

后端只和 `orchestrator.orchestrator` 打交道：

```python
from orchestrator import orchestrator

orchestrator.configure_lifecycle(...)      # 后端注入自己的 hook（版本号、日志级别、UI 缓存）
orchestrator.start_scheduler()             # 启动调度
orchestrator.run_tasks_direct(tasks)       # 显式跑一批任务
orchestrator.execution_status()            # 忙碌/停止状态
```

装配（谁驱动谁）在 `facade.py` 里完成一次，调用方不再自己接线。子对象仍可访问
（`orchestrator.scheduler`、`orchestrator.tasks`、`orchestrator.tree`），因为后端需要的能力不止一种。

## 模块

| 模块 | 职责 |
| --- | --- |
| `facade.py` | 组合入口，`orchestrator` 单例 |
| `registry.py` | 启动时的任务发现、导入顺序、装配（原 `tasks/pkg_utils` + `custom_task_loader` + `load_tasks`） |
| `scheduler.py` | 定时等待、跨角色派发、调度周期 retry、状态机、执行闸门 |
| `task_manager.py` | 单任务执行、任务内 retry、进度判定、人工接管、执行后时间 |
| `task_tree.py` / `task_ordering.py` | 任务树判定、全局排序投影 |
| `task_tree_service.py` | 任务树投影（供 WebUI 读取） |
| `runtime_controller.py` | 执行互斥：调度 / 直接执行 / 编辑器代码三者仲裁 |
| `lifecycle.py` | 配置与任务的保存/重载生命周期 |
| `state_version.py` | 配置版本号 |
| `watcher.py` | 配置文件变更监听 |
| `notify.py` / `character_reports.py` / `qq_notify.py` | 管线内联的结果聚合与投递 |

## 边界

本层不下探到：

- HTTP / WebSocket / 页面 → `backend/`
- 任务脚本本体、导航、战斗 → `tasks/`、`ZmxyOL/`

冲突以**纯数据**表达（`RuntimeController.busy_conflict()` 返回 dict），塑形成 HTTP 状态码是 backend 的事——
编排层不 import `backend`。依赖方向是单向的：

```
backend -> orchestrator -> tasks -> ZmxyOL -> AutoScriptor
```
