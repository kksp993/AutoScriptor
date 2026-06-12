# WebUI API Contract 当前基线

WebUI 后端是 FastAPI；静态前端位于 `services/webui/static/`，Electron 壳位于 `webapp/`。

## 响应约定

新建或重构接口优先使用 `services.webui.api_response`：

```json
{"ok": true, "config_version": 12}
```

```json
{
  "ok": false,
  "error": "runtime_busy",
  "message": "当前调度器正在运行，请先点击「终止执行」再继续操作。",
  "code": "runtime_busy"
}
```

现状中仍有历史接口返回 `{"success": ...}`、`{"error": ...}` 或业务裸对象；不要在新接口继续扩散。HTTP 状态码必须有意义：参数错误 `400`，未授权/未解锁 `401/403`，运行冲突 `409`。前端通用错误解析必须兼容 FastAPI 的 `detail` 字段，否则 404/422 等框架错误会退化成“创建失败/操作失败”等空泛提示。

## 认证与解锁

- `deploy.password` 非空时，所有 `/api/*` 默认需要 `auth_token` Cookie 或 `X-Auth-Token`，豁免 `/api/auth` 和 `/api/deploy`。
- `/api/auth` 成功后写 `auth_token`，并清除旧 credential unlock token。
- 账号密码、内容更新等敏感操作使用 credential unlock cookie；主动重新验证会吊销旧 unlock。
- 登录和安全密码验证有频率限制。

## 核心状态

| 接口 | 说明 |
|------|------|
| `GET /api/init-status` | 后台初始化是否完成 |
| `GET /api/refresh` | 公开配置快照；会消费配置变更、重读任务投影 |
| `GET /api/runtime/snapshot` | 主轮询入口：运行状态、调度器、任务汇总、下次执行、config_version |
| `GET /api/run/status` | 直接运行线程状态 |
| `POST /api/run` | 直接运行任务，或启用调度模式 |
| `POST /api/stop` | 请求协作式停止 |

前端不要新增散落的账号/调度器/运行状态多路轮询；主界面以 `runtime/snapshot` 为准。

## 配置和任务

| 接口 | 说明 |
|------|------|
| `POST /api/config` | 保存 `app/emulator/ocr`，可包含 `scheduler` |
| `POST /api/tasks` | 保存任务树，后端剥离运行时字段并重载任务 |
| `POST /api/tasks/reload` | 重载任务和职业脚本 |
| `POST /api/enum-options` | 批量查询枚举选项，含 `BattleFlowName` 当前职业过滤 |
| `GET /api/config/export` | 导出可迁移配置 |
| `POST /api/config/import` | 导入允许的配置段，剥离 deploy 密码/证书等敏感字段 |
| `GET/POST /api/deploy` | 读取/保存 deploy、notify、update、remote_access |

`POST /api/config` 保存时会把空的、`YOUR_` 占位的或 `:0` 结尾的 `emulator.adb_addr` 规范化为 MuMu 默认地址：`127.0.0.1:16384 + index*32`。保存失败必须返回标准 `api_error` JSON，前端不能只显示“未知错误”。

保存任务时必须通过 `TaskTreeService.strip_runtime_fields()`，不能持久化 `fn/order/param_meta/param_keys/beta/custom/debug_mode/task_description/task_doc_flow/_due/progress/progress_display` 等运行时字段。

## 账号、角色和队列

| 接口 | 说明 |
|------|------|
| `GET /api/accounts` | 账号列表 |
| `POST /api/accounts/switch` | 切换账号并重载任务 |
| `POST /api/accounts/add` / `delete` | 新增/删除账号；新增账号使用标准 `api_ok/api_error` 响应 |
| `GET /api/characters` | 当前账号角色树 |
| `POST /api/characters/switch` | 切换角色并重载任务 |
| `POST /api/characters/add` / `delete` | 新增/删除角色 |
| `POST /api/characters/game_profession` | 设置角色游戏职业 |
| `GET /api/characters/all_tasks_summary` | 全角色任务汇总 |
| `GET/POST /api/dispatch/queue` | 跨角色调度队列 |

调度器只执行 `dispatch_queue` 内角色；队列保存时会去重并过滤不存在的角色。

## 设备、Editor 和 Canvas

| 接口 | 设备会话 |
|------|----------|
| `GET /api/device/diagnostics?screenshot=false` | 默认不截图，不初始化 OCR/UI Map |
| `/api/editor/ingest-image`、`ocr`、`color`、`save`、`store-template`、`locate-image` | 使用缓存截图/导入图，不启动模拟器 |
| `/api/editor/screenshot`、无缓存 `locate`、`remote/click`、`remote/swipe`、真实 `execute-code`、无缓存 `preview-extract` | 需要 `runtime_ctx.ensure_device_session()` |
| `/api/canvas/save/load/list/delete/preview` | 读写 `get_data_root()/canvas_data` 和 `get_custom_task_dir()` 下的 custom task 预览 |

Editor 真实设备动作需要 credential unlock；模拟执行且已有缓存图时应使用虚拟 `mixctrl`，只在画布标注，不触碰真实设备。

## 更新与发布

| 接口 | 说明 |
|------|------|
| `GET /api/update/status` | 源码部署 git updater 状态 |
| `POST /api/update/check` / `run` | 源码部署 fetch/pull/pip 更新；发行包中不可用 |
| `GET /api/content-update/status` | 发行版内容更新状态 |
| `POST /api/content-update/check` / `apply` | HTTPS manifest 内容更新，校验 hash/签名和保护路径 |

源码 updater 和发行版内容更新是两条独立通道。不要让发行包用户走 git updater。

## 错误归档、资讯、远程访问

| 接口 | 说明 |
|------|------|
| `/api/error-archives*` | 列表、详情、文件读取、批量删除、zip 导入 |
| `/api/news/*` | 4399 资讯、礼包码、代理页面 |
| `GET/POST /api/remote-access` | 远程访问配置和状态 |
| `POST /api/notify/test/save` | 通知测试与保存 |

错误归档路径必须经过安全文件名校验，zip 导入解压到新目录，不覆盖任意路径。

资讯页约定：

- 打开资讯页、WebUI 登录成功后停留在资讯页、或再次点击资讯入口时，前端都应调用 `/api/news/posts?force=1` 立即拉取远端列表，不等 30 分钟缓存。
- `/api/news/gift_codes?refresh=1` 只从官方公告近 10 天、最多 15 个帖子增量查找兑换码；记录已查帖子 ID 和仍有效兑换码，后续只查新增帖子。
- `/api/news/gift_codes/page` 是兑换码弹窗的内嵌页，读取本地 `docs/zmxy_redeem_codes.json`；表格列为序号、兑换码、到期时间、来源链接、操作，支持 Shift 连续选择和批量兑换，不要再使用旧的 4399 礼包页作为兑换码来源。
- `/api/news/redeem_targets` 只返回账号名和 `服务器:角色名` 选择项；`POST /api/news/gift_codes/redeem` 需要 credential unlock 或安全密码，接受 `redeem_code` 或 `redeem_codes`，先切到所选账号/角色并强制自动登录，再按顺序以临时 `redeem_code` 参数执行内置一般任务 `一般任务/活动/兑换豪礼礼品兑换`。
- `/api/news/proxy` 遇到 4399 登录墙时会使用可用资讯通行证重试一次；缓存通行证失效时应重登后再拉取正文。
- `news.account = "85rwm3janyyc"` 且 `news.password = "123456"` 是唯一允许明文模板保留的公开资讯通行证，仅用于 4399 news/forum/gift-code 代理。
- 旧配置若没有 `news` 段，资讯代理按该公开通行证兜底；显式配置其他 `news.*` 时按敏感凭据处理。
- 其他 `news.*`、`game.*`、账号文件、token、证书/私钥、deploy 密码都按敏感信息处理；非公开 news/game 凭据用于论坛代拉前仍需要 credential unlock。

## 日志

- 实时日志使用 WebSocket `/ws/logs`。
- 不使用 Socket.IO。
- 静态资源缓存：`/vendor` 和 `/fonts` 可缓存，`/static/*.js/css` no-cache。

## 修改接口前检查

- 是否需要 `guard_idle()`，避免运行中修改配置。
- 是否需要 credential unlock。
- 是否泄漏账号、密码、加密块或运行时字段。
- 前端是否统一走 `window.WebUIApi.request()` 和错误文案处理。
- 是否需要更新 `test/test_webui_contracts.py`。
