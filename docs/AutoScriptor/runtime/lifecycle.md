# Runtime Lifecycle 当前基线

本文记录 WebUI、调度器、设备会话、配置和热重载的当前边界。任何改动这些模块的任务都要同步更新本文档。

## 启动边界

- Source Electron configures Chromium render mode before `app.whenReady()`. `AUTOSCRIPTOR_ELECTRON_RENDER_MODE` supports `software` (default, hardware acceleration disabled plus GPU composition/raster/zero-copy switches), `d3d11` (GPU kept with ANGLE D3D11), and `default` (no Electron render switches for comparison). The shell logs the render mode and GPU feature status; browser access to `http://127.0.0.1:5000` is unchanged.
- OCR 在进程启动时冻结 `ocr.use_gpu`、普通模型和数字模型。全局 OCR、线程局部 OCR
  和数字 OCR 都使用该快照；保存新配置不会热切换已加载或稍后创建的 Paddle 引擎。
  `GET /api/ocr-status` 通过 `configured_*`、`runtime_*`、`engine_*` 和
  `restart_required` 暴露三层状态，变更设备或模型后必须重启进程。
- Paddle/PaddleOCR 的 Python 运行时导入和 OCR 模型构造都在 OCR 后台线程执行。
  模型文件命中本地缓存仍需完成每个新进程的运行时导入和模型构造；启动日志分别记录
  运行时导入、模型阶段和总耗时，`Model files already exist` 表示模型文件缓存已命中。
- 导入 `MumuAdaptor.mumu` 不得通过 `api.screen.gui` 提前启动 OCR 后台线程；`Mumu.auto`
  在实际访问时才按需导入 GUI/OCR。这样 NemuIpc 的 `uiautomator2/adbutils/pkg_resources`
  兼容依赖会先完成主线程导入，避免与 Paddle 后台导入争用 Python import 状态。
- Electron/Chromium 的渲染模式与 Paddle OCR 设备互相独立；关闭 Electron 硬件加速
  不会阻止 OCR 使用 CUDA GPU。
- WebUI 启动后只做静态服务、日志 WebSocket、任务注册和后台监控代理。
- 后台初始化必须完成运行时上下文、任务重载和配置读取后才把 `/api/init-status` 标记为 `ready=true`；失败时保留 `ready=false` 和错误信息，不伪装成已完成。
- 启动、刷新、普通轮询和默认诊断不应主动创建 `mixctrl/mumu`。
- 设备会话由明确需要实时设备的入口创建：任务执行、实时截图、遥控点击/滑动、无缓存定位、真实代码执行。
- `RuntimeContext` 是唯一运行态对象中心，负责 `mixctrl`、`mumu`、`bg` 和兼容全局变量同步。
- 长生命周期模块不要保存 `from AutoScriptor import *` 或 `from AutoScriptor import mixctrl` 得到的 `mixctrl/mumu` 快照；需要运行态对象时从 `runtime_ctx` 或 `AutoScriptor.core.api` 读取当前值。
- 源码 Electron 启动必须先创建可见加载窗口，再执行端口清理和 Python 后端启动。加载页要持续显示阶段日志，包括运行目录检查、端口检查、Python 进程创建、WebUI 模块导入、等待本地 WebUI 响应；不要让首次运行长时间无输出。
- Electron 不修改 Windows 控制台 code page。后端编码通过 `-X utf8`、`PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8` 保证。
- 端口 `5000` 清理只会杀本项目目录匹配到的旧进程；清理失败必须写 `startup.log` 并显示在加载页，不能静默吞掉。

## 设备会话

| 方法 | 用途 |
|------|------|
| `runtime_ctx.ensure_device_session(reason=..., launch_app=True)` | 若尚无设备会话，则启动/确认 MuMu 和 App |
| `runtime_ctx.refresh(cancel_check=..., launch_app=True)` | 释放旧 NemuIpc，重建 `mixctrl/mumu` |
| `runtime_ctx.shutdown()` | 释放 NemuIpc 并清空运行态对象 |
| `runtime_ctx.status_dict()` | 返回 WebUI 展示用运行态摘要 |

`ensure_app_running()` 会：

1. 依据 `start_emulator` 确认 MuMu 进程存在；`MuMuManager launch` 返回成功只代表启动命令已被接受。
2. 无论 MuMu 是刚启动还是已在运行，都等待配置的 TCP ADB 串号重连为 `device`，并确认 `sys.boot_completed=1`。
3. 按 `launch_app` 解析并启动 `app_to_start`，必要时写回配置。
4. 创建 `MixControl(mumu, serial=adb_addr)`。
5. 通过测试点击确认模拟器响应。
6. 按 `run_in_background` 隐藏窗口。

`debug_mode` 只跳过调度器的自动登录、任务前重启和常规失败恢复，不跳过设备会话的基本就绪检查。重启设备的任务应先调用 `runtime_ctx.shutdown()` 释放旧 NemuIpc 和运行态引用，再重启 MuMu 并通过 `runtime_ctx.refresh()` 建立新会话。

## 设备通道

- `DeviceFacade` 用于诊断页聚合 Manager、ADB、App、NemuIpc、OCR、UI Map 状态。
- MuMuManager 负责低频生命周期命令；`version` 等命令失败但 ADB 可用时通常是 warning。
- ADB 是点击、滑动、输入、按键、App 启停和包状态的稳定路径；高频输入优先直接走 `adb.exe`。
- MuMu TCP ADB 地址（如 `127.0.0.1:16384`）不会因为 `adb start-server` 自动出现在 `adb devices`；`DeviceFacade` 在 `get-state` 失败时会先 `adb connect <adb_addr>` 并重试，再判断端口错误或设备未启动。
 - MuMu TCP ADB 地址（如 `127.0.0.1:16384`）不会因为 `adb start-server` 自动出现在 `adb devices`；`DeviceFacade` 在配置串号不是 `device` 时会先 `adb disconnect <adb_addr>` 再 `adb connect <adb_addr>` 并重试。已列出但状态为 `offline` 的 TCP 串号只做 `connect` 会回 `already connected` 却不恢复，必须 disconnect 后再 connect。
- NemuIpc 仍是截图主路径。默认诊断不做截图探测；用户点击“截图探测”才检查该层。
- NemuIpc 截图返回后按 `1280x720` 横屏绝对像素合同检查帧尺寸。尺寸不符只输出节流 warning；原始帧保持不变并继续交给调用方，不自动缩放、不终止设备会话或当前任务。
- NemuIpc 原生连接按单通道使用：截图、点击、长按、滑动、拖拽、释放触摸和 disconnect 必须通过 `NemuIpc` 公开方法串行进入，不能在运行期直接调用底层 `nemu_ipc.nemu_ipc.*`。后台检测线程和战斗移动线程共享同一连接时，用串行化解决确定性争用，不用扩大重试或吞掉超时。

## WebUI 运行状态

`RuntimeController` 合并运行互斥状态：

| 状态来源 | 说明 |
|----------|------|
| direct_run | WebUI 直接执行指定任务 |
| scheduler | 调度器当前正在执行一轮到期任务；单纯 `state=running` 不算占用 |
| editor | Editor `/api/editor/execute-code` 自定义代码执行 |

调度激活状态与执行占用状态必须分开：`SchedulerState.RUNNING` 表示后台调度保持启用并等待下一执行点，`scheduler.executing/busy` 只表示调度当前持有共享执行闸门。调度已启用但空闲时，任务列表、Editor 和配置操作均可继续；它们取得闸门后，调度线程若到期会阻塞等待，释放后自动继续且仍保持 `running`。调度当前正在执行时，手动入口返回 `409 runtime_busy` 并提示等待本轮结束，不要求停止调度。

任务列表直接执行、Editor 代码执行以及 Editor `remote/click` / `remote/swipe` 都使用同一个执行闸门。入口的状态预检仅用于友好提示，真正互斥由非阻塞取得闸门保证，避免“检查时空闲、启动时撞上调度”的竞态。调度线程使用阻塞取得闸门，因此不会与已经开始的手动操作并发点击。

保存配置、同步配置、保存通知设置、保存任务、切换账号/角色、重载任务、重新验证/吊销凭据、源码更新执行等会先走 `guard_idle()`。真正执行中请求会返回 `409 runtime_busy`；调度仅启用但空闲时不阻断。停止按钮会同时：

- `TaskManager.request_cancel()`
- `Scheduler.request_stop()`
- `Scheduler.invalidate_login()`

`/api/stop` 发出协作式取消信号，同时把调度器恢复为 `pending`、清零连续错误次数并清除本调度周期 retry 耗尽记录；取消信号会保留到任务协作退出，终止后的失败结果不重新占用错误额度。接口仍只返回轻量 runtime 状态，前端应立即呈现停止中/待运行，不在按钮回调里同步等待完整任务树快照或配置刷新；完整 `/api/runtime/snapshot` 由后台刷新和常规轮询补齐，避免调度收尾写状态时把 UI 操作卡住。总览、调度页和任务列表页必须统一走总览 `stop-dispatch` / `stopDispatch()` 前端入口。

任务脚本必须使用可取消 API，例如 `AutoScriptor.sleep()`。

Editor 自定义代码执行由 `/api/editor/execute-code` 拥有路由内执行状态，并通过 `RuntimeController` 的 `editor` 外部状态投影进入统一 busy/stop/status：接口会拒绝与当前 direct run / scheduler execution 并行运行，但不因调度器仅保持激活而拒绝。运行期间配置保存、任务保存、账号/角色切换和 reload 仍会被 `guard_idle()` 拦截。执行体放入工作线程，避免阻塞 FastAPI 事件循环；前端“终止执行”调用 `POST /api/editor/execute-code/stop`，后端复用 `TaskManager.request_cancel()` 触发 `AutoScriptor.sleep()`、`click()`、`locate()` 等协作式取消点。执行结束后会清理本次 editor 执行状态、取消标记并释放执行闸门。

## 配置与账号

- 全局配置：源码运行使用 `data/config.json`。
- 账号配置：`data/accounts/*.json`。
- 自定义任务：`data/custom_task/`。
- 职业脚本：`data/battle_character/`。
- 日志与错误归档：`logs/`。
- 配置/账号保存只使用同目录临时文件加原子替换；默认不强制 `fsync`，避免低内存、杀毒扫描或慢盘把小 JSON 写入拖成秒级阻塞。需要严格刷盘时设置 `AUTOSCRIPTOR_STRICT_FSYNC=1`。
- 纯全局配置保存（如基础配置、deploy、notify、update、remote_access）只写 `data/config.json`，不重写当前账号 JSON。任务、状态、账号、角色变更才写 `accounts/*.json`。
- 若 Windows ACL 允许写入但拒绝替换/删除（`WinError 5`），保存层直接失败并交给 WebUI 返回包含 `dataRoot/config_path/accounts_dir` 的错误诊断，不再直接覆写目标文件。
- 当前角色的 `tasks` / `status` / `game_profession` 被展开到运行态 `cfg`。
- 全局任务排序覆盖层 `task_ordering` 存在 `data/config.json`，当前保存用户拖拽得到的可嵌套总顺序 `items`；`user_order` 是展平后的兼容投影。它不写入账号 JSON，也不改变 `cfg["tasks"]` 的树形目录。
- 写 JSON 使用同目录临时文件加 `os.replace()`。
- `WebUILifecycleService` 负责配置副作用顺序：修改内存、保存、按场景选择配置同步/轻量 reload/完整 reload、刷新 order map、唤醒调度、递增 `config_version`。新增账号完成写入和切换后，投影刷新失败会沿 API 返回错误，不再把不完整生命周期上报为成功。

任务顺序保存只使用 `POST /api/task-ordering`：保存 `items` 分组顺序并派生 `user_order`，要求 runtime idle，并刷新 WebUI order map 与调度器投影。旧版图布局接口 `POST /api/task-ordering/layout` 仅作为兼容 no-op 保留，不再保存画布坐标或影响执行顺序。

任务树保存和排序保存的并发边界分为两层：后端通过 `WebUILifecycleService.config_operation()` 串行完成内存修改、文件保存、投影刷新和版本递增；前端把 `POST /api/tasks` 与 `POST /api/task-ordering` 放入同一个 FIFO 提交序列，并在入队时冻结请求快照。排序接口只返回排序投影，前端不得用排序响应替换 `configData.tasks` 中尚未提交的任务草稿。

`GET /api/runtime/snapshot` 可能与前端提交同时在途。轮询响应在根据 `config_version` 触发完整 `/api/refresh` 前，必须等待任务持久化序列稳定排空，再与响应处理时的当前公开版本比较；只有响应版本更大时才允许刷新，不能让请求发出前的旧版本基线引发全量配置回填并覆盖本地草稿。

WebUI 公开配置必须剥离账号、密码、加密块、运行时任务字段和 `_due` 等后端投影字段。

## 热重载

调度器 `ConfigWatcher` 监听：

- 当前 `data/config.json`
- 当前账号文件
- `data/custom_task/`
- `data/battle_character/`

如果未在执行任务，直接 `TaskManager.reload_tasks()`。如果正在执行，则先 `cfg.reload_preserving_decrypted_credentials()` 同步磁盘变更，设置 `_reload_deferred`，等任务安全边界再重建任务注册表和职业脚本。

调度器自己写入任务状态、进度或 `next_exec_time` 时，也会更新 `data/config.json` 或当前账号文件。此类内部持久化只用于同步 WebUI 展示，不应在下一轮被误判为外部配置变更并再次触发 `TaskManager.reload_tasks()`；调度循环会把已处理的配置/账号 JSON 写入标记为已见。`data/custom_task/` 和 `data/battle_character/` 的脚本变更仍按热重载处理。

WebUI reload 分三类：

1. 轻量 reload：`POST /api/tasks/reload` 要求 runtime idle，执行 `bg.clear(clear_signals=True)`，刷新调度器任务更新标记、任务树投影、order map 和公开配置；不重新加载 `cfg`，不清 `ZmxyOL.*` 模块，不重载职业脚本，不调用 `force_reload_tasks()`。
2. 配置同步：`POST /api/config/sync` 执行 `cfg.reload_preserving_decrypted_credentials(security_key)`，刷新 order map，应用 WebUI log level，并递增 `config_version`；它不属于 reload，不清 `bg`，不重载任务注册表。
3. 完整 reload：`POST /api/tasks/reload-all`、Editor 保存自定义任务、启动初始化、调度器安全边界处理脚本变更，以及兑换码任务注册缺失兜底，走 `TaskManager.reload_tasks()`，并刷新 `AutoScriptor.utils.ui_map` 模块级 `ui` 缓存。所有 reload 类操作最终都要清 `bg`；配置同步不清 `bg`。

任务列表页和总览页的“刷新”都使用完整 reload，随后读取一次运行时快照。这样新增、删除或修改任务脚本后，手动刷新会重新扫描任务、重建注册表，并同步任务树与总览汇总；运行时忙碌期间仍拒绝重载。

自定义任务导入失败会记录到公开配置的 `custom_task_load_errors`。本轮自定义任务存在导入错误时，任务加载会跳过 stale 自定义任务配置清理和本轮 `cfg.save_config()`，避免把临时坏脚本误判为已删除任务并持久化清空用户配置。

保存任务、切换账号/角色、账号解锁、更新账号凭据和普通配置导入只保存或同步配置并刷新投影/order/config_version，不重建职业脚本和任务注册表。

自动跨角色调度、重试轮切换角色和执行后回切首个调度角色也使用 `TaskManager.switch_character()` 或 `cfg.switch_character()` 做轻量切换；这些路径只刷新登录状态和 WebUI 投影，不走完整 reload。

`TaskManager.reload_tasks()` 会：

1. 保留已解密凭据重新加载配置。
2. 清除 `ZmxyOL.*` 模块缓存。
3. `reload_battle_character_modules()` 重载职业脚本。
4. `force_reload_tasks()` 重建任务注册表。
5. 最后 `bg.clear(clear_signals=True)` 清理残留监听。

## 性能边界

- 源码运行不修改 Windows 电源策略、CPU 亲和性、Python 进程优先级、任务线程优先级或 MuMu 进程优先级。
- `AutoScriptor.utils.perf` 已移除；不要用兼容壳、重试或兜底恢复主机级 boost。
- 调度器、WebUI 直接运行和 MuMuManager subprocess 都按普通系统调度运行，不围绕任务生命周期切换 boost/unboost。
- 性能排查优先看截图/OCR频率、截图复用、ADB 连接、NemuIpc 串行化和任务循环，不用主机级优先级兜底。
- `Hero.way_to_exit()` 的出口检测交给 bg 监听；主线程只做分阶段移动、停顿确认和失败微调。退出位移用 `mumu` 长按，位移后切回 `nemu` 继续识别。出口标记使用 `战斗-离开标记` 的倒计时 `秒` 判断站位，完成条件仍必须是加载、回家或抽牌等离开后的状态；检测慢半拍时不能继续大步移动。不要把私有检测线程、OCR 节流或复杂目标分类塞回离开关卡逻辑。

## 执行后动作

`data/config.json -> emulator.post_execution` 支持：

| 值 | 行为 |
|----|------|
| `none` / `null` | 不额外关闭游戏或模拟器 |
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
