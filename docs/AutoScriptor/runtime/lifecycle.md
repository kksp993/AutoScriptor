# Runtime Lifecycle 当前基线

本文记录 WebUI、调度器、设备会话、配置和热重载的当前边界。任何改动这些模块的任务都要同步更新本文件。

## 启动边界

- WebUI 启动后只做静态服务、日志 WebSocket、任务注册、后台监控代理和可选 VLM 初始化。
- 启动、刷新、普通轮询和默认诊断不应主动创建 `mixctrl/mumu`。
- 设备会话由明确需要实时设备的入口创建：任务执行、实时截图、遥控点击/滑动、无缓存定位、真实代码执行。
- `RuntimeContext` 是唯一运行态对象中心，负责 `mixctrl`、`mumu`、`bg`、`vlm_client` 和兼容全局变量同步。
- Electron portable 启动必须先创建可见加载窗口，再执行端口清理和 Python 后端启动。加载页要持续显示阶段日志，包括运行目录检查、端口检查、Python 进程创建、WebUI 模块导入、等待本地 WebUI 响应；不要让首次运行长时间无输出。

## 设备会话

| 方法 | 用途 |
|------|------|
| `runtime_ctx.ensure_device_session(reason=..., launch_app=True)` | 若尚无设备会话，则启动/确认 MuMu 和 App |
| `runtime_ctx.refresh(cancel_check=..., launch_app=True)` | 释放旧 NemuIpc，重建 `mixctrl/mumu` |
| `runtime_ctx.shutdown()` | 释放 NemuIpc 并清空运行态对象 |
| `runtime_ctx.status_dict()` | 返回 WebUI 展示用运行态摘要 |

`ensure_app_running()` 会：

1. 在启动 MuMuManager 前 `unboost()`，避免子进程继承高优先级。
2. 依据 `cfg["app"]["auto_start"]` 或显式参数启动模拟器和 App。
3. 解析 `app_to_start`，必要时写回配置。
4. 创建 `MixControl(mumu, serial=adb_addr)`。
5. 通过测试点击确认模拟器响应。
6. 按 `run_in_background` 隐藏窗口。

## 设备通道

- `DeviceFacade` 用于诊断页聚合 Manager、ADB、App、NemuIpc、OCR、UI Map 状态。
- MuMuManager 负责低频生命周期命令；`version` 等命令失败但 ADB 可用时通常是 warning。
- ADB 是点击、滑动、输入、按键、App 启停和包状态的稳定路径；高频输入优先直接走 `adb.exe`。
- MuMu TCP ADB 地址（如 `127.0.0.1:16384`）不会因为 `adb start-server` 自动出现在 `adb devices`；`DeviceFacade` 在 `get-state` 失败时会先 `adb connect <adb_addr>` 并重试，再判断端口错误或设备未启动。
- NemuIpc 仍是截图主路径。默认诊断不做截图探测；用户点击“截图探测”才检查该层。

## WebUI 运行状态

`RuntimeController` 合并两类执行状态：

| 状态来源 | 说明 |
|----------|------|
| direct_run | WebUI 直接执行指定任务 |
| scheduler | 调度器后台执行 |

保存配置、保存任务、切换账号/角色、重载任务等会先走 `guard_idle()`。运行中请求会返回 `409 runtime_busy`。停止按钮会同时：

- `TaskManager.request_cancel()`
- `Scheduler.request_stop()`
- `Scheduler.invalidate_login()`

任务脚本必须使用可取消 API，例如 `AutoScriptor.sleep()`。

## 配置与账号

- 全局配置：开发模式 `config.json`；发行版 `install.json.dataRoot/config.json`。
- 账号配置：`dataRoot/accounts/*.json`。
- 发行版或 Electron 指定 `AUTOSCRIPTOR_DATA_DIR` 时，旧配置里的绝对 `accounts.dir` 会迁移/归一到 `dataRoot/accounts`，避免继续写旧安装目录或 Program Files。
- 配置/账号保存优先使用同目录临时文件加原子替换；默认不强制 `fsync`，避免低内存、杀毒扫描或慢盘把小 JSON 写入拖成秒级阻塞。需要严格刷盘时设置 `AUTOSCRIPTOR_STRICT_FSYNC=1`。
- 纯全局配置保存（如基础配置、deploy、notify、update、remote_access）只写 `config.json`，不重写当前账号 JSON。任务、状态、账号、角色变更才写 `accounts/*.json`。
- 若 Windows ACL 允许写入但拒绝替换/删除（`WinError 5`），保存层会降级为直接写目标文件并记录 warning。完全不可写时仍返回包含 `dataRoot/config_path/accounts_dir` 的错误诊断。
- 当前角色的 `tasks` / `status` / `game_profession` 被展开到运行态 `cfg`。
- 写 JSON 使用同目录临时文件加 `os.replace()`。
- `WebUILifecycleService` 负责配置副作用顺序：修改内存、保存、重载任务、刷新 order map、唤醒调度、递增 `config_version`。新增账号完成写入和切换后，任务重载失败只记录 warning，不回滚创建结果。

WebUI 公开配置必须剥离账号、密码、加密块、运行时任务字段和 `_due` 等后端投影字段。

## 热重载

调度器 `ConfigWatcher` 监听：

- 当前 `config.json`
- 当前账号文件
- `data/custom_task/`
- `data/battle_character/`

如果未在执行任务，直接 `TaskManager.reload_tasks()`。如果正在执行，先 `cfg.reload_preserving_decrypted_credentials()` 同步磁盘变更，设置 `_reload_deferred`，等任务安全边界再重建任务注册表和职业脚本。

`TaskManager.reload_tasks()` 会：

1. 保留已解密凭据重新加载配置。
2. 清除 `ZmxyOL.*` 模块缓存。
3. `reload_battle_character_modules()` 重载职业脚本。
4. `force_reload_tasks()` 重建任务注册表。
5. 最后 `bg.clear(clear_signals=True)` 清理残留监听。

## 性能边界

- 首次真正使用 `click()`、`locate()`、`swipe()` 等 API 时会温和 boost Python 进程。
- 调度任务执行前先 `unboost()` 启动设备，设备就绪后 `boost(process_priority=ABOVE_NORMAL_PRIORITY_CLASS)`。
- 默认不提升 MuMu 进程；`boost_mumu=True` 只保留为显式选项。
- MuMuManager subprocess 调用使用 `mumu_safe_subprocess()` 临时恢复普通优先级。
- `app.cpu_cores` 可限制 Python 进程 CPU 亲和性，退出时恢复。

## 执行后动作

`config.json -> emulator.post_execution` 支持：

| 值 | 行为 |
|----|------|
| `none` / `null` | 不额外处理 |
| `close_game_only` | 只关闭游戏 App |
| `close_mumu` | 安全关闭游戏和模拟器 |
| `goto_main` | 尝试回到主界面 |

仅当本轮 pipeline 有真实成功或失败统计时执行。若本轮只执行 debug 任务，会跳过收尾，保留现场。

自动跨角色调度在执行后动作前，会先切回 `dispatch_queue` 的第一个有效角色并确认登录。单任务直跑和纯 debug 任务不做这个角色回切。

## 维护检查

修改运行期代码时必须核对：

- WebUI 启动和普通轮询是否仍不触发设备初始化。
- 设备会话失败是否能通过 API 返回可读错误。
- 停止按钮是否能打断启动、登录、任务 sleep、retry 等等待。
- 热重载是否不会在任务中途清空任务局部 `bg` 监听。
- `cfg`、账号文件和前端任务树是否仍保持同一事实。
