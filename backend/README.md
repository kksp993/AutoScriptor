# backend — 后端

HTTP API、WebSocket、进程启动、安全、更新与通知。当前 `services/` 就是这一层。

## 现有来源

WebUI 服务（`services/webui/`）：

| 文件 | 职责 |
| --- | --- |
| `server.py` | FastAPI 应用、`/api/*`、`/ws/logs`、静态挂载、鉴权中间件 |
| `gui.py` | 后端进程启动入口（含 Electron 模式） |
| `routes/` | editor、news、news_4399_session、notifications |
| `security.py` | 部署密码、会话、限流、凭据解锁 |
| `error_archives.py` | 错误归档的读取/删除/导入 |
| `api_response.py`、`state_version.py` | 响应封装、配置版本号 |

运维与集成（`services/core/` 中不属于编排的部分）：

| 文件 | 职责 |
| --- | --- |
| `banner.py` | 启动横幅 |
| `updater.py` | 源码 Git 更新通道 |
| `watcher.py` | 配置文件监听 |
| `single_instance.py` | 单实例锁 |
| `remote_access.py` | 远程访问入口 |
| `notify.py`、`qq_bot.py`、`qq_notify.py`、`character_reports.py` | 桌面通知、QQ 通知与机器人、角色结果聚合 |

## 不负责

- 调度、重试、任务排序、执行闸门 → `orchestrator/`
- 页面与静态资源 → `frontend/`
