# 错误归档当前基线

错误归档用于任务失败后保存足够还原现场的信息。当前 `src` 分支只保留源码运行路径，归档目录由 `AutoScriptor.utils.paths.get_error_archives_dir()` 决定，通常是仓库 `logs/errors/`。

源码终端使用 Rich 显示调用文件和行号。Windows 文件超链接必须转换为标准 `file:///D:/...` URI，并对空格和非 ASCII 路径做 URL 编码；日志文字和落盘日志仍保留本机路径，避免终端把 `file://D:\\...` 错误解析为根目录 `\\`。

## 产生位置

`TaskManager._execute_single_task()` 捕获普通异常时调用 `archive_error()`。以下情况不作为普通错误归档：

- `RequestHumanTakeover`：属于人工接管分支。
- `TaskRequireReTry`：属于 retry 分支。
- `TaskCancelled`：用户停止。
- debug mode 失败恢复会跳过归档，但普通异常仍会先归档。

## 归档内容

| 文件/目录　　　　　　　　　　　　　　　　　　　　　 | 内容　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| -----------------------------------------------------| -----------------------------------------------------------------|
| `error.log`　　　　　　　　　　　　　　　　　　　　 | 最近日志、异常信息、上下文、完整堆栈和局部变量　　　　　　　　　|
| `current_screenshot.png`　　　　　　　　　　　　　　| 异常浮出时的当前画面　　　　　　　　　　　　　　　　　　　　　　|
| `debug_screenshots/`　　　　　　　　　　　　　　　　| 本次运行的调试截图（标注帧 + 运行期抓帧）　　　　　　　　　　　　|
| `task_video/segment_*.mp4`　　　　　　　　　　　　　| 任务 debug 打开时失败保留的录屏分段；任务成功或取消时删除　　　　|

归档里不再有异常后补拍的多张截图：等归档开始写时画面往往已经变了，有价值的是任务运行期间
真正发生过的画面。`AutoScriptor.logging.tracer` 独占 `get_logs_root()/debug_screenshot/`，
每批任务开始前清空，失败时整批移入 `debug_screenshots/`，因此归档里的截图只属于刚跑完的这一次。

录屏由 `AutoScriptor.logging.task_video_recorder` 挂载在 `TaskManager` 上，顶部
`ENABLE_TASK_VIDEO_RECORDING` 硬开关可临时关闭。录制按段滚动：Android 的 `screenrecord`
单次上限是 180 秒，超范围的 `--time-limit` 会直接拒绝启动，所以单段录制只能覆盖开头，而排障
需要的恰恰是失败前的几分钟。实现取 165 秒一段、只保留最新 3 段（约最后 8 分钟），每段都让
设备自己按 `--time-limit` 收尾，保证 MP4 尾部写完整；拉取后还会用 OpenCV 校验可解码性。

录屏与运行期抓帧共用同一个判据：任务生效的 `debug`，即用户在 cfg 里的覆盖优先、其次作者在 `@register_task` 声明的默认值。它是这个开关的唯一来源，
`cfg["app"]` 里没有也不再有 debug 键；任务在哪个目录、是不是自定义任务都不影响判定。
debug 关闭的任务不产生录屏和 `r` 帧，这就是"有时有视频、有时没有"的真实边界。

## 调试截图命名

`AutoScriptor.logging.tracer.save_debug_screenshot()` 当前生成：

```text
YYMMDD_HHMMSS_micro_c.png   # 成功点击前截图与点击点
YYMMDD_HHMMSS_micro_s.png   # 搜索/点击失败即时截图
YYMMDD_HHMMSS_micro_e.png   # OCR/提取信息截图
YYMMDD_HHMMSS_micro_r.png   # debug 运行中每 5 秒一张的例行抓帧
```

`c`/`s`/`e` 是决策点标注帧，由 API 层在点击、定位失败、OCR 读取时调用。`r` 是运行期时间线，
由 `MixControl.screenshot()` 送帧、`tracer.capture_run_frame()` 按间隔落盘；开关由
`TaskManager` 在任务开始时调 `set_run_capture()` 设置，批次结束后自动关闭，所以它在控制层
不需要也不应该去猜全局 debug 配置。

保留上限：

| 类型 | 上限 |
|------|------|
| `c` | 30 |
| `s` | 10 |
| `e` | 5 |
| `r` | 60 |

定位类问题优先看 `*_s.png`；要看"失败之前页面怎么一步步变成这样"就按时间顺序翻 `*_r.png`。

## 默认上下文

`collect_default_context()` 默认尝试收集：

- `bg_active_callbacks`
- `bg_signals`
- `bg_event_history`
- `action_history`
- `recognition_trace`
- `python_version`
- `error_timestamp`

需要追加业务信息时，在调用 `archive_error()` 时传入 `extra_context`，或用
`register_context_provider()` 注册一个零参数取数函数。

`action_history` 是最近 120 条输入动作（点击、滑动、按键…），带毫秒时间戳，每轮任务开始时清空。它存在的理由是**日志里的重复动作有节流**：`MixControl._log_action` 对同类动作按 1 秒合并，只在放行时写一行 INFO，并把期间被合并的条数附在后面（`（另有 N 次同类操作未逐条记录）`）。所以「日志里没有这一行」只说明被合并，不说明没执行；要判断某一步到底点没点，看 `action_history`。

`recognition_trace` 是当前任务线程最近识别结果的结构化摘要：运行时环形缓冲最多保留 32 条，归档默认写入最近 16 条。摘要包含操作、成功状态、目标/结果概况、耗时、帧来源和帧形状，不保留截图数组；读取追踪本身不会初始化设备、截图或重跑 OCR/识别。

`error.log` 开头的日志段写出来源和条数（`Recent log lines (tail N of <path>)`），并只从日志文件尾部读固定窗口，不把整个文件读进内存。日志文件本身按 8 MB × 3 轮转，不会无限增长。

位置诊断 `locate_region_result` 由 `ZmxyOL.nav` 注册，用 `cnt=1` 调用 `locate_region(check_only=True)`：跳过冷启动分支，归档时不会顺手启动游戏或 `sleep`。「当前位置未知」只在真的没有任何环境/位置匹配时出现。

## 手动归档

```python
from AutoScriptor.logging.log_archiver import archive_error

try:
    ...
except Exception as e:
    archive_error(
        "每日任务/村庄/示例",
        e,
        mixctrl=mixctrl,
        extra_context={"stage": "after_click"},
    )
```

## WebUI 错误归档页

`backend/webui/error_archives.py` 提供：

| API | 功能 |
|-----|------|
| `GET /api/error-archives` | 列表和日期分组 |
| `GET /api/error-archives/detail` | 摘要、日志段、图片列表 |
| `GET /api/error-archives/file` | 读取图片或日志文件 |
| `DELETE /api/error-archives` | 批量删除 |
| `POST /api/error-archives/import` | 导入 zip 到新归档目录 |

安全规则：

- 归档目录名必须通过安全正则，不允许 `..`、斜杠或反斜杠。
- 文件读取只能解析到归档目录内部。
- zip 导入会写到新目录 `YYMMDD_HHMMSS_import_<name>`，不会覆盖任意路径。

前端支持 Shift 连选和批量删除。

## 排查顺序

1. 看 `error.log` 的异常类型、异常信息和最后日志。
2. 用 `action_history` 确认「这一步到底执行了没有、什么时候执行的」，再判断后面为什么没反应。
3. 识别类失败看 `recognition_trace` 的最后几条操作、耗时、帧来源和结果摘要。
4. 看 `bg_event_history` 是否有信号、回调或 `clear()`。
5. 看 `*_s.png` 失败即时截图。
6. 看 `*_r.png` 时间线，还原失败前几分钟的页面变化。
7. 看 `task_video/segment_*.mp4` 里失败前最后几段录屏。
8. 看 `current_screenshot.png` 确认异常浮出时的画面。
9. 看堆栈局部变量，确认参数、角色、任务状态是否异常。
