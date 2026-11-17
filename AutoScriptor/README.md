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
- `requirements.txt` 与 `pyproject.toml` 的 `[project].dependencies` 是同一份内容，`test/framework/test_framework_public_api.py` 会校验两者一致。

## 快速开始

装完之后不拿源码也能写脚本。下面这份文件放哪都能跑：

```python
import os
from pathlib import Path

# 配置、日志都落在这里；不设的话会落到 site-packages 边上。
os.environ.setdefault("AUTOSCRIPTOR_DATA_DIR", str(Path(__file__).resolve().parent / "runtime"))

from AutoScriptor import *

init()                                     # 连接模拟器；进入游戏需 launch_app=True
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

切换实例直接传 `init(emulator_index=0)`，不需要修改 `cfg`。默认推导的 ADB 端口随编号变化，手填地址保留；也可显式传 `adb_addr="127.0.0.1:16384"`。这些参数只绑定本次会话，不保存为全局配置，后续 ADB/Manager/IPC 控制使用同一选择。

初始化会核对 MuMuManager 实际实例/地址、ADB 启动状态和一帧 IPC 截图，不发送测试点击；参数冲突或无法验证会明确报错并停止，不自动选择其他在线实例。当前混合控制仅支持本机 `127.0.0.1` / `localhost`、实例 0..31 和 NemuIpc 可映射端口；任意远端 IP/自定义端口并不因可传参就获得支持。成功日志会列出实例名称、地址和截图尺寸，但不保证目标页面或 OCR 区域正确。

## 公共 API

`from AutoScriptor import *` 暴露下面全部名字（等同于 `AutoScriptor.__all__`，由 `test/framework/test_framework_public_api.py` 对着本文校核，两边不允许漂移）：

| 类别 | 名称 |
| --- | --- |
| 脚本 API 版本（独立于软件版本） | `API_VERSION`、`get_api_version` |
| 目标 | `B`、`I`、`T`、`Box`、`box_cell_in_grid`、`Target`、`ui` |
| 操作 | `click`、`seq_click`、`click_all`、`swipe`、`swipe_precise`、`input`、`key_event`、`sleep` |
| 定位 | `locate`、`locate_dyn`、`match`、`ui_T`、`ui_F`、`ui_idx`、`wait_for_appear`、`wait_for_disappear`、`wait_for_signal` |
| 结果处理 | `first`、`simple`、`full`、`count` |
| 识别 | `extract_info`、`get_colors`、`coloris` |
| 文字后处理 | `pretext`、`posttext`、`prenum`、`postnum` |
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

- `from AutoScriptor import get_api_version` 可只读查询脚本 API 版本，不加载 OCR、配置或设备。WebUI「API 文档」提供分类教程、源码签名和版本记录；[维护约定](../docs/AutoScriptor/reference/API.md)。
- `locate()` 的三种形态：单个 `Target` 查一个；`tuple[Target, ...]` 是 **OR**（任一命中即成功）；`list[Target]` 是 **AND**（全部命中才算）。`match()` 在同样语义上返回带 `box`/`index`/`path` 的 dict。
- `locate_dyn(target, min_area, *, interval=0.2, threshold=20, timeout=5)` 接收单目标或列表，`T/I` 及带颜色的 `B` 先定位全部框，再统一与固定第 0 帧作差。`min_area` 是边长或 `(宽, 高)`，8 连通块的宽高须分别达到对应最小边长减 5；首个命中帧有几个返回几个，始终返回 `list[Box]`，不要求每个区域都变化。定位与采样共用超时，未命中抛 `TimeoutError`；变化框不等于对象框或可领取状态，断开的动效不会自动合并。
- `click(..., if_exist=True)` 找不到目标返回 `False`，不抛错；`click_all(target)` 点一帧内该目标的**全部**命中框并返回数量；`click(..., repeat=N)` 是反复点同一个框。
- `seq_click([T("入口"), T("确认")])` 按顺序点击，每项点击到下一项出现，外层 `until` 只用于最后一项；空列表返回 `True`。参数沿用 `click`，但 `timeout` 默认 **每项 10 秒**，不是整条序列共用。衔接检测得到的 Box 直接交给下一次点击，只有 `assure_stable=True` 时额外检测稳定性；重试仍重新定位，不持续点击旧框。无颜色条件的 `B(...)` 自身视为已存在，`ui_T(B(...))` 恒为 `True`，不表示页面已切换。
- `sleep()` 是可取消等待，任务里不要用 `time.sleep()`。
- `extract_info(B(...), post_process=prenum)` 可直接提取前缀整数；`postnum` 提取后缀整数，`pretext/posttext` 提取首尾连续非数字文本。四个函数先 `strip()` 再做首尾锚定正则，数字转 `int`（含 0）；无匹配抛 `ValueError`，由提取流程重试，耗尽返回 `None`，不补 0。它们也可直接调用，无需设备初始化。
- `click()` 返回只表示输入事件已发送，**不表示画面已更新**；要紧跟着读取数据时，先等可观察状态变化。
- **`mixctrl` / `mumu` 是运行态对象，别存星号导入的快照。** `from AutoScriptor import *` 在导入时就把这两个名字绑成了当时的值（通常是 `None`），`init()` 之后那个名字不会变。要拿当前设备控制，用 `import AutoScriptor.core.api as core_api; core_api.mixctrl.screenshot()`，或 `from AutoScriptor.core.runtime_context import runtime_ctx; runtime_ctx.mixctrl`。任务脚本不受影响：它们是在设备会话建立之后才导入的。

## ascli 流程命令

安装后的入口是 `ascli`；源码可直接用 `scripts\ascli.bat` 或 `python -m AutoScriptor.cli`。连接已有 WebUI 后端，不在每条命令里初始化 OCR/设备。

```powershell
ascli help click
ascli check flow.as
ascli transform flow.as -o flow.py
ascli run flow.as --timeout 300
ascli status RUN_ID
ascli artifacts RUN_ID
```

`.as` 每行一个指令，支持 `-B/-T/-I`、`--until`、`--next`、固定截图引用、ADB、录屏及多指操作。整段预校验、整段占用、失败即停；默认保存录像和错误证据。`--until` 会重复点击，单次点击后等待须写两行。生成 Python 保持目标内联、一个指令一行，不自动初始化。

```python
from AutoScriptor.cli import AscliClient, AutomationService, parse_script, transform_script

code = transform_script('click -B 332 33 22 44 --until -T "完成" --timeout 20')
```

`AscliClient.run(source)` 一次提交并等待；`submit/get_run/stop` 支持异步管理。宿主可以实例化 `AutomationService`，注入已有执行锁和取消钩子；包内不 import 后端或游戏层。完整语法和安全边界见 [ascli](../docs/AutoScriptor/reference/ascli.md)。设备动作需平台凭据解锁；单步完成不等于完整流程验收。

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
