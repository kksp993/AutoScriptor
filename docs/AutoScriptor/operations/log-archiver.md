# 错误归档当前基线

错误归档用于任务失败后保存足够还原现场的信息。当前 `src` 分支只保留源码运行路径，归档目录由 `AutoScriptor.utils.paths.get_error_archives_dir()` 决定，通常是仓库 `logs/errors/`。

## 产生位置

`TaskManager._execute_single_task()` 捕获普通异常时调用 `archive_error()`。以下情况不作为普通错误归档：

- `RequestHumanTakeover`：属于人工接管分支。
- `TaskRequireReTry`：属于 retry 分支。
- `TaskCancelled`：用户停止。
- debug mode 失败恢复会跳过归档，但普通异常仍会先归档。

## 归档内容

| 文件/目录 | 内容 |
|-----------|------|
| `error.log` | 最近日志、异常信息、上下文、完整堆栈和局部变量 |
| `current_screenshot.png` | 捕获异常时的当前画面 |
| `timed_screenshot_1.png` ~ `timed_screenshot_3.png` | 后续每秒一张 |
| `click_screenshots/` | 本任务调试截图副本 |

调试截图来自 `get_logs_root()/debug_screenshot/`。任务开始前会清空，归档后也会清空，保证归档里的截图属于本任务。

## 调试截图命名

`AutoScriptor.utils.tracer.save_debug_screenshot()` 当前生成：

```text
YYMMDD_HHMMSS_micro_c.png   # 成功点击前截图与点击点
YYMMDD_HHMMSS_micro_s.png   # 搜索/点击失败即时截图
YYMMDD_HHMMSS_micro_e.png   # OCR/提取信息截图
```

保留上限：

| 类型 | 上限 |
|------|------|
| `c` | 30 |
| `s` | 10 |
| `e` | 5 |

定位类问题优先看 `*_s.png`，它通常比延迟保存的 `current_screenshot.png` 更接近失败当下。

## 默认上下文

`collect_default_context()` 默认尝试收集：

- `mm_current_region`
- `locate_region_result`
- `bg_active_callbacks`
- `bg_signals`
- `bg_event_history`
- `python_version`
- `error_timestamp`

当前不再保留运行时覆盖率追踪和默认上下文开关。需要追加业务信息时，在调用 `archive_error()` 时传入 `extra_context`。

## 手动归档

```python
from AutoScriptor.utils.log_archiver import archive_error

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

`services/webui/error_archives.py` 提供：

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
2. 看 `bg_event_history` 是否有信号、回调或 `clear()`。
3. 看 `*_s.png` 失败即时截图。
4. 看 `current_screenshot.png` 和 timed screenshots 是否发生状态变化。
5. 看堆栈局部变量，确认参数、角色、任务状态是否异常。
