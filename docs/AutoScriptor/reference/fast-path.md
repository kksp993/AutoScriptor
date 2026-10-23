# Nemu IPC 快速路径与实时闭环

本文记录 MuMu 控制链路的当前事实：输入默认走 Nemu IPC、ROI 快速截图、多指 API
和「条子」类实时闭环的使用方式。本机实测数据来自 2026-09-29 的真机验证
（MuMu 5.30.1.3586，1280x720，证据与脚本见 `logs/fastpath_online_20260929/`）。

## 通道与默认路由

- `MixControl` 默认 `mode="nemu"`：点击、滑动、长按、文本输入全部走 MuMu
  `external_renderer_ipc.dll`（进程内调用，无 ADB 子进程）。
- 截图恒走 Nemu IPC，与输入模式无关。
- Nemu 输入失败（`NemuIpcError` / `RequestHumanTakeover`）时单次运行自动回退
  ADB，并记录一条 error 日志；后续输入直接走 ADB，不再反复尝试。
  `switch_to_nemu()` 会复位回退标记，重新启用快速路径。
- 本机实测输入延迟：finger down+up 往返 p50 **0.23ms**；对照 ADB `input tap`
  约 45ms，截图 `adb screencap` 数百 ms。慢的是通道选择，不是设备本身。

### 实测数据（本机 2026-09-29）

| 路径 | 延迟（p50） | 备注 |
| --- | --- | --- |
| 全帧截图（复用缓冲 + 全帧转换） | 3.07 ms | `mixctrl.screenshot()` |
| ROI 截图（复用缓冲 + 区域转换） | 2.35 ms | `screenshot_region(box)` |
| finger down+up 往返 | 0.23 ms | 编号手指 API |
| 30Hz 闭环（ROI 截图 + 简单检测） | 单次迭代 3.2 ms | 有效 29.3Hz，含调度 sleep |
| ADB `input tap`（对照） | ≈45 ms | 仅兜底 |
| ADB `screencap`（对照） | ≈560 ms | 实时场景禁用 |

## 截图 API

- `mixctrl.screenshot()`：全帧 RGB（1280x720 合同）。沿用 `MixControl` 的
  分辨率 warning 与调试截图节流。
- `screenshot_region(box)`（公共 API 同名）：只转换给定屏幕区域，返回该区域
  RGB 图像。`box` 为 `(x, y, width, height)` 或 `Box`，与点击同一坐标约定
  （左上原点）。越界抛 `ValueError`。

截图缓冲在 `NemuIpcImpl` 内复用，分辨率变化时自动重建；截图之间在实例级
`io_lock` 上串行（复用缓冲不允许并发写），输入不参与该锁。

## 多指 API

公共 API（`from AutoScriptor import *` 可用）：

```python
finger_down(finger_id, x, y)   # 按下 1..10 号手指
finger_move(finger_id, x, y)   # 移动：IPC 没有独立 move，重复 down 即移动
finger_up(finger_id)           # 抬起
multi_finger_down([(1, x1, y1), (2, x2, y2)])  # 多指同按（无中间 up 事件）
release_all_fingers()          # 兜底释放 1..10 号（不会抛错）
```

边界与注意：

- 编号手指（1..10）是 IPC 原生的多点触控通道；`click()` / `long_click()`
  走的是另一条单触点路径。两者可并存，但同一操作序列内不要交叉使用
  （单触点 `touch_up` 会释放它自己的接触点，不会释放编号手指）。
- 实时步骤必须在 `finally` 里 `release_all_fingers()`，防止中止后手指保持按下。
- 手指按下/抬起是没有中间节流的边沿事件；不要给相邻事件叠加人为 sleep 凑时序。

## 录制回放（replay）

`replay(events, ...)` 是 `finger_*` 之上的数据驱动入口，把 MuMu 操作录制
（`.mmor`）转成的事件流按原始时序回放，一条扁平事件流同时表达多指与时序。

```python
EVENTS = [(0, "down", 1, 0.50, 0.25), (0, "down", 2, 0.75, 0.25),
          (60, "move", 1, 0.50, 0.50), (120, "up", 1, 0.0, 0.0),
          (120, "up", 2, 0.0, 0.0)]
replay(EVENTS, speed=1.5, recording_size=(1080, 1920))
```

- 坐标是 0~1 归一化值，回放时按 `frame_size`（默认 `getFrameSize()`）换算，
  因此录制与运行分辨率不同也能对齐；方向不一致时**抛错**而非静默按轴缩放。
- 计时用绝对时间锚点，长录制不漂移；`start_ms`/`end_ms` 可截窗口分段调试。
- `finger_id` 越界（1..10 之外）**显式抛错**：`.mmor` 的槽位号实测出现 19/20，
  与 `finger_id` 不是同一编号空间，必须在转换侧重映射，不能夹取或取模。
- 中止时只释放本次回放按住的手指，不用 `release_all_fingers()`，避免误伤
  任务在回放之外异步按住的手指。
- 核心不认识 `.mmor`：解析与槽位重映射在外部 `mumuinner` 项目的 `mmor_to_fast_replay.py` 里
  完成，导出的 timeline JSON（`t_ms`/`op`/`finger`/`x`/`y`）可直接喂给 `replay`。

契约由 `test/runtime/test_replay_events.py` 固化（21 项：坐标换算、同刻多指保序、
编号越界、跨方向、时间窗、取消清理、清理失败不掩盖原始异常、公共导出）。

## 实时闭环（「条子」类）

目标形态：30~60Hz 的 截图 → ROI 检测 → 决策 → 按住/松开 循环。骨架：

```python
screenshot_region(bar_box)                 # ~2.4ms
#  检测优先颜色阈值/扫描线，不用 OCR（全帧 OCR 几十 ms 起）
#  估计速度并预测「当前 + 延迟」后的位置，再决定按住或松开
finger_down(1, x, y) / finger_up(1)        # 只在状态翻转时发边沿
```

规则：

- 检测只在 ROI 内做；条子类看 1~3 条扫描线即可。
- 输入用边沿触发（状态翻转时才发），不要每帧重复发 down。
- 步骤退出、检测丢失超时、收到取消信号时都必须松开手指。
- Windows 默认计时器精度 15.6ms 会破坏 60Hz 节拍；需要时开
  `timeBeginPeriod(1)` 或用 sleep+短自旋混合。
- 采样频率不必超过模拟器渲染帧率（本机 60fps 上限，有效新帧约 56fps）。

## 风险与边界

- MuMu 版本差异：MAA 对 MuMuManager < 6.3.2.0 禁用了 IPC 输入；本机
  5.30.1.3586 实测输入、多指、并发全部正常。升级 MuMu 后应回归本页验证脚本。
- `app_keptlive`（后台保活）开启时 display id 语义变化，现有代码在检测到
  keep-alive 时会要求人工处理，保持即可。
- 并发语义已由 `test/device/test_nemu_ipc_concurrency.py` 固化：输入与截图并发、
  截图之间串行。

## 验证入口

```powershell
$py = ".venv\Scripts\python.exe"
& $py -X utf8 logs\fastpath_online_20260929\verify_fast_path_live.py   # 通道延迟与闭环
& $py -X utf8 logs\fastpath_online_20260929\verify_init_live.py        # init 全链路
& $py -X utf8 -m unittest test.device.test_nemu_ipc_fast_path test.device.test_nemu_ipc_concurrency
```
