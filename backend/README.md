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
    ├── server.py             FastAPI 应用、/api/*、/ws/logs、静态挂载、鉴权中间件
    ├── gui.py                后端进程入口（含 Electron 模式）
    ├── security.py           部署密码、会话、限流、凭据解锁
    ├── error_archives.py     错误归档读取/删除/导入
    ├── api_response.py       响应封装
    ├── routes/               editor、news、news_4399_session、notifications
    ├── static/               Vue 页面与静态资源
    └── vendor/               第三方前端库
```

## 与编排层的接口

```python
from orchestrator import orchestrator
```

本层负责：注入生命周期 hook、把 `orchestrator.guard_idle()` 的结构化冲突转成 409、
把状态投影成 `/api/*` 的响应。它不持有调度内脏。
