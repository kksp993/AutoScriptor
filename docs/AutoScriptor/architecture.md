# AutoScriptor 架构基线

本页只记录当前 `src` 分支事实。它不是历史清单，历史方案不在主线里复活。

## 主线入口

```text
start.bat / local_start.bat
└─ scripts\run.bat electron
   └─ webapp\main.js
      └─ .venv\Scripts\python.exe -X utf8 services\webui\gui.py --electron

webui.bat / scripts\run.bat webui
└─ .venv\Scripts\python.exe -X utf8 services\webui\gui.py
   └─ services\webui\server.py
      └─ services\webui\static\
```

## 代码分层

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 桌面壳 | `webapp/` | 源码 Electron 启动、后端进程管理、加载本地 WebUI |
| WebUI | `services/webui/` | FastAPI API、页面、日志 WebSocket、配置/任务/更新面板 |
| 服务层 | `services/core/` | 调度器、任务管理、运行上下文、源码 Git 更新 |
| 自动化核心 | `AutoScriptor/` | 识别、控制、配置、路径、日志、截图和通用 API |
| 游戏任务 | `ZmxyOL/` | 任务注册、任务实现、导航和战斗流程 |
| 用户数据 | `data/` | 配置、账号、职业脚本、自定义任务 |
| 运行产物 | `logs/` | 日志、错误归档、截图、礼包码缓存 |
| 维护脚本 | `scripts/` | 安装、运行、更新和少量当前主线需要的维护脚本 |

## 数据边界

- 全局配置：`data/config.json`
- 配置模板：`data/config.template.json`
- 账号/角色/任务状态：`data/accounts/`
- 全局任务排序覆盖层：`data/config.json` 的 `task_ordering`
- 自定义任务：`data/custom_task/`
- 用户职业脚本：`data/battle_character/`
- 可变缓存和采集结果：`logs/`

代码里的路径入口统一使用 `AutoScriptor.utils.paths`。不要把运行数据放回 `docs/`，也不要恢复根目录 `tools/`。

## 任务注册边界

- `TaskRegistry` 保存运行时任务数据：函数、排序、参数元数据、说明、beta/custom/debug 标记。
- `cfg["tasks"]` 只保存用户配置：开关、下次执行时间、参数、调度窗口和星期限制。
- `task_ordering` 保存用户排序覆盖层：当前持久化可嵌套总顺序 `items`；`user_order` 是由 `items` 展平得到的兼容投影和旧数据导入 seed。它是全局配置，不写入账号 JSON。
- 两者用 slash 路径关联，例如 `每日任务/村庄/宠物培养`。
- 保存配置前必须剥离 `fn`、`order`、`param_meta`、`param_keys`、`_due`、`progress_display` 等运行时字段。
- 调度器收集到期任务时必须通过 `task_registry.has_task(path)` 过滤未注册残留叶子。
- `ZmxyOL/task/**/_order.txt` 是 legacy 源码导入/注册 seed；任务加载可读取它保持内置脚本稳定注册顺序，但用户显示和执行顺序由全局 `task_ordering` 投影决定，不在运行时反写源码树。
- 有效任务顺序通过确定性总排序计算：先递归展开用户拖拽保存的 `items` 分组顺序，再回退到当前任务树顺序、运行时注册顺序和路径字典序。旧版 `hard_edges`、`layout`、`group_order` 会被规范化忽略，不再参与显示或执行顺序。

## 动态 API 边界

- MuMu 适配器有动态转发：`BaseMumuControl.__getattr__` 会把未知属性转给当前 `Mumu().select(...)` 实例。
- `AutoScriptor` 和 `ZmxyOL/task` 里的控制、时间、识别辅助函数是任务作者 API；没有仓库内静态引用不等于可删。
- 可以删除已移除产品面的入口、脚本和文档，但不要只凭 `rg` 静态未命中删除 MuMu 控制属性、任务装饰器参数、`sleep/click/locate` 等任务脚本可调用面。

## 源码启动与更新边界

- Electron 只负责源码壳：创建加载窗口、清理本项目占用的 `5000` 端口、启动 `.venv\Scripts\python.exe -X utf8 services\webui\gui.py --electron`。
- Electron 壳在 `app.whenReady()` 前配置 Chromium render mode；默认 `AUTOSCRIPTOR_ELECTRON_RENDER_MODE=software` 只影响桌面壳，不改变浏览器访问 WebUI 的行为。
- 加载窗口必须先于端口清理和 Python 后端启动出现；端口清理失败要写启动日志并显示在加载页，不修改 Windows 控制台 code page。
- WebUI 更新器只处理源码 Git 通道：固定 `fetch origin main`、比较 `HEAD` 和 `origin/main` 的 ahead/behind，只有当前检出分支可快进到 `origin/main` 时才执行 `pull --ff-only origin main`。
- 更新器拒绝 detached HEAD、非 Git 工作区和脏工作区；Git stderr、启动失败和 timeout 要原样进入 `last_error`。
- 更新器不安装依赖。`requirements.txt`、`webapp/package*.json` 等依赖变更后，用户再运行 `scripts\install.bat`。

## 已移除产品面

当前主线不包含这些面：

- 发布包、安装器、wheelhouse、本地打包验收脚本。
- 旧 CLI 菜单。
- Canvas/Drawflow 脚本画布。
- Socket.IO 日志通道。
- Nuitka/冻结运行时兜底。
- VLM 实验链路。

相关测试里的引用一般是“不得恢复”的合同断言，不是待修复引用。

## 异常处理原则

- 启动、安装、更新、配置、加密、路径解析：明确失败，抛出具体错误。
- 配置/账号 JSON 写入：只走同目录临时文件加原子替换，替换失败即暴露为保存失败。
- WebUI 状态和动态选项探测：后端导入、配置读取、OCR/Paddle 探测失败必须显式返回错误，不合成空数组或 `unknown`。
- 设备控制、OCR、任务执行：只在运行边界捕获并记录，避免吞掉取消信号和程序错误。
- 错误归档、日志刷新、退出清理：允许保底，但只围绕 I/O、终端流、截图和现场记录失败。
- 不用“猜一个默认路径/默认通道/默认产品面”来让旧架构继续跑。
