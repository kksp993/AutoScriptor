# AutoScriptor 架构基线

本页只记录当前 `src` 分支事实。它不是历史清单，历史方案不在主线里复活。

## 主线入口

```text
start.bat
└─ scripts\run.bat electron
   └─ frontend\electron\main.js
      └─ .venv\Scripts\python.exe -X utf8 backend\webui\gui.py --electron

webui.bat / scripts\run.bat webui
└─ .venv\Scripts\python.exe -X utf8 backend\webui\gui.py
   └─ backend\webui\server.py
      └─ backend\webui\static\
```

## 代码分层

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 前端 | `frontend/electron/`（Electron 壳）+ `backend/webui/static/`（Vue 页面与静态资源，由 FastAPI 挂载） | 桌面壳与页面 |
| 后端 | `backend/`（`core/` 运维 + `webui/` 服务） | FastAPI API、日志 WebSocket、安全、更新与通知 |
| 编排层 | `orchestrator/` | 定时、排序、跨角色派发、执行闸门、retry、任务注册装配 |
| 任务脚本 | `tasks/` | `@register_task` 任务实现与运行时任务状态 |
| 自动化核心 | `AutoScriptor/` | 识别、控制、配置、路径、日志、设备会话、截图和通用 API |
| 游戏业务 | `ZmxyOL/` | 账号（`accounts/`，含 `crypto`）、角色（`character/`）、导航、战斗、参数表 |
| 用户数据 | `data/` | 配置、账号、职业脚本、自定义任务 |
| 运行产物 | `logs/` | 日志、错误归档、截图、礼包码缓存 |
| 维护脚本 | `scripts/` | 安装、运行、更新、构建 import wheel 和少量当前主线需要的维护脚本 |

编排层内部再分七个模块，各回答一个问题，依赖单向：

| 模块 | 回答的问题 |
| --- | --- |
| `orchestrator/model.py` | 任务集长什么样、什么时候到期（纯查询，无 IO/线程/设备） |
| `orchestrator/catalog.py` | 任务集从哪来：发现、导入顺序、自定义任务、启动装配 |
| `orchestrator/scheduler.py` | 什么时候跑、跑谁、在哪个设备会话 |
| `orchestrator/task_manager.py` | 单个任务怎么执行、重试、恢复 |
| `orchestrator/projection.py` | WebUI 能看见什么、保存/重载怎么排序副作用 |
| `orchestrator/delivery.py` | 有什么要送出去：桌面通知、onepush、OneBot QQ、角色结果 |
| `orchestrator/facade.py` | 组合根与执行互斥（`orchestrator` 单例、`RuntimeController`） |

依赖方向单向，每层都不反向 import：

```text
backend -> orchestrator -> tasks -> ZmxyOL -> AutoScriptor
```

后端只通过 `orchestrator.orchestrator` 调用编排层，装配在 `orchestrator/facade.py` 完成一次。

同一条依赖链还落成两个可安装发行体，供「不拿源码写脚本」的场景使用：`autoscriptor` 只含
`AutoScriptor/`，`zmxyol` 含 `ZmxyOL/` 与 `tasks/` 并依赖前者。`tasks/` 跟着 `ZmxyOL/`
走是因为两者互相 import（`ZmxyOL` 重导出 `tasks.register_task`，`tasks/task_register.py`
又 `from ZmxyOL import *`），拆开就是一对循环依赖。构建与边界见
[两个可安装 wheel](operations/library-packages.md)。

## 数据边界

- 全局配置：`data/config.json`
- 配置模板：`data/config.template.json`
- 账号/角色/任务状态：`data/accounts/`
- 全局任务排序覆盖层：`data/config.json` 的 `task_ordering`
- 运行时日历：`cfg` 拍平视图里的 `year` / `month` / `day` / `weekday`（`weekday` 为 `1=周一 ... 7=周日`）。它不在 `_GLOBAL_KEYS` 里，因此**永不落盘**，由 `AutoConfig._refresh_flat_config()` 在每次生成视图时写入，只反映进程当前时间。任务脚本可以直接下标读取，不需要先保存一次配置。
- QQ 结果通知：`data/config.json` 的 `notify.qq`；角色结果聚合与 OneBot 发送分离，见 [通知边界](operations/qq-notifications.md)。
- 可选本机 QQ 机器人：`backend/core/qq_bot.py` 管理官方包安装与独立启动，运行文件和令牌在
  Git 忽略的 `.autoscriptor/qq-bot`；WebUI 通过 lifecycle 接收连接配置，不把安装逻辑放进游戏任务。
- 自定义任务：`data/custom_task/`
- 用户职业脚本：`data/character/`
- 可变缓存和采集结果：`logs/`

代码里的路径入口统一使用 `AutoScriptor.utils.paths`。不要把运行数据放回 `docs/`，也不要恢复根目录 `tools/`。

## 任务注册边界

- `TaskRegistry` 保存运行时任务数据：函数、参数 spec、说明、custom 标记，以及作者声明的 `reschedule`/`debug` 默认值。参数 spec 由 `describe_signature(fn)` 生成，默认值/表单/执行解码共用（见 [任务脚本编写](tasks/script-authoring.md#参数)）。
- `cfg["tasks"]` 是**以任务 id 为键的平表**，只保存用户配置：开关、下次执行时间、参数、调度窗口和星期限制。
- 一个任务有两个字符串，别混：`id` 是身份（`cfg["tasks"]` 和 `task_ordering` 的键），`path` 是显示位置（UI 树、执行顺序、参数标签），例如 `每日任务/村庄/宠物培养`。`id` 就是任务名（文件名去掉 `.py`），所以**换目录不动用户数据**；只有重命名文件时在 `@register_task(id="旧任务名")` 里把身份钉住。
- `task_ordering` 保存用户排序覆盖层，**同样以 id 为键**：持久化可嵌套总顺序 `items`；`user_order` 是由 `items` 展平得到的兼容投影和旧数据导入 seed。它是全局配置，不写入账号 JSON。存储说 id、投影和 WebUI 说显示路径，两个键空间只在 `retarget_ordering_overlay()` 处换键。
- `cfg["tasks"]` 是注册集的镜像：注册按 id 写条目，加载末尾 prune 掉没有任务认领的条目（`catalog.prune_stale_tasks()`）。UI 树由 `TaskTreeService.build_task_tree()` 按显示路径拼出、叶子带 `id`，保存时 `flatten_payload_tasks()` 拼回平表；**存储从不依赖树的形状**。
- 保存配置前必须剥离 `fn`、`order`、`param_meta`、`param_keys`、`_due`、`progress_display`、`id` 等运行时字段；`param_meta` 由 spec 现算，`id` 只活在线上的 payload 里，由键本身表达。
- 调度器收集到期任务时必须通过 `task_registry.has_task(path)` 过滤未注册残留条目。
- 内置任务的默认顺序来自源码路径排序；用户显示和执行顺序由全局 `task_ordering` 投影决定，不在运行时反写源码。
- 有效任务顺序通过确定性总排序计算：先把存储里的 id 键 overlay 换成显示路径，再递归展开用户拖拽保存的 `items` 分组顺序，最后回退到当前注册顺序和路径字典序。旧版 `hard_edges`、`layout`、`group_order` 会被规范化忽略，不再参与显示或执行顺序。

## 任务重载边界

任务重载重建两类模块：任务脚本（让 `@register_task` 再跑一遍，含 `tasks` 包和汇总 `@flow` 的 `tasks.battle_task_params`），以及游戏层的纯逻辑模块（`ZmxyOL/nav`、`ZmxyOL/battle` 的战斗流程、包名解析）。**判据是「有没有对象被别人拿着」**：持有跨边界对象的模块保留，其余重建。

| 保留 | 原因 |
|------|------|
| `tasks.task_register` | 注册表单例。重新导入会造出第二个空注册表，而任务管理器、任务目录和 stale 清理仍读第一个。 |
| `tasks.task_params` / `task_state` / `time` | 编写期基础设施，不携带每轮状态；`task_params` 按类身份识别 `TableParam` 默认值。 |
| `ZmxyOL.battle.table_param` | 定义 `TableParam`；`tasks/task_params.py` 用 `isinstance` 判它，第二个副本会让所有已存表格默认值认不出来。 |
| `ZmxyOL.accounts*` | 账号域，导入时向 AutoScriptor 注册过后端；`orchestrator.projection` 持有它的 `INJECTED_TASK_FIELDS`。 |
| `ZmxyOL.character.profession` | `GAME_PROFESSIONS` 被 `projection` 和总览路由持有。 |
| `ZmxyOL.character` / `hero` / `plan` | 持有 `Hero` 基类、职业注册表和 `h` 单例；`hero` 由 `reload_character_modules()` **就地**重载（重新执行职业脚本），重新导入会造出第二份注册表和第二个 `h`。`plan` 的 `BattlePlan` 被 `data/character/hero.py` 在导入时绑定，而该文件不重跑。 |
| `ZmxyOL.character._user_*` | 职业脚本，模块名是内容哈希、没有 finder，由 `reload_character_modules()` 重跑。 |

两份保留清单和 `is_reloadable_module()` / `reload_game_layer_modules()` 都在 `orchestrator/catalog.py`，`test/test_task_register/test_task_reload_contract.py` 钉住它们——其中一组用例真的跑一次重建，断言逻辑模块被换掉、而 `TableParam` 与 `Hero`/`h` 的身份不变。重建后的 `mm` 是干净实例（believed region 归零），导航会重新定位而不是沿用旧判断。stale 叶子清理在注册表为空时拒绝执行：那表示注册没落到读它的注册表上，而不是用户配置过期。详见 [运行生命周期](runtime/lifecycle.md#重载保留哪些模块)。

## 动态 API 边界

- MuMu 适配器有动态转发：`BaseMumuControl.__getattr__` 会把未知属性转给当前 `Mumu().select(...)` 实例。
- `AutoScriptor` 和 `tasks/` 里的控制、时间、识别辅助函数是任务作者 API；没有仓库内静态引用不等于可删。
- 可以删除已移除产品面的入口、脚本和文档，但不要只凭 `rg` 静态未命中删除 MuMu 控制属性、任务装饰器参数、`sleep/click/locate` 等任务脚本可调用面。

## 设备输入通道边界

- 默认输入走 Nemu IPC（`external_renderer_ipc.dll` 的 finger/touch 通道）：点击、滑动、文本输入与截图同源，没有 ADB subprocess 开销。`MixControl.mode` 默认 `"nemu"`；`"mumu"`（ADB）只作为显式回退。
- IPC 输入失败（`NemuIpcError` / `RequestHumanTakeover`）时 `MixControl` 自动把本次运行回退到 ADB 并记录 error 日志；`switch_to_nemu()` 是复位快速通道的唯一入口。不要因为单次失败把热路径无条件改回 ADB，也不要吞掉回退日志。
- 编号手指（1..10）是 IPC 原生的多点触控通道：`finger_down/finger_move/finger_up/multi_finger_down` 与普通 `click/swipe` 的触点互相独立。实时闭环步骤用它「按住/松开」，只在状态翻转时发边沿，且任何退出路径都要 `release_all_fingers()` 兜底。
- 截图与输入可以并发（同一连接实测零错误）：`NemuIpcImpl.io_lock` 只保护连接管理与复用缓冲，不是截图/输入的全局互斥；`NemuIpc._ipc_lock` 只用于复合手势（点击/滑动）之间的互斥。不要恢复跨实例的全局锁，也不要把 worker 线程的截图逻辑包进调用方的锁。
- 实时区域检测用 `screenshot_region` 只转换 ROI；不要在热路径上对全帧截图做 OCR 循环。
- NemuIpc 截图返回复用缓冲之上的视图：拿到帧后要么立即消费，要么复制需要保留的部分，不要跨下一次采集持有。

## 源码启动与更新边界

- Electron 只负责源码壳：创建加载窗口、清理本项目占用的 WebUI 端口（先按 `AUTOSCRIPTOR_PORT`／缺省 `5000` 挑一个空闲端口，再把同一个端口通过环境变量交给后端）、启动 `.venv\Scripts\python.exe -X utf8 backend\webui\gui.py --electron`。
- Electron 壳在 `app.whenReady()` 前配置 Chromium render mode；默认 `AUTOSCRIPTOR_ELECTRON_RENDER_MODE=software` 只影响桌面壳，不改变浏览器访问 WebUI 的行为。
- 加载窗口必须先于端口清理和 Python 后端启动出现；端口清理失败要写启动日志并显示在加载页，不修改 Windows 控制台 code page。
- WebUI 更新器只处理源码 Git 通道：固定 `fetch origin main`、比较 `HEAD` 和 `origin/main` 的 ahead/behind，只有当前检出分支可快进到 `origin/main` 时才执行 `pull --ff-only origin main`。
- 更新器拒绝 detached HEAD、非 Git 工作区和脏工作区；Git stderr、启动失败和 timeout 要原样进入 `last_error`。
- 更新器不安装依赖。`requirements.txt`、`frontend/electron/package*.json` 等依赖变更后，用户再运行 `scripts\install.bat`。

## 已移除产品面

当前主线不包含这些面：

- 安装器、wheelhouse、发布包验收流程。两个 import wheel 是开发产物，见
  [两个可安装 wheel](operations/library-packages.md)。
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
