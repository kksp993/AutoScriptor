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
