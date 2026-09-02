# AutoScriptor API 与运行入口速查

本文只记录 `src` 分支当前保留的源码运行事实。更细的生命周期、调度、WebUI 和任务说明见本目录其他功能文档。

## 入口

| 场景 | 入口 |
|------|------|
| 安装源码依赖 | `scripts\install.bat` |
| 源码 Electron 桌面壳 | `scripts\run.bat electron` 或根目录 `start.bat` |
| 后端 WebUI | `scripts\run.bat webui`、根目录 `webui.bat` 或 `.venv\Scripts\python.exe -X utf8 services\webui\gui.py` |
| 更新源码 | `scripts\update.bat` |
| WebUI 模块直跑 | `.venv\Scripts\python.exe -X utf8 services\webui\server.py` |

导入 `AutoScriptor` 本身是懒加载：不会初始化 OCR、UI Map、MuMu、NemuIpc 或 `mixctrl/mumu`。真正执行 `click()`、`locate()`、任务运行或显式设备接口时才需要设备会话。

## 屏幕与坐标合同

AutoScriptor 的内置游戏截图、模板、`Box` 和点击坐标统一使用 **1280x720 横屏绝对像素**。`Box(x, y, width, height)` 表示左上角坐标与宽高；运行时不会自动缩放截图、模板或坐标。

Editor 遥控和自定义脚本可以操作其他应用的原生截图尺寸，例如 720x1280 竖屏。纯坐标 `click(B(x, y))` 直接使用该原生坐标；需要扩大 OCR/模板区域时必须写明截图尺寸，例如 `Box(...).margin(frame_size=(720, 1280))`。Editor 在非 1280x720 截图上生成 T/I 代码时会自动携带该参数，左侧执行栏和保存后的脚本使用同一代码语义。这里不做坐标换算；执行时应用方向必须与录制时一致。

`MixControl.screenshot()` 会检查实际帧尺寸。尺寸不符时会输出带实际值和期望值的中文 warning，同一异常尺寸 60 秒内节流；原始帧会原样返回，不抛异常、不改尺寸。运行内置游戏任务时应修正 MuMu 分辨率；明确操作竖屏外部应用时则保留原生尺寸，并为识别区域显式声明 `frame_size`。

`locate()`、`match()`、`click()`、`extract_info()` 的参数和返回合同不因诊断功能改变。内部 `RecognitionResult` 只在当前线程保留最近 32 条摘要，供错误归档和维护排查使用；它不保存截图数组，也不是任务脚本公共 API。

离线维护入口：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\audit_ui_assets.py
.\.venv\Scripts\python.exe -X utf8 scripts\run_recognition_baselines.py
```

素材审计只读检查 `ui_map.csv`、模板引用和孤立图片；固定帧基准要求样本严格为 1280x720，报告都写入 `logs/`。空基准清单会报告 `status=empty` 并以退出码 `2` 结束，不视为回归通过。

## 数据目录

| 目录/文件　　　　　　　　　　　　 | 说明　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| -----------------------------------| ------------------------------------------------------------|
| `data/config.json`　　　　　　　　| 源码运行的全局配置　　　　　　　　　　　　　　　　　　　　 |
| `data/accounts/*.json`　　　　　　| 账号、角色、任务树、任务状态、加密凭据；真实账号文件不提交 |
| `data/custom_task/`　　　　　　　 | 用户自定义任务脚本　　　　　　　　　　　　　　　　　　　　 |
| `data/battle_character/`　　　　　| 当前有效的运行态职业脚本目录　　　　　　　　　　　　　　　 |
| `logs/zmxy_redeem_codes.json`　　 | 4399 兑换码采集器生成的运行态缓存；不提交到仓库　　　　　　|
| `ZmxyOL/assets/config/ui_map.csv` | UI 名称到图片、文本、坐标的映射　　　　　　　　　　　　　　|
| `ZmxyOL/assets/pic/`　　　　　　　| 模板图片资源　　　　　　　　　　　　　　　　　　　　　　　 |
| `logs/`　　　　　　　　　　　　　 | `get_logs_root()` 返回的运行日志、调试截图、错误归档目录　 |

路径统一通过 `AutoScriptor.utils.paths` 解析。不要在仓库根目录新增散落的 `accounts/`、`custom_task/` 或 `battle_character/`。

## 公共导入

任务脚本通常可以写：

```python
from AutoScriptor import *
```

常用导出：

| 类型　　　　　| 名称　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| ---------------| ----------------------------------------------------------------------------|
| 目标　　　　　| `B`、`I`、`T`、`Box`、`Target`、`ui`　　　　　　　　　　　　　　　　　　　 |
| 操作　　　　　| `click`、`swipe`、`input`、`key_event`、`sleep`　　　　　　　　　　　　　　|
| 定位/区域识别 | `locate`、`match`、`ui_T`、`ui_F`、`wait_for_appear`、`wait_for_disappear` |
| OCR/提取颜色　| `extract_info`、`get_colors`、`coloris`　　　　　　　　　　　　　　　　　　|
| 后台　　　　　| `bg`、`BG_SIGNALS`　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 配置/状态　　 | `cfg`、`get_task_status`、`set_task_status`　　　　　　　　　　　　　　　　|
| 错误　　　　　| `TaskRequireReTry`、`RequestHumanTakeover`　　　　　　　　　　　　　　　　 |

`clear_task_status` 目前不是 `AutoScriptor.__all__` 公共导出；需要清理状态时从 `AutoScriptor.utils.task_state` 导入。

## 定位

```python
from AutoScriptor import B, I, T, Box

btn = I("确认")                         # 图片目标，来自 ui_map / pic
txt = T("胜利", box=B(300, 100, 400, 80)) # OCR 文本目标
box = B(100, 200, 120, 60)              # 直接坐标区域，参数为 x, y, w, h
```

`locate()` 的组合语义：

| 形态 | 含义 |
|------|------|
| `Target` | 查找单个目标 |
| `tuple[Target, ...]` | OR：任意目标命中即成功 |
| `list[Target]` | AND：全部目标命中才成功 |

混合 `I()` 与 `T()` 的 tuple 会优先尝试图片，图片命中时跳过 OCR，降低弹窗类 OR 查询延迟。

### 区域识别

`match()` 是定位里的结构化区域识别入口，沿用同一套 `Target` / `tuple` / `list` 语义：

```python
hit = match((T("确定"), T("取消")), timeout=2)
if hit:
    click(hit["box"])
```

返回值为 `dict | None`。常用字段：

| 字段 | 含义 |
|------|------|
| `all` | 本次是否按 list 的 AND 语义匹配 |
| `index` | 扁平目标列表中的首个命中下标 |
| `path` | 目标结构中的嵌套位置，不是文件路径，例如 `(1, 0)` 表示第 1 组里的第 0 个目标 |
| `target` | 首个命中的目标对象 |
| `box` | 首个命中的 `Box` |
| `boxes` | 完整定位结果矩阵 |

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
- `click(..., until=callable)` 会循环点击直到条件满足或超时；未传 `interval` 时循环间隔默认 0.5 秒，普通 `click()` 默认仍为 0 秒。
- `offset` / `resize` 和 `Box + {"offset": ..., "resize": ...}` 使用同一坐标语义。
- `click()`、`locate()` 超时较长时会保存失败截图到调试截图目录。

## OCR、数字与提取颜色

### OCR 与数字

```python
text_value = extract_info(B(100, 100, 80, 30), mode="text")
digits = extract_info(B(100, 100, 80, 30), mode="digital_only")
image_keys = extract_info(box_grid, mode="img")
values = extract_info(box_grid, mode="both")
```

`extract_info` 的 `mode` 只接受 `digital_only`、`text`、`img`、`both`：分别表示仅数字、仅 OCR 文本、仅匹配 `ui_map` 已登记图片并返回条目 key，以及逐格优先图片、未命中时再 OCR。单个 Box、Box 列表和二维 Box 网格会保持对应的返回形状；未识别的格子保留 `None` 或空字符串。`post_process` 解析失败会记录为本次识别失败并继续重试，重试耗尽后返回 `None`，不会把原始 OCR 文本当作处理后结果返回。`extract_info(..., screenshot_frame=frame)` 会固定使用同一帧，适合在线截图测试、Editor 导入图和批量识别，避免 UI 漂移。OCR 层应保留识别语义，业务层再决定是否转成数量 `0` 或 `1`。

### 提取颜色

```python
colors = get_colors((B(10, 10, 20, 20), B(40, 10, 20, 20)))
is_green = coloris(B(100, 100, 80, 30), "绿色")
```

`coloris(targets, color, timeout=0, offset=(0, 0), resize=(-1, -1))` 用于直接判断颜色是否匹配：单个目标判断自身颜色，tuple 表示任一目标颜色匹配即可，list 表示全部目标都要匹配。需要读取具体颜色列表时仍使用 `get_colors()`。

## 配置与任务状态

`cfg` 是当前账号/角色扁平运行视图：

- 全局字段来自 `data/config.json`。
- 当前账号与角色来自 `data/accounts/*.json`。
- 当前角色的 `tasks`、`status` 会展开到 `cfg["tasks"]`、`cfg["status"]`。
- 保存通过 `AutoScriptor.utils.app_config` 原子写 JSON。

任务内状态：

```python
set_task_status("progress", "5/6")
progress = get_task_status("progress")
```

`progress` 是可观察业务进度，不等同于函数返回。未完成进度会被执行层转为 retry；超过 retry 后进入人工接管冷却。

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
- Editor、News 使用独立 router：`/api/editor/*`、`/api/news/*`。

新增或修改接口前先看 [webui/api-contract.md](../webui/api-contract.md)。
