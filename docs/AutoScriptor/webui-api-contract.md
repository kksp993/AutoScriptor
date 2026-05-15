# WebUI API Contract

WebUI 新增或重构接口应统一使用以下响应形状。

## 响应格式

成功:

```json
{
  "ok": true,
  "config_version": 12
}
```

失败:

```json
{
  "ok": false,
  "error": "runtime_busy",
  "message": "当前调度器正在运行，请先点击「终止执行」再继续操作。",
  "code": "runtime_busy"
}
```

约定:

- HTTP 状态码必须有意义，业务冲突用 `409`，未验证用 `403`，参数错误用 `400`。
- 前端统一使用 `window.WebUIApi.request()`，错误文案统一走 `WebUIApi.errorMessage()`。
- 新接口不要直接返回裸 `{"error": ...}`；历史接口可逐步迁移。

## 核心轮询

- 主界面只保留 `/api/runtime/snapshot` 作为统一状态轮询入口。
- 独立页面可按需主动刷新，例如启动诊断页调用 `/api/device/diagnostics`。
- 不新增散落的账号、调度器、运行状态多路轮询。

## Editor 设备会话

Editor 接口分为两类:

- 离线图片接口只读 `_last_screenshot` 缓存，不应启动模拟器，例如 `/api/editor/ingest-image`、`/api/editor/ocr`、`/api/editor/color`、`/api/editor/save`、`/api/editor/store-template`、`/api/editor/locate-image`。
- 实时设备接口必须按需调用 `runtime_ctx.ensure_device_session()`，包括 `/api/editor/screenshot`、无缓存图时的 `/api/editor/locate`、`/api/editor/remote/click`、`/api/editor/remote/swipe`、真实 `/api/editor/execute-code`、无缓存图时的 `/api/editor/preview-extract`。

约定:

- WebUI 启动、普通轮询和默认诊断页不得为了“预加载”而创建 `mixctrl/mumu`。
- 实时设备接口第一次调用可能较慢，因为它会启动或确认 MuMu、拉起 App，并同步全局 API 引用。
- 设备会话失败统一返回可读错误，例如 `设备会话初始化失败: ...`；前端按钮应展示该错误，而不是静默吞掉或显示“未初始化”。
- 模拟执行且已有导入/截图缓存时使用虚拟 `mixctrl`，只在画布标注点击/滑动，不触发真实模拟器。

## 设备诊断

`GET /api/device/diagnostics?screenshot=false`

返回:

```json
{
  "ok": true,
  "diagnostics": {
    "adb_addr": "127.0.0.1:16416",
    "emulator_index": "1",
    "overall": {"status": "ok", "message": "Device diagnostics passed"},
    "checks": {
      "manager": {"status": "warn", "message": "MuMuManager version command failed; ADB fallback may still be usable"},
      "adb": {"status": "ok", "message": "ADB executable is available"},
      "adb_device": {"status": "ok", "message": "ADB device is ready"},
      "app": {"status": "ok", "message": "App is running"},
      "nemu_ipc": {"status": "skipped", "message": "Screenshot probe not requested"},
      "ocr": {"status": "skipped", "message": "OCR module has not been loaded"},
      "ui_map": {"status": "skipped", "message": "UI Map module has not been loaded"}
    }
  }
}
```

状态含义:

- `ok`: 当前层可用。
- `warn`: 可继续观察或 fallback，但有潜在风险。
- `error`: 当前层不可用，会阻断执行或截图。
- `skipped`: 本次未检查，例如默认不做 NemuIpc 截图探测，或 OCR/UI Map 模块尚未被运行期加载。诊断接口不会为了查看状态而主动初始化 OCR/UI Map。
