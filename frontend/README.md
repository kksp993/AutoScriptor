# frontend — 前端

Vue 3 + Element Plus 页面，以及 Electron 桌面壳。

## 现有来源

| 位置 | 职责 |
| --- | --- |
| `services/webui/static/index.html` | 页面骨架、CSP、脚本加载顺序 |
| `services/webui/static/js/app.js` | 根组件与全局状态 |
| `services/webui/static/js/components/` | 各面板（Overview、Scheduler、TaskPanel、EditorPanel、Settings 等） |
| `services/webui/static/js/core/` | `api.js`、`taskStatusTheme.js` |
| `services/webui/static/js/stores/` | `runtimeStore.js` |
| `services/webui/static/css/style.css` | 样式 |
| `services/webui/vendor/` | 第三方前端库 |
| `webapp/` | Electron 壳：`main.js`、`preload.js`、`renderer/` |

## 注意

- 静态资源由后端挂载，路径是 `/static` 与 `/vendor`；搬迁后必须同步 `backend` 的挂载点。
- `index.html` 用 `?v=N` 做缓存失效，改动 JS 时要一起改版本号，`test/test_webui_contracts.py` 有对应断言。

## 不负责

- API 实现 → `backend/`
- 调度逻辑 → `orchestrator/`
