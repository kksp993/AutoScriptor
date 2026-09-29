# backend — 后端

HTTP API、WebSocket、进程启动、安全、更新与通知。由原来的 `services/` 迁入。

调度、排序、重试、执行互斥这些属于 `orchestrator/`；本层只调用它的接口。

## 结构

```
backend/
├── core/       运维与集成
│   ├── banner.py             启动横幅
│   ├── updater.py            源码 Git 更新通道
│   ├── single_instance.py    单实例锁
│   ├── remote_access.py      远程访问入口
│   └── qq_bot.py             本机 QQ 机器人安装与启动
└── webui/      WebUI 服务
    ├── server.py             应用壳：日志、鉴权中间件、静态挂载、进程生命周期
    ├── gui.py                后端进程入口（含 Electron 模式）
    ├── api_context.py        路由共用的请求上下文：执行守卫、公开配置投影、持久化诊断
    ├── api_response.py       响应封装
    ├── security.py           部署密码、会话、限流、凭据解锁、请求层薄封装
    ├── error_archives.py     错误归档读取/删除/导入
    ├── routes/
    │   ├── tasks.py          任务配置与执行控制
    │   ├── overview.py       总览与运行快照
    │   ├── accounts.py       账号、角色、调度队列、凭据解锁
    │   ├── news.py           4399 资讯抓取、代理、兑换码执行入口
    │   ├── ops.py            设备/OCR 探测、更新、远程访问、部署、导入导出、错误归档
    │   ├── notifications.py  onepush 与 QQ 通知渠道
    │   ├── editor.py         图片编辑器后端
    │   └── news_4399_session.py
    ├── static/               Vue 页面与静态资源
    └── vendor/               第三方前端库
```

`server.py` 只管应用壳和几个属于进程本身的端点（登录、日志流、favicon）。
其余按域分模块，各自从 `api_context` / `security` 取需要的东西，不 import server。

## 与编排层的接口

```python
from orchestrator import orchestrator
```

本层负责：注入生命周期 hook、把 `orchestrator.guard_idle()` 的结构化冲突转成 409、
把状态投影成 `/api/*` 的响应。它不持有调度内脏。

路由需要编排层的两件事时，都走 `api_context`：**执行守卫**（写配置不能和正在跑的任务撞车，
冲突载荷统一成一种 409）和**公开配置投影**（浏览器能看见什么）。持久化失败要带上的
诊断信息也在那里，所以每个写接口报错时附的路径是同一份。

它也不缓存编排层的派生数据。任务列表的执行顺序由 `orchestrator.tree.sort_task_paths()`
现算，而不是本地留一份顺序表——那种缓存过期了不会报错，只会悄悄按旧顺序跑。
