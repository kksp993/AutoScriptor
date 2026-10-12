# AutoScriptor

面向安卓模拟器的 Python 自动化**框架层**：设备控制、屏幕识别、任务脚本 API，以及 Windows 主机键鼠控制。

这个包可以独立安装、独立运行，不依赖本仓库的其它目录：

```text
AutoScriptor/        框架层（本包）
ZmxyOL/ tasks/       游戏层：具体游戏业务与任务脚本，另装 zmxyol
orchestrator/ backend/ frontend/   编排、WebUI 与桌面壳，只从源码树运行，不进任何 wheel
```

框架层**不 import 游戏层**——游戏业务通过注入契约接进来（账号后端、包名解析、资源根、归档上下文）。

## 安装

```powershell
# 1) 装本体（wheel 里已经声明了下面的运行时依赖）
uv pip install autoscriptor-<版本>-py3-none-any.whl

# 2) OCR 运行时二选一，与 data/config.json -> ocr.use_gpu 保持一致
uv pip install paddlepaddle==3.2.0 mkl>=2023.0.0   # CPU
uv pip install paddlepaddle-gpu==3.2.2             # GPU（官方 CUDA 12.9 源）

# 3) 从源码装时可以照 requirements.txt
pip install -r requirements.txt
```

- Python `>=3.10,<3.11`。
- `paddlepaddle` 与 `paddlepaddle-gpu` 互斥，**不能同时存在**；`use_gpu=true` 但装了 CPU 变体时 OCR 会明确报错，不会静默降级。
- `requirements.txt` 与 `pyproject.toml` 的 `[project].dependencies` 是同一份内容，`test/test_framework_public_api.py` 会校验两者一致。

## 快速开始

装完之后不拿源码也能写脚本。下面这份文件放哪都能跑：

```python
import os
from pathlib import Path

# 配置、日志都落在这里；不设的话会落到 site-packages 边上。
os.environ.setdefault("AUTOSCRIPTOR_DATA_DIR", str(Path(__file__).resolve().parent / "runtime"))

from AutoScriptor import *

init()                                     # 连模拟器、起 OCR、进入配置里的游戏
print("分辨率:", getFrameSize())

click(T("确定"), if_exist=True)
swipe(B(600, 500, 100, 100), B(600, 200, 100, 100))
sleep(0.5)
```

只操作别的 App（例如 4399 游戏盒）时不要先拉起配置里的游戏：

```python
init(launch_app=False)
launch_app("com.m4399.gamecenter")
if ui_T((T("首页"), T("找游戏"), T("福利"))):
    click(T("我的"))
close_app("com.m4399.gamecenter")
go_home()
```

`init()` 之前的导入都是懒的：`import AutoScriptor` 不会初始化 OCR、UI Map、MuMu、NemuIpc 或 `mixctrl/mumu`。

## 公共 API

`from AutoScriptor import *` 暴露下面全部名字（等同于 `AutoScriptor.__all__`，由 `test/test_framework_public_api.py` 对着本文校核，两边不允许漂移）：

| 类别 | 名称 |
| --- | --- |
| 目标 | `B`、`I`、`T`、`Box`、`box_cell_in_grid`、`Target`、`ui` |
| 操作 | `click`、`click_all`、`swipe`、`swipe_precise`、`input`、`key_event`、`sleep` |
| 定位 | `locate`、`match`、`ui_T`、`ui_F`、`ui_idx`、`wait_for_appear`、`wait_for_disappear`、`wait_for_signal` |
| 结果处理 | `first`、`simple`、`full`、`count` |
| 识别 | `extract_info`、`get_colors`、`coloris` |
| 实时与多指 | `screenshot_region`、`finger_down`、`finger_move`、`finger_up`、`multi_finger_down`、`release_all_fingers`、`replay` |
| 输入通道 | `switch_base`、`ctrl_nemu`、`ctrl_mumu` |
| 初始化与 App | `init`、`launch_app`、`close_app`、`go_home`、`ensure_app_running`、`ensure_all_environment_ready` |
| 设备对象 | `mixctrl`、`mumu` |
| 帧尺寸 | `setFrameSize`、`getFrameSize`、`MUMU_SIZE_1280_720`、`MUMU_SIZE_720_1280` |
| 配置与日志 | `cfg`、`logger`、`log_flush` |
| 网格 | `make_box_grid`、`indexof` |
| 后台监控 | `bg`、`BG_SIGNALS`、`BgSignals` |
| 错误 | `RequestHumanTakeover`、`NemuIpcIncompatible`、`NemuIpcError`、`JobError`、`JobTimeout`、`_JobKill`、`PackageNotInstalled`、`ImageTruncated`、`ImageNotSupported`、`TaskRequireReTry` |

几处容易踩的语义：

- `locate()` 的三种形态：单个 `Target` 查一个；`tuple[Target, ...]` 是 **OR**（任一命中即成功）；`list[Target]` 是 **AND**（全部命中才算）。`match()` 在同样语义上返回带 `box`/`index`/`path` 的 dict。
- `click(..., if_exist=True)` 找不到目标返回 `False`，不抛错；`click_all(target)` 点一帧内该目标的**全部**命中框并返回数量；`click(..., repeat=N)` 是反复点同一个框。
- `sleep()` 是可取消等待，任务里不要用 `time.sleep()`。
- `click()` 返回只表示输入事件已发送，**不表示画面已更新**；要紧跟着读取数据时，先等可观察状态变化。
- **`mixctrl` / `mumu` 是运行态对象，别存星号导入的快照。** `from AutoScriptor import *` 在导入时就把这两个名字绑成了当时的值（通常是 `None`），`init()` 之后那个名字不会变。要拿当前设备控制，用 `import AutoScriptor.core.api as core_api; core_api.mixctrl.screenshot()`，或 `from AutoScriptor.core.runtime_context import runtime_ctx; runtime_ctx.mixctrl`。任务脚本不受影响：它们是在设备会话建立之后才导入的。

## 主机桌面控制（Windows）

控制主机上的普通 Windows 程序（浏览器、PC 客户端），与模拟器通道互不干扰：

```python
from AutoScriptor.control.DesktopControl import get_desktop
from AutoScriptor import T

desktop = get_desktop()                      # 首次调用会声明进程 DPI 感知
window = desktop.find_window(process_name="msedge.exe")   # 按进程名/标题找窗口
desktop.activate_window(window)              # 提到前台
desktop.hotkey("ctrl", "l")
desktop.type_text("http://127.0.0.1:5000")   # Unicode 注入，中文与网址都可用
desktop.press("enter")
desktop.click_text(T("终止执行"), box=window.rect)          # 在窗口内识别，再点它的中心
```

坐标合同：**物理像素，原点在虚拟桌面左上角**（多显示器原点是负数）。截图、`Box`、点击坐标共用这一套，所以 `desktop.screenshot()` 上量到的像素可以直接当点击坐标。键鼠注入走系统 `SendInput`，被更高权限窗口拦下时抛 `InputInjectionBlocked`，不会把没生效的点击当成成功。

这一块**刻意不放进 `from AutoScriptor import *`**：上面那张公共 API 表是「安卓设备 + 游戏」
域的任务脚本面，坐标是 1280x720 游戏帧；主机桌面控制是另一个能力域，坐标是整块虚拟桌面。
两者混在一个星号导入里，最容易犯的错是拿游戏帧的 `T(...)` 区域去套主机屏幕。所以它按子模块
路径发布（`AutoScriptor.control.DesktopControl`），要用就显式导入，见上面的 `get_desktop()`。

## 坐标与分辨率合同

- 模拟器侧：内置截图、模板、`Box` 和点击坐标统一是 **1280x720 横屏绝对像素**，运行时不缩放。
- 要操作竖屏等其它原生尺寸：单区域用 `Box(...).margin(frame_size=(720, 1280))`，整份脚本用 `setFrameSize(MUMU_SIZE_720_1280)`。
- `MixControl.screenshot()` 遇到尺寸不符会打节流 warning 并原样返回帧，不改尺寸也不终止会话。

## 数据目录

`AUTOSCRIPTOR_DATA_DIR` 决定运行数据的根（默认是包所在位置旁边）：

```text
<数据根>/config.json      全局配置
<数据根>/accounts/        账号与角色（由游戏层注入的账号后端管理）
<数据根>/logs/            日志、调试截图、错误归档
```

没有 `config.json` 时用内置的一份最小默认值启动（`app` / `ocr` / `emulator` 三段，模拟器
路径为空，用 `AutoScriptor.utils.mumu_discovery.discover_mumu_setup()` 自动填）。

日志写在**数据根**下的 `logs/log/[yymmdd_HHMMSS].log`，不跟进程的工作目录走——安装位里
进程 cwd 是用户自己的工作目录，把日志写那儿既找不到也和本节说的位置对不上。

## 边界

框架层提供「写脚本」的能力，不提供「跑整套 WebUI」的能力：

- 不含游戏业务、内置任务、任务编排、账号加密与 WebUI。这些在 `zmxyol` 与本仓库的 `orchestrator/`、`backend/`、`frontend/`。
- 不 import 游戏层；游戏层单向依赖本包。
- 只含 Python 代码与随包文档，没有二进制与素材；UI 模板图片属于游戏层的 `ui_map` 资产。
