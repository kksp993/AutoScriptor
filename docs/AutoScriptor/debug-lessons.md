# 失败排查速查

上限 1000 字；满了先合并同类项，只写现状。

## 根因

1. **固定 sleep 等界面**：动画时长不定，到点界面可能还在变。一律 `ui_T` 等出现、
   `click(..., until=ui_F(...))` 等消失。
2. **有东西吞点击**：① 遮罩压暗页面吃掉点击、不会自己消失，点关闭无效，判据是目标区
   近白像素归零、亮度减半；② 模拟器的「App 启动失败/超时」模态框，判据是同一状态反复
   重试、报错却指向各自第一步；锚点须用弹窗独有字串（`App启动超时`），**别用「确定」**
   （游戏里到处都是）。恢复路径：`try_close_via_x`、PageRouter。
3. **裸 Box 当识别目标**：`Box` 是 namedtuple，会被当多目标元组解析报
   `Unsupported target type`。用 `B(...)` 包一层。
4. **日志会漏读**：`_log_action` 按 1 秒合并同类动作，条数写在下一行。「日志没这一行」
   ≠ 没执行；查某步点没点看 `action_history`。
5. **镜像配置字段**：一条信息存两份（多开编号 ↔ ADB 端口）时要区分「推导的」和
   「手填的」：与推导结果全等才可跟随。
6. **图标会动，模板不会**：大厅图标栏每期可能插入新图标挤走旧的，写死坐标必失效；
   按文字搜会被 OCR 粘连误伤（`T("活动")` 先中「充值活动」）。改用全帧图片模板
   （`ui_map` 填 `0,0,1280,720`），**并在相隔数秒的两帧上验证**。主机屏幕同理：
   提示语「点击「开始运行」…」会抢在按钮之前命中，用 `box` 把搜索区收紧到按钮行
   （DesktopControl 命中多处时会告警）。
7. **跑测试会写真实配置**：测试进程 import 真模块、用真实 `data/` 路径；退出时
   `app_config` 末尾的 `atexit` 还会把测试留在内存里的 `cfg._config` 存回去，看起来
   像「配置全丢了」。防线：`_refuse_test_process_write` 拒绝测试进程写非临时目录；
   判据冻结在 `app_config` 导入时（Paddle 会 import unittest，写盘时实时查会把真实
   运行进程全拒——2026-10-09 事故）；起 app 子进程必须带 `AUTOSCRIPTOR_DATA_DIR`。
8. **竖屏 App 点不动**：NemuIpc 注入点击在竖屏 720x1280 下无效——同一坐标 nemu 点
   20 次页面纹丝不动、ADB 一次即切换（2026-10-10 实机对照）。竖屏任务入口
   `switch_base("mumu")`、`finally` 恢复 `nemu`；截图仍走 NemuIpc。
9. **4399 游戏盒的登录按钮只认长按**：快速点击（`click()` 默认 10-20ms 按压）连点
   多次界面毫无反应；同一坐标 700ms 长按立即登录成功（2026-10-10 实机对照）。登录
   提交对 HZ4399 用同点 swipe（发出 `input swipe x y x y 700`），别退回 click。
10. **改完不生效先查 5000 端口归属**：旧进程的 multiprocessing 子进程会带着旧代码
    继续占着 5000 端口，浏览器/WebUI 一直连的是旧后端（表现：改完没效果、持续拒写）。
    `netstat -ano | findstr :5000` 看 PID，杀掉旧进程再重启。
11. **动态页面别用串行「定位→点击→再定位」**：页面一有动画/弹窗/滚动，第二次定位
    就卡在 `assure_stable` 的两帧一致重试里直到超时报「定位失败」——`ui_T`（无稳定性
    要求）通过、紧接着 `click`（默认有）失败，就是这个模式（2026-10-10 领券失败）。
    改用 `click_all(..., if_exist=True, assure_stable=False)`：一帧冻结结果上把所有
    命中一次点完（多张券一次处理），轮次之间先关提示框；`if_exist` 让「没有目标」
    返回 0 而不是抛异常。
12. **MuMu 库路径随版本换目录**：`shell/sdk` → `nx_device/12.0/shell/sdk`（MuMu
    5.0/12）→ `nx_device/15.0/...`（MuMu 6.0）；`nx_device/<号>` 的号是 Android 大
    版本、还会继续加，写死任一个都会在新版本上报「找不到 external_renderer_ipc.dll」。
    一律通配 + 版本排序（`mumu_discovery.resolve_mumu_layout`，路径知识的唯一出处）。
    同类陷阱：`nx_main/sdk` 有同名 DLL（MuMu 5.30 实测存在），会让子目录冒充安装根；
   安装根只认含 `nx_main`/`nx_device` 子目录的那一级。`emu_path` 必须指向
    `MuMuManager.exe`——它被当 CLI 执行，指到 GUI 的 `MuMuPlayer.exe` 会静默失效。
13. **`ui_map` 会在错误时机建表**：它在模块导入时读一次资产根，而游戏层是在自己
    包导入时才 `set_assets_root()`。谁先导入 `ui_map`（例如某个测试模块顶层
    `import ui_map`），表就按错误（或缺失）的根建好并一直空着，之后按 key 的目标
    报 `KeyError`。改法是 `get_ui()` 比对资产根并原地刷新——表对象只有一个，
    模块级 `ui`、`AutoScriptor.ui` 都靠原地 `clear()+update()` 才一起看到新表。
14. **别用 `os.getcwd()` 定日志/数据位置**：安装位里 cwd 是用户自己的工作目录，
    源码位恰好等于仓库根所以看不出来。日志统一走 `get_logs_root()`（数据根下的
    `logs/log/`），与 `log_archiver` 的兜底路径一致。同类：跑完
    `release_probe\run_probe.ps1` 后当前 shell 会残留 `AUTOSCRIPTOR_DATA_DIR`，
    接着跑仓库测试会去探针目录找职业脚本并报导入错误，看着像代码坏了。

## 手法

- 日志 `模块:行号` 直接映射源码，别猜。
- **识别逻辑不必上设备验证**：按实机 OCR 坐标合成一张帧让真识别跑，断言「认得出」
  「点得中」；期望值取自实机测量。
- 存疑就离线 OCR 复现；同路径取成功/失败各一次对照。
- 只在真运行暴露的接口用冒烟测试兜；归档见 `operations/log-archiver.md`。

## 约定

- 做不完的任务 `deprecated=True` 下架，同步 `test/test_tasks`。
