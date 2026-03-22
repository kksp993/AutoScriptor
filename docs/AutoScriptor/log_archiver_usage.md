# 错误归档服务使用指南

## 功能概览

错误归档服务用于在任务失败时，把“足够还原现场”的信息集中保存到 `logs/errors/时间_任务名/` 下，避免后续只能靠推断定位问题。

当前归档内容包括：

1. `error.log`
2. `current_screenshot.png`
3. `timed_screenshot_1.png` ~ `timed_screenshot_3.png`
4. `click_screenshots/` 目录中的调试截图
5. 自动收集的上下文信息
6. 完整堆栈跟踪和局部变量

## 自动上下文收集

错误归档默认会自动收集以下上下文：

1. `mm_current_region`: `MapManager` 中记录的当前环境 `env/loc`
2. `locate_region_result`: `locate_region(check_only=True)` 的识别结果
3. `bg_active_callbacks`: `BackgroundMonitor` 当前注册的后台回调
4. `bg_signals`: `BackgroundMonitor` 当前信号状态
5. `bg_event_history`: `BackgroundMonitor` 最近 50 条事件历史
6. `code_coverage`: 最近执行过的文件/函数统计
7. `python_version`: Python 版本
8. `error_timestamp`: 错误发生时间

其中 `bg_event_history` 现在会记录：

1. 回调触发
2. 回调完成
3. 回调异常
4. 信号变化
5. `clear()` 调用

示例：

```text
[08:54:42] clear() 被调用 (clear_signals=True)
[09:46:56] 回调触发: try_exit (identifier: (T('确定'),))
[09:46:56] signal try_exit: False → True
[09:46:56] 回调完成: try_exit
```

## 截图归档策略

### 自动保存的截图

归档时会保存：

1. `current_screenshot.png`: 异常捕获时的当前画面
2. `timed_screenshot_1~3.png`: 后续每秒一张，共 3 张
3. `click_screenshots/`
4. `click_screenshots/*_c.png`: 成功点击截图（旧版为 `c_*.png`）
5. `click_screenshots/*_s.png`: 搜索/点击失败时的即时截图（旧版为 `s_*.png`）
6. `click_screenshots/*_e.png`: OCR/提取信息截图（旧版为 `e_*.png`）

### 失败即时截图

以下场景会额外保存 `s_` 前缀截图：

1. `click()` 超时，目标始终未找到
2. `locate()` 超时，目标未出现

这类截图记录的是“失败当下”的画面，通常比错误归档晚几秒生成的 `current_screenshot.png` 更有价值。

### 调试截图保留上限

调试截图目录 `logs/debug_screenshot/` 会按类型保留最新截图：

1. 类型 `c`（文件名 `*_c.png`）保留 30 张
2. 类型 `s`（`*_s.png`）保留 10 张
3. 类型 `e`（`*_e.png`）保留 5 张

总计最多约 45 张。

同时，每个任务开始前会自动清空该目录，确保归档里的调试截图只属于当前任务。

## 配置接口

### 1. 查看当前默认配置

```python
from AutoScriptor.utils.log_archiver import get_default_context_config

config = get_default_context_config()
print(config)
# 输出：
# {
#     "mm_current_region": True,
#     "locate_region_result": True,
#     "bg_active_callbacks": True,
#     "bg_signals": True,
#     "bg_event_history": True,
#     "code_coverage": True,
#     "python_version": True,
#     "timestamp": True,
# }
```

### 2. 修改默认配置

```python
from AutoScriptor.utils.log_archiver import set_default_context_config

# 关闭 locate_region_result，避免错误处理中再次识别
set_default_context_config({
    "locate_region_result": False
})

# 只保留关键上下文
set_default_context_config({
    "mm_current_region": True,
    "bg_active_callbacks": True,
    "bg_signals": True,
    "bg_event_history": True,
    "code_coverage": False,
    "locate_region_result": False,
    "python_version": True,
    "timestamp": True,
})
```

### 3. 归档时临时覆盖配置

```python
from AutoScriptor.utils.log_archiver import archive_error, collect_default_context

try:
    pass
except Exception as e:
    # 方式1：默认上下文 + 自定义字段
    archive_error(
        "任务名",
        e,
        mixctrl=mixctrl,
        extra_context={
            "retry_count": 3,
            "task_name": "混沌炼狱塔",
        }
    )

    # 方式2：先生成自定义上下文，再统一传入
    custom_context = collect_default_context({
        "mm_current_region": True,
        "locate_region_result": False,
        "bg_active_callbacks": True,
        "bg_event_history": True,
        "code_coverage": False,
    })
    custom_context["retry_count"] = 3

    archive_error(
        "任务名",
        e,
        mixctrl=mixctrl,
        extra_context=custom_context
    )
```

## 推荐配置

### 生产环境

推荐优先保证稳定，不要在错误处理中再次触发复杂识别：

```python
from AutoScriptor.utils.log_archiver import set_default_context_config

set_default_context_config({
    "mm_current_region": True,
    "locate_region_result": False,
    "bg_active_callbacks": True,
    "bg_signals": True,
    "bg_event_history": True,
    "code_coverage": False,
    "python_version": True,
    "timestamp": True,
})
```

### 调试环境

如果你正在查一个复杂时序问题，可以保留完整默认配置：

```python
# 默认配置即为完整模式
# 其中 locate_region_result=True、code_coverage=True
```

## 在代码中使用

### 基本用法

```python
from AutoScriptor.utils.log_archiver import archive_error

try:
    ensure_in("极北村庄")
except Exception as e:
    archive_error(
        "每日任务/极北/极北村庄/极光天诏",
        e,
        mixctrl=mixctrl,
    )
```

### 添加自定义上下文

```python
from AutoScriptor.utils.log_archiver import archive_error

try:
    task_name = "极寒深渊"
    difficulty = "噩梦"
    retry_count = 3
except Exception as e:
    archive_error(
        "每日任务/极北/极寒深渊/极渊副本",
        e,
        mixctrl=mixctrl,
        extra_context={
            "task_name": task_name,
            "difficulty": difficulty,
            "retry_count": retry_count,
            "task_params": {"type": "极寒深渊"},
        }
    )
```

### 兼容旧接口

如果历史代码仍在使用旧接口，也会走同一套归档逻辑：

```python
from AutoScriptor.utils.log_archiver import archive_error_with_log, dump_error_and_log
```

其中：

1. `archive_error_with_log()` 会在归档后切换主日志文件
2. `dump_error_and_log()` 是旧入口的兼容封装

## 错误日志格式

`error.log` 现在通常包含以下结构：

```text
================================================================================
最近100行日志（来自主日志文件）:
================================================================================
[日志内容...]

================================================================================
错误信息:
================================================================================

[260306_085604] 每日任务/村庄/混沌炼狱塔 执行错误: Click T('s's's'sssss') failed...
异常类型: RuntimeError
异常信息: Click T('s's's'sssss') failed, for failed to locate target in 60 seconds

================================================================================
上下文信息:
================================================================================
  bg_active_callbacks = list([])
  bg_event_history =
    [08:54:42] clear() 被调用 (clear_signals=True)
  bg_signals = dict({})
  code_coverage = dict({'enabled': True, ...})
  error_timestamp = 2026-03-06 08:56:04
  locate_region_result = dict({'env': 登录, 'loc': 登录})
  mm_current_region = dict({'env': 登录, 'loc': 登录})
  python_version = 3.10.11

================================================================================
完整堆栈跟踪（包含局部变量）:
================================================================================
  File "D:\Projects\AutoScriptor\ZmxyOL\nav\envs\login.py:line 48", in login
    if character_name: click(T(character_name), delay=1, timeout=60)
    局部变量:
      character_name = '我是谁'
      account = '15**43**2324"
      password = '********'
      ...
```

## 常见排查顺序

建议看归档时按这个顺序排查：

1. 先看 `error.log` 的异常信息和最后 100 行日志
2. 看 `bg_event_history` 是否有信号、回调或清理行为
3. 看 `current_screenshot.png` 和 `timed_screenshot_1~3.png` 是否发生状态变化
4. 看 `click_screenshots/*_s.png`（或旧版 `s_*.png`），确认失败那一刻界面到底是什么
5. 看堆栈中的局部变量，确认调用参数是否异常

如果是定位类问题，`*_s.png`（失败截图）往往是最关键的证据。
