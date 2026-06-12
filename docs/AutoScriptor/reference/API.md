# AutoScriptor API 与运行入口速查

本文只记录当前代码事实。更细的生命周期、调度、WebUI 和发行说明见本目录其他功能域文档。

## 入口

| 场景 | 入口 |
|------|------|
| 桌面开发运行 | `cd webapp; npm start` |
| 后端 WebUI | `.venv\Scripts\python.exe -X utf8 gui.py` 或 `services/webui/server.py` |
| CLI | `.venv\Scripts\python.exe -X utf8 services/main_cli/run.py` |
| 发行构建 | `.venv-nuitka\Scripts\python.exe scripts\build_release.py -j N` |

导入 `AutoScriptor` 本身是懒加载：不会初始化 OCR、UI Map、MuMu、NemuIpc 或 `mixctrl/mumu`。真正执行 `click()`、`locate()`、任务运行或显式设备接口时才需要设备会话。

## 数据目录

| 目录/文件 | 说明 |
|-----------|------|
| `config.json` / `dataRoot/config.json` | 全局配置：源码模式默认在仓库根；发行/Electron 模式由 `AUTOSCRIPTOR_DATA_DIR` 指向 `install.json.dataRoot` |
| `dataRoot/accounts/*.json` | 账号、角色、任务树、任务状态、加密凭据；真实账号文件不提交 |
| `dataRoot/custom_task/` | 用户自定义任务脚本 |
| `dataRoot/battle_character/` | 当前唯一生效的运行态职业脚本目录 |
| `ZmxyOL/assets/config/ui_map.csv` | UI 名称到图片/文本/坐标的映射 |
| `ZmxyOL/assets/pic/` | 模板图片资源 |
| `logs/` / `dataRoot/logs/` | `get_logs_root()` 返回的运行日志、调试截图、错误归档目录；源码模式通常是仓库 `logs/`，发行模式通常是 `install.json.dataRoot/logs/` |

路径统一通过 `AutoScriptor.utils.paths` 解析。不要在仓库根目录新建 `accounts/`、`custom_task/` 或 `battle_character/`。

## 公共导入

任务脚本通常可以写：

```python
from AutoScriptor import *
```

常用导出：

| 类型 | 名称 |
|------|------|
| 目标 | `B`、`I`、`T`、`V`、`Box`、`Target`、`ui` |
| 操作 | `click`、`swipe`、`input`、`key_event`、`sleep` |
| 定位 | `locate`、`ui_T`、`ui_F`、`wait_for_appear`、`wait_for_disappear` |
| OCR/颜色 | `extract_info`、`get_colors` |
| 后台 | `bg`、`BG_SIGNALS` |
| 配置/状态 | `cfg`、`get_task_status`、`set_task_status` |
| 错误 | `TaskRequireReTry`、`RequestHumanTakeover` |

`clear_task_status` 目前不是 `AutoScriptor.__all__` 公共导出；需要清理状态时从 `AutoScriptor.utils.task_state` 导入。

## 目标语义

```python
from AutoScriptor import B, I, T, V, Box

btn = I("确认")                         # 图片目标，来自 ui_map / pic
txt = T("胜利", box=B(300, 100, 400, 80)) # OCR 文本目标
box = B(100, 200, 120, 60)              # 直接坐标区域，参数为 x, y, w, h
vlm = V("红色确认按钮", box=box)         # VLM 目标，需启用 llm.use_agent
```

`locate()` 的组合语义：

| 形态 | 含义 |
|------|------|
| `Target` | 查找单个目标 |
| `tuple[Target, ...]` | OR：任意目标命中即成功 |
| `list[Target]` | AND：全部目标命中才成功 |

混合 `I()` 与 `T()` 的 tuple 会优先尝试图片，图片命中时跳过 OCR，降低弹窗类 OR 查询延迟。

## 操作 API

```python
click(T("确定"), timeout=10)
click((T("知道了"), T("取消")), if_exist=True)
click(B(100, 200, 40, 40), repeat=2, interval=0.2)
swipe(B(600, 600, 1, 1), B(600, 200, 1, 1), duration_s=1)
input("hello", T("请输入"))
key_event(4)
sleep(1)
```

规则：

- `sleep()` 是可取消等待；任务脚本不要直接 `time.sleep()`。
- `click(..., if_exist=True)` 找不到目标时返回 `False`，不会抛错。
- `click(..., until=callable)` 会循环点击直到条件满足或超时。
- `offset` / `resize` 和 `Box + {"offset": ..., "resize": ...}` 使用同一坐标语义。
- `click()`、`locate()` 超时较长时会保存失败截图到调试截图目录。

## OCR、数字与颜色

```python
value = extract_info(T("数量", box=B(100, 100, 80, 30)))
digits = extract_info(B(100, 100, 80, 30), digit_only=True)
colors = get_colors((B(10, 10, 20, 20), B(40, 10, 20, 20)))
```

`extract_info(..., screenshot_frame=frame)` 会固定使用同一帧，适合在线截图测试、Editor 导入图和批量识别，避免 UI 漂移。OCR 层应保留识别语义：空/不可读返回 `None` 或空字符串，业务层再决定是否转成数量 `0` 或 `1`。

## 配置与任务状态

`cfg` 是当前账号/角色扁平运行视图：

- 全局字段来自 `config.json`。
- 当前账号与角色来自 `data/accounts/*.json`。
- 当前角色的 `tasks`、`status` 会被展开到 `cfg["tasks"]`、`cfg["status"]`。
- 保存通过 `AutoScriptor.utils.app_config` 原子写 JSON。

任务内状态：

```python
set_task_status("progress", "5/6")
progress = get_task_status("progress")
```

`progress` 是可观测业务进度，不等同于函数返回。未完成进度会被执行层转为 retry；超过 retry 后进入人工接管冷却。

## 任务入口

内置任务放在 `ZmxyOL/task/`，自定义任务放在 `data/custom_task/`。

```python
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *

@register_task(default_offset_hours=10, description="示例任务")
def task(count: int = 1):
    for _ in range(count):
        click(T("开始"), timeout=10)
```

自定义任务必须提供中文路径：

```python
@register_task(path_cn="自定义任务/示例/hello")
def task():
    ...
```

运行时元数据保存在 `TaskRegistry`，用户配置保存在 `cfg["tasks"]`。脚本不要依赖 `fn/order/param_meta/_due` 等字段被持久化。

## WebUI 入口

WebUI 当前是 FastAPI + Vue 静态组件：

- 日志走 WebSocket `/ws/logs`。
- 主状态轮询为 `/api/runtime/snapshot`。
- 配置快照为 `/api/refresh`。
- 设备诊断为 `/api/device/diagnostics`，默认不做截图探测。
- Editor、Canvas、News 使用独立 router：`/api/editor/*`、`/api/canvas/*`、`/api/news/*`。

新增或修改接口前先看 [webui/api-contract.md](../webui/api-contract.md)。
