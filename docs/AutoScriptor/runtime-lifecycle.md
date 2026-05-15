# Runtime Lifecycle

本文档记录当前 WebUI/调度器/设备控制的生命周期约定，作为后续重构边界。

## 执行入口

- WebUI 启动只加载配置、任务注册、后台监控和可选 VLM，不主动初始化 `mixctrl/mumu`。
- 用户点击运行或调度器发现到期任务时，才调用 `runtime_ctx.refresh()`。
- `runtime_ctx.refresh()` 负责释放旧 NemuIpc、启动或确认 MuMu、拉起 App，并把新的 `mixctrl/mumu` 同步到兼容的全局变量。
- 停止按钮通过 `TaskManager` 取消事件、`Scheduler.request_stop()` 和直接执行线程中断协同完成；脚本内应使用 `AutoScriptor.sleep()`，不要直接 `time.sleep()`。

## 懒加载边界

- 模块级懒加载只负责避免 import 阶段副作用：导入 `AutoScriptor`、`DeviceFacade`、诊断页路由时，不应初始化 OCR、UI Map、MuMu、NemuIpc 或 `mixctrl/mumu`。
- 请求级按需初始化由 `runtime_ctx.ensure_device_session(reason=...)` 负责。只有明确需要实时设备的操作才能调用它，例如任务执行、Editor 刷新截图、实时定位补帧、遥控点击/滑动、自定义代码真实执行、无缓存的 `extract_info` 预览。
- Editor 的离线图片流程不应启动模拟器：`/ingest-image`、缓存图上的 OCR/颜色/保存/模板匹配，以及有缓存图的模拟执行，均只使用 `_last_screenshot`。
- 诊断页默认只做状态探测，不拉起截图；只有用户点击“截图探测”时才检查 NemuIpc 截图层。OCR/UI Map 状态显示为 `skipped` 代表模块尚未被运行期需要，不代表功能丢失。

## 设备通道

- `DeviceFacade` 是统一设备检查入口，集中处理 MuMuManager、ADB、App、NemuIpc、OCR、UI Map 状态。
- MuMuManager 用于官方 lifecycle 命令；若 `version/info/launch/app` 命令失败，但 ADB 已健康，运行链路允许降级继续。
- ADB 是点击、输入、App 启停和包状态的稳定 fallback。
- NemuIpc 仍是截图主路径，诊断页默认不触发截图探测，只有点击“截图探测”才检查该层。

## 性能副作用边界

- 默认只温和提升 Python 进程，不提升 MuMu 进程，避免影响同一机器上的 StarRailCopilot 等其他 MuMu 用户。
- 所有 MuMuManager subprocess 调用都会通过 `mumu_safe_subprocess()` 临时恢复普通优先级，避免子进程继承高优先级导致虚拟化/权限误判。
- `boost_mumu=True` 仅作为显式选项保留，不应在默认 WebUI/调度执行中启用。

## 配置写入

- 配置拆为全局 `config.json` 和账号文件 `accounts/*.json`。
- `TaskManager.config_transaction()` 负责运行期配置互斥。
- JSON 持久化使用同目录临时文件加 `os.replace()`，避免保存中断导致半截 JSON。
- 前端读写任务时必须以 `/api/runtime/snapshot` 和 `/api/tasks` 返回值为准，不用本地旧树覆盖后端新状态。
