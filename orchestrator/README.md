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
| `model.py` | 任务集的形状与到期时间：任务树判定、全局排序投影、时间窗口/星期限制、到期判定。纯查询，不读文件、不持线程、不碰设备 |
| `catalog.py` | 任务集从哪来：`tasks/` 发现、`_order.txt` 导入顺序、自定义任务、配置归一化和启动装配 |
| `scheduler.py` | 何时跑、跑谁：后台线程、跨角色派发、调度周期 retry、状态机、执行闸门、配置变更监听（`ConfigWatcher`） |
| `task_manager.py` | 单个任务怎么跑：参数恢复、任务内 retry、进度判定、人工接管、失败恢复、执行后时间 |
| `projection.py` | WebUI 能看见什么、怎么改：任务树公开投影与存档清洗、保存/重载生命周期、配置版本号 |
| `delivery.py` | 有什么要送出去：桌面 Toast / onepush 渠道 / OneBot QQ / 角色结果聚合 |
| `facade.py` | 组合根：`orchestrator` 单例，以及调度 / 直接执行 / 编辑器代码三者的执行互斥（`RuntimeController`） |

七个模块各回答一个问题，互相之间的依赖是单向的：`facade -> scheduler / task_manager / projection -> model`，
`catalog` 只被启动路径调用，`delivery` 不读任务树。`model.py` 是唯一不依赖运行时状态的模块，
所以调度器和 UI 投影能共用同一份「是否到期」定义，而不用各自维护一份。

## 边界

本层不下探到：

- HTTP / WebSocket / 页面 → `backend/`
- 任务脚本本体、导航、战斗 → `tasks/`、`ZmxyOL/`

冲突以**纯数据**表达（`RuntimeController.busy_conflict()` 返回 dict），塑形成 HTTP 状态码是 backend 的事——
编排层不 import `backend`。依赖方向是单向的：

```
backend -> orchestrator -> tasks -> ZmxyOL -> AutoScriptor
```
