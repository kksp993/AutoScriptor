# WebUI API Contract 当前基线

WebUI 后端是 FastAPI；静态前端位于 `services/webui/static/`，源码 Electron 壳位于 `webapp/`。

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

现状中仍有历史接口返回 `{"success": ...}`、`{"error": ...}` 或业务裸对象；不要在新接口继续扩散。HTTP 状态码必须有意义：参数错误 `400`，未授权/未解锁 `401/403`，运行冲突 `409`。前端通用错误解析必须兼容 FastAPI 的 `detail` 字段，否则 404/422 等框架错误会退化成空泛提示。

## 认证与解锁

- `deploy.password` 非空时，所有 `/api/*` 默认需要 `auth_token` Cookie 或 `X-Auth-Token`，豁免 `/api/auth` 和 `/api/deploy`。
- `/api/auth` 成功后写 `auth_token`，并清除旧 credential unlock token。
- 账号密码、真实设备动作等敏感操作使用 credential unlock cookie；主动重新验证会吊销旧 unlock。
- `POST /api/credential/revoke` 要求 runtime idle；运行中返回 `409 runtime_busy`，前端不能先乐观清空“已验证”状态。
- 登录和安全密码验证有频率限制。

## 核心状态

| 接口 | 说明 |
|------|------|
| `GET /api/init-status` | 后台初始化是否完成；初始化失败时 `ready=false` 并返回 `error` |
| `GET /api/refresh` | 公开配置快照；会消费配置变更、重读任务投影 |
| `GET /api/runtime/snapshot` | 主轮询入口：运行状态、调度器、任务汇总、下次执行、`config_version` |
| `GET /api/run/status` | 直接运行线程状态 |
| `POST /api/run` | 直接运行任务，或启用调度模式 |
| `POST /api/stop` | 请求协作式停止；返回轻量 `runtime` 投影供前端立即更新停止状态 |

前端不要新增散落的账号、调度器、运行状态多路轮询；主界面以 `runtime/snapshot` 为准。停止按钮是控制信号入口：`POST /api/stop` 返回后先应用响应中的轻量 `runtime` 状态，不能在点击处理函数里同步等待完整 `/api/runtime/snapshot` 或 `/api/refresh`，完整任务树/配置投影由后台刷新或常规轮询补齐。总览、调度页、每日/每周/通用/自定义任务页的“终止执行”必须复用总览 `stop-dispatch` 前端事件和同一个 `stopDispatch()` action，不要为任务页或调度页另接停止 API。

## 配置和任务

| 接口 | 说明 |
|------|------|
| `POST /api/config` | 保存 `app/emulator/ocr`，可包含 `scheduler` |
| `POST /api/config/sync` | 要求 runtime idle；同步所有配置并刷新 order map/log level/config_version；不清 `bg`，不重载任务注册表 |
| `POST /api/tasks` | 保存任务树，后端剥离运行时字段并刷新任务投影/order/config_version；不重载任务注册表 |
| `POST /api/tasks/reload` | 轻量 reload：要求 runtime idle，清 `bg`，刷新任务更新标记、任务投影、order map 和公开配置 |
| `POST /api/tasks/reload-all` | 完整 reload：要求 runtime idle，同步配置、重载职业脚本和任务注册表、刷新 UI map 缓存，并清 `bg` |
| `POST /api/enum-options` | 批量查询枚举选项，含 `BattleFlowName` 当前职业过滤；导入/枚举错误必须返回错误，不返回空列表伪装成功 |
| `GET /api/config/export` | 导出可迁移配置 |
| `POST /api/config/import` | 导入允许的配置段，剥离 deploy 密码/证书等敏感字段 |
| `GET/POST /api/deploy` | 读取/保存 deploy、notify、update、remote_access |

`POST /api/config` 保存时会把空的、`YOUR_` 占位的或 `:0` 结尾的 `emulator.adb_addr` 规范化为 MuMu 默认地址：`127.0.0.1:16384 + index*32`。保存失败必须返回标准 `api_error` JSON，并附带 `data_root/config_path/accounts_dir/current_account` 诊断字段；前端不能只显示“未知错误”。保存层只使用同目录临时文件加 `os.replace` 原子替换；`PermissionError/WinError 5` 等替换失败必须作为保存失败暴露出来，不再降级为直接覆写目标文件。

保存任务时必须通过 `TaskTreeService.strip_runtime_fields()`，不能持久化 `fn/order/param_meta/param_keys/beta/custom/debug_mode/task_description/task_doc_flow/_due/progress/progress_display` 等运行时字段。

Reload 边界：所有 reload 类操作都会清 `bg`；纯配置同步 `POST /api/config/sync` 不属于 reload，不清 `bg`。保存任务、切换账号/角色、账号解锁、更新账号凭据和普通配置导入只保存或同步配置并刷新 WebUI 投影，不做职业脚本和任务注册表完整重载。Editor 保存自定义任务脚本、启动初始化、调度器安全边界处理脚本变更，以及兑换码任务注册缺失兜底，仍使用完整 reload。

## 账号、角色和队列

| 接口 | 说明 |
|------|------|
| `GET /api/accounts` | 账号列表 |
| `POST /api/accounts/switch` | 切换账号并刷新任务投影/order/config_version；不重载任务注册表 |
| `POST /api/accounts/add` / `delete` | 新增/删除账号；新增账号使用标准 `api_ok/api_error` 响应 |
| `GET /api/characters` | 当前账号角色树 |
| `POST /api/characters/switch` | 切换角色并刷新任务投影/order/config_version；不重载任务注册表 |
| `POST /api/characters/add` / `delete` | 新增/删除角色 |
| `POST /api/characters/game_profession` | 设置角色游戏职业 |
| `GET /api/characters/all_tasks_summary` | 全角色任务汇总 |
| `GET/POST /api/dispatch/queue` | 跨角色调度队列 |

新增账号的业务成功条件是账号 JSON 写入、切换到新账号、凭据可解锁、调度登录状态失效和前端投影刷新完成；后续步骤失败必须沿 API 返回错误，不能把不完整生命周期上报为成功。调度器只执行 `dispatch_queue` 内角色；队列保存时会去重并过滤不存在的角色。

## 设备和 Editor

| 接口 | 设备会话 |
|------|----------|
| `GET /api/device/diagnostics?screenshot=false` | 默认不截图，不初始化 OCR/UI Map；附带只读 MuMu 路径发现建议 |
| `GET /api/device/discover?probe_adb=true` | 只读发现 MuMu 安装目录、MuMuManager、adb.exe 和可用 ADB 设备，不写配置 |
| `POST /api/device/discover/apply` | 运行空闲时应用已确认的发现结果到 `emulator` 全局配置并刷新 `config_version` |
| `GET /api/ocr-status` | 读取 Paddle/OCR 状态；探测异常返回 500，不合成 `false/0/unknown` |
| `/api/editor/ingest-image`、`ocr`、`color`、`save`、`store-template`、`locate-image` | 使用缓存截图/导入图，不启动模拟器 |
| `/api/editor/screenshot`、无缓存 `locate`、`remote/click`、`remote/swipe`、真实 `execute-code`、无缓存 `preview-extract` | 需要 `runtime_ctx.ensure_device_session()` |
| `POST /api/editor/execute-code/stop` | Editor 自定义代码执行中的终止入口；前端“终止执行”按钮只发送该请求，不再调用语法校验 |
| `POST /api/editor/save-custom-task` | Editor 保存脚本入口；不需要设备会话，接收保存表单和编辑器合并后的代码内容，写入 `data/custom_task` 并注册为 `自定义任务/...` |

Editor 真实设备动作需要 credential unlock；模拟执行且已有缓存图时应使用虚拟 `mixctrl`，不触碰真实设备。`/api/editor/execute-code` 的 running/stopping 状态会通过 `RuntimeController` 投影为 `reason="editor"`，因此运行期间配置、任务、账号、角色和 reload 类接口都应返回 `409 runtime_busy`。

MuMu 自动定位只在设置/诊断层运行：发现逻辑检查注册表和常见安装目录，并从安装目录推导 `mumu_folder`、`emu_path`、`adb_path`，可选探测已连接 ADB 设备。运行热路径仍依赖已持久化配置，不能在任务执行时临时扫盘。

`POST /api/editor/save-custom-task` 请求体约定：

```json
{
  "filename": "custom_task.py",
  "task_path": "自定义任务/示例/操作设置",
  "description": "一句话描述",
  "task_doc": "补充说明正文",
  "params": [
    {"name": "times", "type": "int", "description": "执行次数"},
    {"name": "mode", "type": "enum", "description": "模式", "enum_options": ["普通", "困难"]},
    {"name": "areas", "type": "enum_multi", "description": "区域", "enum_options": ["普通", "困难"]}
  ],
  "code": "click(T(\"确定\"))"
}
```

后端必须分别校验 `filename` 和 `task_path`，并对文件名做安全归一化，禁止路径穿越；旧 `name` 字段只作为兼容 fallback。保存产物是 UTF-8 Python 文件，位于 `data/custom_task/`，同目录临时文件写入后通过 `os.replace` 原子替换。裸片段会被包装为 `@register_task(path_cn="自定义任务/<name>", description=..., task_doc=...)`；`params` 会生成函数签名、字段说明，以及本地 `enum.Enum` 类型默认值，`enum` 表示单选，`enum_multi` 表示多选选项列表。完整自定义任务文件可以自行设置 `path_cn`，例如 `自定义任务/<name>`，但必须显式传入该参数；完整文件内已有元数据时由文件自身负责，不再把 `param_meta/task_doc_flow` 等运行期元数据写进配置。所有 `data/custom_task` 注册都会在后端归一到 `自定义任务/...` 根，前端自定义任务页只读取这个根；例如完整文件写 `path_cn="背包清空/进阶仙宝"` 时，WebUI 中显示为 `自定义任务/背包清空/进阶仙宝`，旧错误路径下的配置会迁移到归一后的路径。语法、模板生成、写入或完整重载失败必须返回结构化错误，不能静默成功；保存成功后通过 lifecycle service 触发完整 reload 并返回 `config_version`。

## 源码更新

| 接口 | 说明 |
|------|------|
| `GET /api/update/status` | 源码工作区 Git updater 状态；非 Git 工作区显示 `disabled`；detached HEAD 显示失败原因；返回 `remote_branch`、`ahead_count`、`behind_count`、`action_taken`、`restart_supported`、`restart_triggered` |
| `POST /api/update/check` | 单次 `git fetch origin main` 并比较 `HEAD` 与 `origin/main`；远端领先时 `state=available` 并返回更新日志，本地一致时 `state=up_to_date`，本地领先时 `state=ahead` |
| `POST /api/update/run` | 要求 runtime idle；工作区有本地改动时拒绝执行；否则 `fetch origin main`，只在当前检出分支可快进时执行 `pull --ff-only origin main`；未拉取时 `action_taken=none`，快进时 `action_taken=fast_forward`，完成后按运行模式通知后端重启 |

更新页只保留源码 Git 通道。非 Git 工作区或非源码运行环境必须显示为 disabled，不要引导用户执行不可用更新。检查目标固定为远端 `main` 分支；若本地相对 `origin/main` 既领先又落后，状态为 failed 并提示用户手动处理分叉。本地领先不是“已更新”，必须显示为 `ahead`，表示远端没有可拉取提交但本地含额外提交。Git stderr、timeout、启动失败必须进入 `last_error`，不能改写成空输出或泛化错误。更新器不安装 Python/npm 依赖；依赖文件变化后用户单独运行 `scripts\install.bat`。

## 错误归档、资讯、远程访问

| 接口 | 说明 |
|------|------|
| `/api/error-archives*` | 列表、详情、文件读取、批量删除、zip 导入 |
| `/api/news/*` | 4399 资讯、礼包码、代理页面 |
| `GET/POST /api/remote-access` | 远程访问配置和状态 |
| `POST /api/notify/test` / `POST /api/notify/save` | 通知测试与保存；保存要求 runtime idle |

错误归档路径必须经过安全文件名校验，zip 导入解压到新目录，不覆盖任意路径。

资讯页约定：

- 打开资讯页、WebUI 登录成功后停留在资讯页、或再次点击资讯入口时，前端都应调用 `/api/news/posts?force=1` 立即拉取远端列表，不等 30 分钟缓存。
- `/api/news/gift_codes?refresh=1` 只从官方公告近 10 天、最多 15 个帖子增量查找兑换码；记录已查帖子 ID 和仍有效兑换码，后续只查新增帖子。
- `/api/news/gift_codes/page` 是兑换码弹窗的内嵌页，只读取运行时 `logs/zmxy_redeem_codes.json`；表格列为序号、兑换码、到期时间、来源链接、操作，支持 Shift 连续选择和批量兑换。
- `/api/news/redeem_targets` 只返回账号名和 `服务器:角色名` 选择项；`POST /api/news/gift_codes/redeem` 需要 credential unlock 或安全密码，接受 `redeem_code` 或 `redeem_codes`，先切到所选账号/角色并强制自动登录，再按顺序以临时 `redeem_code` 参数执行内置一般任务 `一般任务/活动/兑换豪礼礼品兑换`。
- `/api/news/proxy` 遇到 4399 登录墙时会使用可用资讯通行证重试一次；缓存通行证失效时应重登后再拉取正文。
- `news.account = "85rwm3janyyc"` 与 `news.password = "123456"` 是唯一允许明文模板保留的公开资讯通行证，仅用于 4399 news/forum/gift-code 代理。
- 旧配置若没有 `news` 段，资讯代理按该公开通行证兜底；显式配置其他 `news.*` 时按敏感凭据处理。
- 其他 `news.*`、`game.*`、账号文件、token、证书、私钥、deploy 密码都按敏感信息处理；非公开 news/game 凭据用于论坛代拉前仍需要 credential unlock。

## 日志

- 实时日志使用 WebSocket `/ws/logs`。
- 不使用 Socket.IO。
- 静态资源缓存：`/vendor` 和 `/fonts` 可缓存，`/static/*.js/css` no-cache。

## 修改接口前检查

- 是否需要 `guard_idle()`，避免运行中修改配置。
- 是否需要 credential unlock。
- 是否泄露账号、密码、加密块或运行时字段。
- 前端是否统一走 `window.WebUIApi.request()` 和错误文案处理。
- 是否需要更新 `test/test_webui_contracts.py`。
