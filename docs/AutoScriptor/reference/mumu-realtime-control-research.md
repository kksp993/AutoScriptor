# MuMu 模拟器实时闭环自动化调研：高帧率截图 / 高速多指输入 / 钓鱼类反馈控制

> 调研日期：2026-09-29
> 调研方式：一手源码与官方文档（MAA / MaaFramework / EmulatorExtras / MaaTouch / minitouch / scrcpy / BetterGI）
> + 本机实测（MuMu 5.30.1.3586，`nx_device/12.0`，1280x720，实例 0，Windows 10.0.26200，Python + OpenCV；
> 未进入游戏画面；输入注入仅用于主屏多点触控验证，证据见 `refs/getevent.log` 与 `refs/mt_*.png`）。
> 文中「事实」= 有来源链接或本机可复现实测；「推断」= 由事实给出但未直接验证的判断；「待验证」= 未找到一手证据或需要真机实验。

---

## 0. 结论摘要

**多指输入最终结论（事实级）**：MuMu 官方 `external_renderer_ipc.dll` 原生支持 1~10 指触控，通过
`nemu_input_event_finger_touch_down / nemu_input_event_finger_touch_up` 的 `finger_id`（1..10）区分手指；
官方头文件明确写明「想要多点触控，多次调用这两个 API 模拟即可」。MAA 与 MaaFramework 都已把多指接入
（`contact` 0-based → `finger_id` 1-based），并确认**没有独立的 move 接口：重复 touch_down 即移动**。
本机 5.30.1.3586 的既有 getevent 实验日志也观察到两个 MT slot（二指）与移动、抬起事件，
说明该构建下 finger 接口至少到达内核输入层有效（工作区 `refs/getevent.log`）。

**最优通道组合（推荐）**：截图继续用 NemuIpc（复用缓冲区、免转换/免翻转，实测均值 2.1ms/帧）；
输入用同一 DLL 的 `finger_touch_down/up` 持久按住（“按住/松开”类小游戏其实**不需要**多指，
但需要低延迟边沿），配合独立实时线程闭环。备选回退链：MaaTouch → minitouch → ADB。
不建议用 scrcpy / adb input / uiautomator2 做 20~60Hz 闭环（延迟或工程量不合适）。

**关键延迟数字（本机实测，1280x720，见 §5）**：
裸 `nemu_capture_display`（复用缓冲）均值 **2.15ms**（≈466fps），含分配+色彩转换+翻转完整路径 **4.42ms**；
`adb shell` 往返 **35.2ms/次**；`adb exec-out screencap -p` **545.6ms/帧**；
ROI 内 HSV 阈值+轮廓检测仅 **0.17ms**（全屏同类流水线约 2.2ms）。即「截图通道」而非「检测」才是延迟大头，
而 NemuIpc 把截图延迟压到毫秒级，20~60Hz 闭环在数据通路上没有障碍。

**钓鱼控制算法要点（事实+推断）**：现成参考 BetterGI 用「颜色掩码 + 轮廓矩形 + 位置比较」做
20Hz（50ms 定时器）的 bang-bang 控制：游标在目标区间左侧→按下，进入区间中点→松开；
靠「中点规则」天然形成滞回、靠 `_prevMouseEvent` 状态去抖，无 PID、无卡尔曼。
对「按住升/松开降」系统，推荐 bang-bang + 死区/滞回 + **速度预测补偿**（估计 bar 速度并预测
「当前时刻+动作延迟」后的位置再决策），控制频率 30~60Hz，通常无需 PID/卡尔曼（推断；理论依据见 §3.3）。

**最大不确定性**：本机 MuMu **5.30.1.3586 低于 MAA 触控增强门槛（MuMuManager ≥ 6.3.2.0）**，
MAA 官方口径是「低于该版本 external renderer 输入行为异常，只启用截图」；
虽然本机 getevent 日志显示 finger 事件到达内核层，但**游戏层是否完整接受、坐标是否正确、高频连续切换是否稳定，
仍未在真实游戏内验证（待验证，见 §7）**。其次是 nemu 输入边沿的实测延迟仍缺（工作区已备好可跑的基准脚本
`tools/bench_nemu_ipc.py`，本轮为不触碰游戏未执行注入部分）。

### 0.1 推荐方案矩阵（通道 × 结论）

| 用途 | 首选 | 次选 | 不建议 | 备注 |
| --- | --- | --- | --- | --- |
| 高帧率截图 | MuMu external_renderer_ipc（NemuIpc）| scrcpy 控制协议（仅当 DLL 被版本问题封死时，但代价大）| adb screencap（545.6ms/帧，实测）| 复用缓冲、去分配去翻转可再省 ~2ms |
| 低延迟单指按住/松开 | nemu `finger_touch_down/up`（持久按住，只发边沿）| MaaTouch / minitouch | adb input（MAA 文档明示滑动会「拖飞」）| 钓鱼场景不需要 move 事件 |
| 多指手势 | nemu `finger_*`（1..10 指）| minitouch / MaaTouch（contact 协议）| scrcpy 默认 UI（单指+捏合）| 需自写客户端才能用 scrcpy 任意多指 |
| 后台（保活）操作 | nemu（官方 README 专门为保活补 `nemu_get_display_id`；MAA 文档称支持后台挂机）| ADB 系（与窗口无关）| 窗口消息注入（无证据）| 保活开启后 display id 需按包名获取 |
| 实时反馈控制 | 独立实时线程 + 边沿式输入 + 速度预测 | 定时器 50ms（BetterGI 已证明可行）| 步骤引擎直接跑 60Hz 循环 | 见 §6 架构建议 |

### 0.2 速度梯队表（本机实测 + 官方文档）

| 梯队 | 通道 | 延迟量级 | 来源 |
| --- | --- | --- | --- |
| T0 | nemu 截图（复用缓冲）| 2.1ms/帧（466fps）| 本机实测 |
| T0 | nemu 截图（含分配/cvt/flip）| 4.4ms/帧 | 本机实测 |
| T0? | nemu 输入边沿 | 预计与截图同量级（同 DLL 进程内调用）| 待实测 |
| T1 | scrcpy 镜像（含视频链路）| 35~70ms（官方 README，端到端含显示）| 官方文档 |
| T2 | adb shell 单次往返 | 35.2ms | 本机实测 |
| T3 | adb `screencap` | 545.6ms（≈1.8fps）| 本机实测 |

---

## 1. MuMu 高速通道细节

### 1.1 external_renderer_ipc.dll 导出函数全集（本机 PE 导出表实测）

用工作区 `tools/pe_exports.py` 直接解析本机两个 DLL 副本，导出符号完全一致（共 11 个）：

```
nemu_connect
nemu_disconnect
nemu_get_display_id
nemu_capture_display
nemu_input_text
nemu_input_event_touch_down
nemu_input_event_touch_up
nemu_input_event_key_down
nemu_input_event_key_up
nemu_input_event_finger_touch_down
nemu_input_event_finger_touch_up
```

实测路径（本机 `C:\Program Files\Netease\MuMu`，MuMu 5.30.1.3586）：
`nx_main\sdk\external_renderer_ipc.dll` 与 `nx_device\12.0\shell\sdk\external_renderer_ipc.dll`——
两者导出相同；加载器应同时探测这两个路径（另见 §1.4 已知的四个历史路径）。

各函数签名与语义（以官方头文件为准，链接见 §8）：

| 函数 | 签名要点 | 语义与约束 |
| --- | --- | --- |
| `nemu_connect` | `(const wchar_t* path, int index) -> int` | 安装路径为 UTF-16；`index` 为多开实例号；返回 >0 成功，0 失败 |
| `nemu_disconnect` | `(int handle)` | 断开连接 |
| `nemu_get_display_id` | `(int handle, const char* pkg, int appIndex) -> int` | 取指定包（含分身 `appIndex`）的 display id；**保活开启时才有效**；应用重启后需重新获取；<0 失败，≥0 有效。旧版本 DLL 无此符号（需回退 0） |
| `nemu_capture_display` | `(handle, displayid, buffer_size, int* w, int* h, uchar* px) -> int` | 两段式调用：先 `buffer_size=0` 取宽高，再按 `4*w*h` 传缓冲；**返回 0 才是成功**（MAA 注释：官方文档此处写反）|
| `nemu_input_text` | `(handle, int size, const char* buf) -> int` | UTF-8 文本输入，0 成功 |
| `nemu_input_event_touch_down` | `(handle, displayid, x, y) -> int` | 旧版单指按下；注释称 displayid「当前只有 0 有效」|
| `nemu_input_event_touch_up` | `(handle, displayid) -> int` | 旧版单指抬起，**没有手指 id 参数** |
| `nemu_input_event_key_down/up` | `(handle, displayid, key_code) -> int` | key_code 用 Linux `input-event-codes`（非 Android KeyEvent，MAA 负责翻译）|
| `nemu_input_event_finger_touch_down` | `(handle, displayid, finger_id, x, y)` | **多指按下/移动**；`finger_id` 范围 [1, 10] |
| `nemu_input_event_finger_touch_up` | `(handle, displayid, finger_id)` | 多指抬起；头文件注释明确「多点触控可多次调用 down/up 模拟」|

对自动化最有价值的三个事实（均出自官方头文件）：

1. **多指是官方设计内能力**（finger_id 1..10，注释直接给出多指用法）；
2. **没有独立 move**——重复调用同一 finger 的 `touch_down` 即为移动（MAA 代码注释「mumu 没有单独的 move，
   重复 touch_down 即可」；MaaFramework 注释「mumu: touch_down == touch_move」）；
3. **无鼠标/滚轮导出**——11 个符号里没有任何 mouse/wheel。旁证：本机 `nemu-inputmanager.dll` 内部字符串含
   `SLOTPRESS / SLOTRELEASE / SLOTMULTIPRESS / SLOTMULTIRELEASE` 与 Qt `QTouchEvent::TouchPoint`，
   说明模拟器内部有一套带 slot 的输入管理（推断：内部有能力但未通过 external API 暴露滚轮/鼠标）。

### 1.2 保活（后台）场景与 display id

官方 `README.txt`（EmulatorExtras 镜像）说明：开启「后台保活」后高速截图接口会失效，为此新增
`nemu_get_display_id`——应用必须已启动；应用重启后要重新调用取最新 display id；单模拟器内应用多开时，
同一应用的不同分身对应不同 display id（`appIndex` 0 为主分身，1 起为副本）。

MAA 的实现细节值得抄作业（`MumuExtras.cpp`）：display id **缓存**（swipe 的 move 每几毫秒一次，
每次都问 DLL 太贵）；但只缓存「真实包名命中」的结果，fallback（"default" 或 0）不缓存，
避免游戏尚未启动时把桌面 display 锁死；截图失败时 `reload()` 一次再重试。

### 1.3 MAA / MaaFramework 集成史（回答「为什么保留/移除输入增强」）

- **2024-04**：MaaXYZ/EmulatorExtras 首次收录 MuMu external_renderer_ipc（commit `eb180816`，2024-04-05）；
  MAA PR #8939「feat: mumu extras」落地截图增强。**当时的 `MumuExtras` 虽然把 input 符号全部
  `GetProcAddress` 出来（取失败还会 return false），但从未调用**——MAA PR #17425 原文：
  「当初显然就是照这条路留的口子，这次把它补完」。
- **2024-08**：EmulatorExtras 更新「chore: update mumu 24/07/22」（commit `9424dcbe`）。
- **2025-06**：MAA PR #12876「chore: MuMuExtras 5.0+」——适配 MuMu 5.0 的
  `nx_device/12.0` 路径。
- **2026-06**：MAA PR #16994「feat: 支持 mumu 6.0 截图增强路径」——新增 `nx_device/15.0`。
- **2026-07-26**：MAA PR #17425「feat: 支持 MuMu 模拟器触控」合并——真正把输入接进 MAA：
  绑定从单指 `nemu_input_event_touch_down` 换成多指 `finger_touch_down`（contact 0-based → finger 1-based），
  增加 Android→Linux 键码映射与多指针处理；**用 MuMuManager.exe 版本探测门控**，
  不可用时干净回退 maatouch；PR 说明其对标 MaaFramework 的 `b4e126a3`（mumu 6.3.2.0 支持触控）。
- **2026-08-23**：MAA PR #17855「将 MuMu 扩展输入检查推迟至游戏开始渲染时进行」——连接时游戏可能未渲染
  （拿到的是桌面 display，尺寸与触控坐标系无关），改为游戏渲染后重新评估并在坐标系匹配时
  把输入方式从 minitouch **自动升级为 MuMu 输入**；GUI 回调 `MuMuExtrasInputStatus` 带
  `available/deferred` 两种状态。

**结论**：MAA 从未「移除」MuMu 输入增强——是「很晚才启用」（2026-07）并持续增强（2026-08）。
当前官方门槛（MAA 手册）：「MuMu 触控增强模式：需官方版 MuMu V6.3.2 及以上，目前方舟专版与国际版均不支持……
不可用时自动回退为 Minitouch（实验功能）……支持 MuMu『应用保活』（后台挂机）场景下操作」。
代码注释更直白：「MuMuManager.exe version >= 6.3.2.0 才支持 external renderer 输入，低版本行为异常」。

> 注意：对本项目的直接影响——本机 MuMu 5.30.1.3586 **低于**该门槛；MAA 生态的策略是「低版本禁用输入、只留截图」。
> 但本机既有 getevent 实验（工作区 `refs/getevent.log`）显示 finger 注入确实产生 MT slot 事件，
> 两个结论并不矛盾——门槛可能是保守/局部（保活、坐标、边缘场景），需要真机游戏内验证后才能确定是否可用（§7）。

### 1.4 MuMu 5.0 / 12.x / 6.0 的差异

- 目录版本：`nx_device/12.0` 对应 **MuMu 5.0 / MuMu 12**（Android 12 镜像）；`nx_device/15.0` 对应
  **MuMu 6.0**；更老的版本用 `shell/sdk/`。MAA 的候选路径列表按此从新到旧探测；
  MaaFramework 还优先探测 `nx_main/sdk/external_renderer_ipc.dll`（本机存在，见 §1.1）。
- 本机实测确认：`nx_main\sdk\` 与 `nx_device\12.0\shell\sdk\` 两个 DLL 导出集合一致，
  但**行为差异无法从符号判断**——MAA 的门槛（6.3.2.0）说明老版本某些路径行为异常（待验证具体差异）。
- 本项目实现（2026-10-12）：`AutoScriptor/utils/mumu_discovery.py` 的 `candidate_nemu_dll_paths` /
  `resolve_mumu_layout` 是布局知识的唯一出处——`nx_device/<Android 大版本>` 通配 + 版本号从大到小
  （不枚举版本号，未来新增版本无需改代码），回退 `nx_main/sdk`、`shell/sdk`，并把配置里的子目录
  上溯到安装根后交给 `nemu_connect`；`NemuIpcImpl` 只消费结果。回归见 `test/test_mumu_layout_adaptive.py`。
- 国际版（MuMuPlayer）与官方版/方舟专版在截图增强门槛上也有差异（MAA 手册：截图增强需官版 V4.1.26+ /
  国际版 V5.21.3+；触控增强目前「方舟专版与国际版均不支持」）。

### 1.5 MuMuManager.exe 与官方文档状态

本机实测 `MuMuManager.exe version` → `{"version": "5.30.1.3586"}`；CLI 子命令：
`version / info / create / clone / delete / rename / import / export / control / setting / adb /
simulation / sort / driver / log / sh`。
`control` 下有 `launch / shutdown / restart / show_window / hide_window / layout_window / app / tool /
shortcut`；`sh --cmd` 等价于 `adb shell`（帮助文本明写 `--cmd "input_text xxx"` == `adb shell input text xxx`、
`go_back` == `adb shell input keyevent 4`）。

**结论**：MuMuManager 是「多开/生命周期管理 + ADB 快捷方式」，**没有低延迟触控 API**；
官方也没有公开的 external_renderer_ipc 文档。EmulatorExtras 仓库 README 声明
「本仓库为 No License 开源，所有文件由对应模拟器厂商保留一切权利」——即该接口是厂商未公开文档化的
内部接口（业界靠 MAA 等项目的头文件镜像维护，推断：任何升级都可能使其行为变化）。

### 1.6 窗口消息注入（PostMessage / WM_TOUCH / InjectTouchInput）

**未找到任何一手证据**表明 MuMu Windows 版接受合成窗口消息做触控注入（待验证）：

- 搜索 MAA 仓库与全网，没有 MuMu 上用 PostMessage/SendMessage/WM_TOUCH 控制游戏的实践/issues；
  MAA PR #17010 的 X11 `XSendEvent` 方案是针对 **Wine/Proton 运行的 PC 端**，不是 MuMu；
- MuMu 主进程是 Qt5 应用（本机目录含 Qt5Core/Qt5Gui/Qt5Quick 等 DLL），渲染走自有管线，
  画面由 GPU 合成而非普通 GDI 子窗口（推断：经典模拟器的「子窗口消息注入」套路在此大概率无效）。

风险提示：即使可行，窗口注入要求窗口前台/焦点、与模拟器输入映射层耦合，不建议作为主通道；保留为观察项。

---

## 2. 高速多指输入通道对比

### 2.1 各通道要点

**① MuMu nemu（external_renderer_ipc）**
进程内 DLL 调用，无 adb/socket 中间环节。多指：官方 `finger_*`（1..10 指）。后台保活：官方专门补了
`nemu_get_display_id`，MAA 文档称支持后台挂机操作。维护：DLL 由网易随 MuMu 发布；MAA / MaaFramework
2026 年仍在活跃修复（#17425、#17855）。风险：未公开文档的内部接口、低版本行为异常（MAA 门槛 6.3.2.0）、
对方舟专版/国际版不保证。

**② minitouch（DeviceFarmer/minitouch）**
C 实现，操作 evdev、socket 协议（`d/m/u/c/r/w`，contact id 多指天然支持）。
官方 README 明确警告：**Android 10 起默认不可用**（SELinux enforcing 策略），需要绕道 STFService；
一个连接只支持一个客户端；乱序事件可能冻结屏幕需重启设备。
尽管有此警告，MAA 至今仍把 minitouch 作为 MuMu 场景的默认/回退触控模式（连接文档与
「MuMu 触控增强不可用时自动回退为 Minitouch」），说明 MuMu12 客体内实际可用（推断：MuMu 的 SELinux 策略
对该二进制放行）。维护状态：DeviceFarmer 仓库近年更新缓慢（以 README 现状为准，待验证最近活跃度）。

**③ MaaTouch（MaaAssistantArknights/MaaTouch）**
MAA 用 Java + 安卓原生 `InputDevice` 重写的 minitouch，协议完全兼容（`c/r/d/m/u/w/k/t`），
专为 Android 10+ 设计（绕开 minitouch 的 SELinux 问题）；MAA 中标注「实验功能」。
多指：支持（contact id）。延迟量级与 minitouch 同层（socket + app_process 注入）。

**④ scrcpy**
server-client 架构：client 把 server push 到设备（`app_process` 运行，shell 权限），视频/控制分 socket。
官方 README：镜像「low latency: 35~70ms」（这是含视频链路与显示的端到端数字）。
控制协议（`control_msg.h`）包含 `INJECT_TOUCH_EVENT`，消息里带 `pointer_id`（鼠标 -1、通用手指 -2、
捏合虚拟手指 -3）——**协议本身支持任意 pointer id 并发**（推断：自定义客户端可实现多指），
但官方 UI 只做单指+捏合。**可以只做控制不做视频**：`--no-video --no-audio`（官方文档「Control only」），
鼠标默认禁用需显式 `--mouse=uhid` 等。对自动化而言，需要自己按协议写客户端（或用第三方
client 库），工程量大；而且控制仍走 socket+设备端注入，不优于 minitouch 方案（推断）。

**⑤ ADB input / uiautomator2 / adbutils**
每次动作起一个设备端进程（`input`），叠加 adb 往返。本机实测 **adb shell 往返就 35.2ms**，
再加 `input` 进程启动开销，单次点击/滑动百毫秒级（uiautomator2 借助常驻 agent 可降到几十毫秒，
仍不适合 20~60Hz）。MAA 手册对 ADB Input 的评价：「滑动容易拖飞……滑动速度会设置得非常慢，
在需要精确控制坐标的场景下无法使用」。**多指：不支持**（`input` 命令无多指语义）。

**⑥ sendevent 批量脚本（资料收集）**
从本机 getevent 日志可见触控设备为 `/dev/input/event4`（"Xiaomi Input"，标准 MT 协议：
`ABS_MT_SLOT / ABS_MT_TRACKING_ID / ABS_MT_POSITION_X/Y / SYN_REPORT`）。
理论上可以 `adb shell` 一次批量写入整段 `sendevent` 序列（省去每事件一次往返），
支持真多指（MT slots）。但需处理 EV_SYN 提交、slot 生命周期、乱序保护，工程与风险都比 minitouch 高，
且仍走 adb（推断：延迟介于 adb 与 minitouch 之间）。仅作后备资料。

**⑦ 驱动级 / 虚拟 HID / DD 类（资料收集，风险高）**
- scrcpy 的 UHID 模式（`--keyboard=uhid --mouse=uhid`）通过 `/dev/uhid` 创建虚拟 HID；
  Android 侧表现为键盘/鼠标而非触摸屏（对触屏游戏无用；且 MuMu 客体的 `uhid` 支持情况未验证）。
- OTG/AOA 模式需要真实 USB，模拟器无此通路，不适用。
- Windows 侧虚拟输入驱动（DD 类）注入到宿主鼠标/键盘：最终仍依赖 MuMu 键位映射与前台窗口，
  后台挂机不可用，装内核驱动有系统级风险，且可能触发游戏反作弊（推断）。
  结论：**不推荐**，仅记录。

### 2.2 对比矩阵（方案 × 延迟 × 多指 × 后台 × MuMu 兼容 × 风险）

| 通道 | 延迟量级 | 多指 | 后台可用 | MuMu12/Android12 兼容 | 维护状态 | 风险 |
| --- | --- | --- | --- | --- | --- | --- |
| nemu finger_* | 进程内 DLL；截图同通道实测 2.1ms/帧，输入边沿待实测 | ✅ 1..10 指 | ✅（保活 + display id）| 需 MuMu ≥6.3.2（官方口径）；本机 5.30.1.3586 待验证 | 活跃（MAA/MaaFw 2026 仍有 PR）| 未公开接口、版本门控、专版不支持 |
| minitouch | socket 事件流，无进程启动；RTT 经 adb forward | ✅（contact）| ✅（evdev 层与窗口无关）| Android10+ 有 SELinux 风险；MAA 仍用于 MuMu12 | 上游缓慢；MAA 打包 | 需 push 二进制；乱序可冻结屏幕 |
| MaaTouch | 同 minitouch 量级 | ✅ | ✅ | 专为 Android 10+ | MAA 维护；标注实验 | 实验特性 |
| scrcpy 控制协议 | 镜像 35~70ms（含视频）；纯控制在 1 RTT + 注入级（无官方数字）| 协议支持任意 pointer id；默认 UI 单指 | 依赖设备端 server 常驻 | 通用（Android 5+）| 活跃（v4.1）| 需自写客户端；工程量大 |
| adb input / uiautomator2 | ≥35ms/命令 + 进程启动 → 数十至数百 ms | ❌ | ✅ | 通用 | 活跃 | 慢；滑动不可控；MAA 明示「拖飞」 |
| sendevent 批量 | adb 往返 + 事件流（未实测）| ✅（MT slots）| ✅ | 需 /dev/input 可写 | 无官方 | 手写协议易错 |
| 窗口消息注入 | 未知 | 未知 | ❌（需前台）| **无一手证据** | — | 大概率无效；不建议 |
| DD/虚拟 HID/驱动 | 宿主层，不可量化 | 取决于实现 | ❌ | 取决于键位映射 | 第三方 | 内核驱动风险、合规风险 |
---

## 3. 实时视觉反馈控制（钓鱼类）

### 3.1 现成参考实现：BetterGI 原神自动钓鱼（源码级）

关键文件（均已核对源码）：

- `BetterGenshinImpact/GameTask/AutoFishing/Behaviours.cs`——`Fishing` 行为类（约 L1163 起）即
  「拉条」控制循环；
- `BetterGenshinImpact/GameTask/AutoFishing/AutoFishingImageRecognition.cs`——`GetFishBarRect()` 识别；
- `BetterGenshinImpact/GameTask/TaskTriggerDispatcher.cs`——调度器，`Start(..., int interval = 50)`，
  **默认 50ms 定时截图循环（20Hz）**。

**检测算法（GetFishBarRect）**：在预设区域（FishBoxRect）内：
1. BGR→HSV（full range）后 `inRange` 取黄色（拉条框的黄色约 HSV(43, 63, 255) 附近，上下浮动区间）；
2. 二值化 + `findContours`（EXTERNAL, APPROX_SIMPLE）；
3. 过滤倾斜轮廓（最小外接矩形角度 `% 45 <= 1`——箭头边缘是 45°）；
4. 取最宽矩形为基准，保留同一水平线（中心 y 差 < 高度/5）且高度相近、宽度 > 高度/4 的矩形；
   返回矩形列表（游标在区间外=2 个矩形；游标在区间内=区间被游标切成 3 个矩形）。

**控制逻辑（bang-bang + 隐式滞回，无 PID/无卡尔曼）**：
- `count == 2`：较窄者为游标、较宽者为目标；**游标 X 在目标 X 左侧 → 按下左键；否则松开**；
  异常保护：目标宽 < 游标宽×10 视为无效检测，本帧不动；
- `count == 3`（游标在区间中）：按 X 排序取 left/cursor/right；
  **右半段长度 ≤ 左半段长度（游标到达中点）→ 松开；否则保持按下**；
- 用 `_prevMouseEvent` 记录当前键状态，**只在需要变化时发 down/up**（天然去抖，等效施密特触发器）；
- 连续 1 秒检测不到矩形 → 判定钓鱼结束，强制 `LeftButtonUp()` 并在退出路径确保松开。

**可直接复用的三个工程结论**：① 20Hz 闭环 + 中点滞回就足以稳定此类小游戏（BetterGI 大规模实跑验证）；
② 状态记忆+边沿触发是防抖动关键；③ 任何退出路径都必须兜底「松开」。

差异说明：BetterGI 控制的是 PC 客户端（Win32 SendInput 鼠标左键按住/松开），我们控制的是安卓触屏——
把「按下/松开」换成「`finger_touch_down` 按住 / `finger_touch_up` 松开」即可，算法层完全迁移。

### 3.2 其它参考项目

- **ZenlessZoneZero-OneDragon**（本机副本 `docs/refs/ZenlessZoneZero-OneDragon`）：未见钓鱼模块，
  但其「战斗/闪避」等高频反应逻辑与实时线程组织可作架构参考（`src/` 下 one_dragon 框架）。
  本次 rg 未发现钓鱼/PID 相关实现（可继续检索 `flash`/`dodge` 等关键词）。
- **StarRailCopilot**（本机副本）：含 `fishing` 相关关键词（`tasks/rogue/keywords/event_option.py` 等），
  属事件文本选项而非拉条控制；本次未发现可迁移的实时控制算法。
- **March7thAssistant**：提供独立钓鱼任务，但本次未取得源码一手证据（待验证）。
- **BetterGI 的单元测试**：`Test/BetterGenshinImpact.UnitTest/GameTaskTests/AutoFishingTests/
  AutoFishingImageRecognitionTests.cs`（1080p 截图对 `GetFishBarRect` 的矩形数量断言）——
  说明该识别方案对分辨率变化有测试覆盖，可借鉴其「用真实截图做回归」的方法。

### 3.3 控制理论选型（本案系统：按住升 / 松开降）

系统模型（推断，参数需实测标定）：bar 位置 `y` 在「按住」时以约恒定速率 `v+` 上升、「松开」时以 `v-`
下降（速率可能随位置/时间缓变）。目标：把 `y` 稳定在 `[lo, hi]` 区间（或中心带）。

| 方案 | 适用性 | 说明 |
| --- | --- | --- |
| bang-bang + 死区/滞回 | 首选 | 执行器本就二值（按住/松开），bang-bang 是自然形态；死区用「目标中点」或显式阈值（Schmitt trigger）实现，防止在边界高频抖动 |
| bang-bang + 速度预测 | 强烈推荐 | 用最近 3~5 帧估计 `v`，预测 `y(t + L)`（L=端到端延迟）后决策，直接抵消采样+执行延迟造成的超调 |
| PID | 非必要 | 二值执行器下 PID 只能做「占空比 PWM」或输出阈值化，20Hz 采样下积分项易震荡；若游戏接受连续滑动（滑条）时才有意义（推断） |
| 卡尔曼滤波 | 可选 | bar 检测噪声通常很小（色块质心干净），一维常速卡尔曼主要用于平滑速度估计；三点差分/线性回归已达同等效果（推断） |

**建议的控制律（伪代码级）**：

```
e_pred = y_center_target - predict_position(y_hist, v_est, t_now + L_total)
if e_pred > +deadband:      want_hold = True    # 需要上升
elif e_pred < -deadband:    want_hold = False   # 需要下降
else:                       want_hold = keep    # 死区内保持当前状态（滞回）
if want_hold != is_holding: send down/up edge
```

**所需控制频率估算（推断，可代入实测参数）**：
允许的最大采样周期 `T_sample ≤ (deadband_half / v) / 3 − latency`。
举例：条全长 100（%），目标窗口 20（±10），全程扫过约 2s → `v = 50%/s`；
`deadband_half/v = 10/50 = 0.2s`；减掉 ~30ms 延迟后除以 3 → `T_sample ≈ 55ms`，
即 **20Hz 已够、30~60Hz 有充裕裕量**。若扫过全程只需 1s（v=100%/s），20Hz 逼近极限，
建议 30Hz 以上。另注意：模拟器/游戏渲染常限 60fps，采样高于 ~60Hz 只会读到重复帧，无收益。

### 3.4 可落地伪代码（截图循环 → 检测 → 预测 → 决策）

```python
# 独立实时线程：perf_counter 截止时间驱动，目标周期 T=16.7~33ms
# 输入：finger#1 持久按住；只在状态翻转时发 down/up（边沿触发）

state = {
    "holding": False,
    "y_hist": deque(maxlen=8),   # (t, position_pct) 环形历史
    "lost_since": None,
}
target_lo, target_hi = 0.42, 0.58          # 由标定/识别得到的目标区间（归一化）
deadband = (target_hi - target_lo) * 0.15  # 死区 = 区间宽度的 ~15%
L_total = 0.030                            # 端到端延迟估计（s），实测标定

while running:
    t0 = time.perf_counter()

    frame = capture_reuse_buffer()                  # nemu_capture_display, 复用缓冲, ~2ms
    pos = detect_bar_and_target(frame)              # ROI HSV+掩码, ~0.2ms; 失败返回 None

    if pos is None:
        state.lost_since = state.lost_since or t0
        if t0 - state.lost_since > 0.5:             # 失稳保护：检测丢失超时
            release_if_holding()                    # 强制松开, 退出本步
            break
    else:
        state.lost_since = None
        y_hist.append((t0, pos))

        v_est = estimate_velocity(y_hist)           # 线性回归斜率（%/s）
        y_pred = pos + v_est * L_total              # 位置预测
        err = center(target) - y_pred

        want_hold = state.holding                  # 死区默认保持（滞回）
        if err > +deadband: want_hold = True
        elif err < -deadband: want_hold = False

        if want_hold != state.holding:              # 只在翻转发输入（~2 次/秒）
            if want_hold: input_finger_down(1, bar_center_x, bar_center_y)
            else:         input_finger_up(1)
            state.holding = want_hold

    # 周期调度：sleep 到下一截止；Windows 下开 timeBeginPeriod(1) 或混合忙等避免 15.6ms 抖动
    sleep_until(t0 + T)

finally:
    release_if_holding()                            # 任何退出路径兜底松开
```

---

## 4. 检测方案与单帧耗时

### 4.1 方法建议

- **颜色阈值**是首选（BetterGI 同款）：bar/区间/游标通常为高饱和纯色，HSV `inRange` + 列投影或轮廓。
  对「游标把区间切成 2/3 段」的场景，直接复用 BetterGI 的矩形分解法（比逐列扫描更抗噪）。
- **ROI 化**：只在 bar 所在横条区域检测（如 900x120），实测 `HSV+inRange+findContours` 仅 **0.170ms**，
  相对全屏（~2.2ms）省一个数量级；坐标常量可与分辨率绑定并做一次性标定。
- 模板匹配 / 帧差仅在「入口/结束检测」等低频判断中使用；1080p 下小模板 matchTemplate 典型 1~5ms
  （估算，未实测），对 20~60Hz 主循环仍可接受，但没必要放进热点路径。
- 用真实截图做回归测试（BetterGI 的单元测试思路），并记录检测失败的「白屏/加载中/过场」样本。

### 4.2 本机实测单帧耗时（1280x720，OpenCV，n=200~500，预热后）

| 操作 | 中位数 | P95 | 备注 |
| --- | --- | --- | --- |
| `nemu_capture_display`（复用缓冲，无转换）| **2.09 ms** | 2.59 ms | n=240；均值 2.15ms → 466fps |
| 完整转换路径（新分配 + BGRA→BGR + flip）| 4.11 ms | 5.45 ms | n=120；均值 4.42ms（max 25.97ms 偶发）|
| BGRA→BGR `cvtColor` | 0.695 ms | 1.067 ms | 全屏 |
| BGRA→HSV `cvtColor` | 0.772 ms | 1.226 ms | 全屏 |
| `inRange`（全屏）| 0.723 ms | 0.967 ms | 全屏 |
| `findContours`（全屏掩码）| 0.739 ms | 1.017 ms | RETR_EXTERNAL + APPROX_SIMPLE |
| ROI（900×120）HSV+inRange+findContours | **0.170 ms** | 0.269 ms | n=500 |
| `np.mean` 全帧（参考基线）| 2.875 ms | 3.491 ms | n=100 |

结论：**检测成本占闭环预算 <5%**，延迟预算几乎全部由「截图通道 + 游戏帧节奏 + 输入边沿」决定；
优化重点应放在复用缓冲（省 ~2ms）、跳过 flip/转换（用 ROI 直接读原始 BGRA）、以及输入边沿延迟实测。

---

## 5. 延迟预算（20~60Hz 闭环可行性）

单次「截图→判断→按住/松开」端到端链路（目标 50ms 周期，即 20Hz）：

| 环节 | 量级 | 依据 |
| --- | --- | --- |
| 截图采集（复用缓冲）| 2~4 ms | 本机实测 |
| 色彩转换/翻转（可省）| 0~3 ms | 本机实测（4.11ms 完整路径中约一半为此）|
| ROI 检测 | 0.2 ms | 本机实测 |
| 控制决策（速度回归+比较）| <0.1 ms | Python 数值运算，忽略不计 |
| 输入边沿（finger down/up）| 预计 1~5 ms（同 DLL 进程内）| **待实测**（脚本已备）|
| 模拟器合成 + 游戏帧节奏 | 0~16.7 ms（60fps）/ 0~33 ms（30fps）| 游戏帧律 |
| **小计（典型）** | **≈ 20~30 ms** | |

在 50ms 周期下裕量 >40%；在 60Hz（16.7ms 周期）下仍可闭环但裕量变薄（主要吃游戏帧节奏）。
另外本机对比：**adb `screencap` 545.6ms/帧 ≈ 1.8fps**，即老通道根本达不到钓鱼所需频率——
这条实测数字就是本项目必须走 NemuIpc 的直接理由。`adb shell` 往返 35.2ms 的单次开销，
也决定了输入绝不能用 `input tap` 之类（每次事件叠加进程启动将轻松破百毫秒）。

独立复测（主代理 `tools/probe_nemu_latency.py`，300 帧连续采样，与本节 n=240 基准相互印证）：
`nemu_capture_display`（复用缓冲）p50=**2.67ms**、p95=3.21ms、min=2.08ms、max=4.64ms，
轮询上限 **257.6Hz**——与 2.09ms/466fps 同量级（差异来自采样脚本与机器负载），结论一致：
截图通道本身不是瓶颈。

---

## 6. 架构建议（把「实时步骤」嵌入步骤式任务引擎）

1. **独立实时线程 + 明确的启停握手**：实时步骤由步骤引擎「进入/退出」，但循环本体跑在专属线程；
   引擎线程只做生命周期管理（start/stop/超时/错误上报），避免被 OCR、日志、UI 更新等阻塞。
2. **持久化资源**：
   - DLL `handle` 进程内复用（一次 `nemu_connect`），display id 缓存 + 失败重取（借鉴 MAA 的 reload 重试）；
   - 预分配帧缓冲与 numpy 视图，**禁止每帧 `(c_ubyte*len)()` 新分配**（实测可省约 2ms/帧）；
   - 输入通道保持「按住」状态跨帧存续，只在状态翻转时发边沿（约 2 次/秒），把输入调用成本压到可忽略。
3. **环形缓冲 + 时间戳**：保存最近 8~16 帧 `(t, bar_pos)`，用于速度估计与延迟补偿；
   掉帧策略取「丢最旧」；所有时间用 `perf_counter`。
4. **失稳回退（must-have）**：
   - `try/finally` 兜底 `finger_touch_up`（钓鱼中松开是安全态）；
   - 检测丢失 >0.5s / 收到停止信号 / 引擎心跳超时 → 松开退出；
   - 输入通道不可用（老版本 MuMu 或符号缺失）→ 按「MaaTouch → minitouch → ADB」的降级链处理，
     并在 UI 明确报告降级状态（借鉴 MAA 的 `MuMuExtrasInputStatus` 思路：区分「未判定/不可用」）。
5. **调度细节**：Windows 默认计时器精度 15.6ms，会毁掉 60Hz 节拍——用 `timeBeginPeriod(1)`
   或「sleep + 短自旋」混合；控制线程不与其他重活共享 GIL 竞争热点（`ctypes.CDLL` 与 OpenCV
   调用期间会释放 GIL，Python 实现 30~60Hz 足够，推断）。
6. **参数标定步骤**（一次性）：录屏/逐帧记录「按住上升速率 v+、松开下降速率 v-、端到端响应延迟 L」，
   作为控制器参数与死区宽度依据；不同模拟器帧率（60 vs 30fps）下重新标定。

---

## 7. 待验证清单

1. **本机 MuMu 5.30.1.3586 的 finger 输入在真实游戏内的可用性**（坐标映射是否正确、游戏是否接受、
   高频 down/up 切换是否稳定）。MAA 官方门槛是 MuMuManager ≥6.3.2.0，低于该版本「行为异常」——
   本机版本低于门槛，必须实测确认（可用现有工作区脚本 `tools/probe_multitouch.py`、`bench_nemu_ipc.py`）。
2. **nemu 输入边沿的实测延迟**（down→屏幕响应、up→屏幕响应）：`tools/bench_nemu_ipc.py` 已就绪，
   但会向屏幕中心注入点击（本轮未执行）。
3. **重复 `touch_down` 作为 move 在高频下的行为**：是否被合并/产生 jitter（MAA 注释确认语义，
   但高频量化特性未知）。
4. **`nemu_input_event_touch_up`（单指旧接口）的实际语义**：无 finger 参数，是否释放所有触点？
   多人共用时是否互相干扰（未找到文档说明）。
5. **保活（后台）模式下**：display id 获取失败/应用重启后的重取时机；
   「后台挂机 + 触控」在 5.30.1.3586 上的实际表现（MAA 仅在 ≥6.3.2 上线该能力）。
6. **钓鱼小游戏的具体交互细节**（梦幻西游「钓鱼达人」）：除按住/松开外是否还有第二次确认、
   拉杆动画、判定窗口宽度、bar 速度是否随游戏等级/帧率变化——需要游戏内截图序列实测。
7. **模拟器帧率设置**对控制效果的影响（60fps 下采样 >60Hz 无增益；30fps 下延迟预算变化）。
8. **窗口消息注入**（PostMessage/WM_TOUCH/InjectTouchInput）在 MuMu 上是否有任何可行路径——
   目前无一手证据（可直接判定为「不投入」）。
9. **scrcpy 自定义客户端多指的可行性上限**（协议层支持，但设备端 MotionEvent 构造、
   MuMu 客体兼容性未验证；仅当 nemu 路线彻底不可用时才有必要评估）。
10. **MuMu 官方对 external_renderer_ipc 的授权/文档状态**：是否允许第三方分发该 DLL 或头文件
    （EmulatorExtras 声明 No License、厂商保留一切权利——商用/分发需谨慎）。

---

## 8. 来源 URL 清单

**MuMu 官方接口 / 镜像**
- EmulatorExtras 仓库（MuMu 接口收录与声明）：https://github.com/MaaXYZ/EmulatorExtras
- 官方头文件（多指 finger API、返回值语义）：https://github.com/MaaXYZ/EmulatorExtras/blob/main/Mumu/external_renderer_ipc/external_renderer_ipc.h
- 保活与 `nemu_get_display_id` 说明：https://github.com/MaaXYZ/EmulatorExtras/blob/main/Mumu/external_renderer_ipc/README.txt
- MuMu 官方帮助（ADB 端口）：https://mumu.163.com/help/20240807/40912_1073151.html

**MAA（MaaAssistantArknights）**
- `MumuExtras.h`（版本门槛注释、函数清单）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/src/MaaCore/Controller/MumuExtras.h
- `MumuExtras.cpp`（display id 缓存、reload 重试、finger 调用）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/src/MaaCore/Controller/MumuExtras.cpp
- PR #17425「feat: 支持 MuMu 模拟器触控」（触控接入、多指、版本门控）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/17425
- PR #17855「将 MuMu 扩展输入检查推迟至游戏开始渲染时进行」：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/17855
- PR #12876「chore: MuMuExtras 5.0+」（nx_device/12.0 路径）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/12876
- PR #16994「feat: 支持 mumu 6.0 截图增强路径」：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/16994
- PR #8939「feat: mumu extras」（初版截图增强）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/8939
- 连接文档（触控模式、MuMu 截图/触控增强门槛、后台挂机）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/manual/connection.md
- 回调协议（`MuMuExtrasInputStatus`、`ScreencapCost`）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/protocol/callback-schema.md
- PR #17010（X11/Wine PC 端触控，对照方案）：https://github.com/MaaAssistantArknights/MaaAssistantArknights/pull/17010

**MaaFramework**
- `MuMuPlayerExtras.h`：https://github.com/MaaXYZ/MaaFramework/blob/main/source/MaaAdbControlUnit/EmulatorExtras/MuMuPlayerExtras.h
- `MuMuPlayerExtras.cpp`（touch_move=重复 down、路径探测）：https://github.com/MaaXYZ/MaaFramework/blob/main/source/MaaAdbControlUnit/EmulatorExtras/MuMuPlayerExtras.cpp

**输入通道**
- minitouch（Android 10 SELinux 限制、协议、多指）：https://github.com/DeviceFarmer/minitouch
- MaaTouch（协议与指令集）：https://github.com/MaaAssistantArknights/MaaTouch
- scrcpy 主页（延迟声明、特性）：https://github.com/Genymobile/scrcpy
- scrcpy 控制文档（control-only 模式）：https://github.com/Genymobile/scrcpy/blob/master/doc/control.md
- scrcpy 控制协议源码（pointer_id、INJECT_TOUCH_EVENT）：https://github.com/Genymobile/scrcpy/blob/master/app/src/control_msg.h
- scrcpy 开发者文档（server 注入原理）：https://github.com/Genymobile/scrcpy/blob/master/doc/develop.md

**实时反馈控制参考**
- BetterGI `Behaviours.cs`（`Fishing` 控制循环，约 L1163 起）：https://github.com/babalae/better-genshin-impact/blob/main/BetterGenshinImpact/GameTask/AutoFishing/Behaviours.cs
- BetterGI `AutoFishingImageRecognition.cs`（`GetFishBarRect`）：https://github.com/babalae/better-genshin-impact/blob/main/BetterGenshinImpact/GameTask/AutoFishing/AutoFishingImageRecognition.cs
- BetterGI `AutoFishingTask.cs`（行为树总览）：https://github.com/babalae/better-genshin-impact/blob/main/BetterGenshinImpact/GameTask/AutoFishing/AutoFishingTask.cs
- BetterGI `TaskTriggerDispatcher.cs`（50ms 调度循环）：https://github.com/babalae/better-genshin-impact/blob/main/BetterGenshinImpact/GameTask/TaskTriggerDispatcher.cs
- BetterGI 识别单元测试（1080p 回归样例）：https://github.com/babalae/better-genshin-impact/blob/main/Test/BetterGenshinImpact.UnitTest/GameTaskTests/AutoFishingTests/AutoFishingImageRecognitionTests.cs

**本机/工作区一手工件（非 URL）**
- 本机 MuMu 5.30.1.3586（`C:\Program Files\Netease\MuMu`）：PE 导出表、MuMuManager 版本/帮助文本、
  `nemu-inputmanager.dll` 字符串分析
- 本机基准/探针脚本（均位于 `d:\Projects\mumuinner\tools\`）：`bench_capture_only.py`、`bench_cv2_detect.py`、
  `bench_nemu_ipc.py`、`probe_multitouch.py`、`inject_two_fingers.py`、`probe_concurrency.py`、
  `probe_nemu_latency.py`、`fast_nemu_io.py`、`scroll_driver.py`、`pe_exports.py`
- 多点实验产物：`d:\Projects\mumuinner\refs\getevent.log`（两个 MT slot / move / up）、
  `refs/mt_0..3_*.png`（pointer_location 覆盖层截图）、`refs/scrcpy*`（scrcpy 镜像与视频测试）
