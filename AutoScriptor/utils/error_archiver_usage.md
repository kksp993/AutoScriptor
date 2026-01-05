# 错误归档服务使用指南

## 自动上下文收集

错误归档服务现在会自动收集以下上下文信息：

1. **mm_current_region**: MapManager 中存储的当前环境(env)和位置(loc)
2. **locate_region_result**: `locate_region()` 实际识别结果（只跑一次，避免递归）
3. **bg_active_callbacks**: BackgroundMonitor 中正在运行的后台任务列表
4. **bg_signals**: BackgroundMonitor 中的信号状态
5. **python_version**: Python 版本信息
6. **error_timestamp**: 错误发生的时间戳

## 配置接口

### 1. 查看当前配置

```python
from AutoScriptor.utils.error_archiver import get_default_context_config

config = get_default_context_config()
print(config)
# 输出：
# {
#     "mm_current_region": True,
#     "locate_region_result": True,
#     "bg_active_callbacks": True,
#     "bg_signals": True,
#     "python_version": True,
#     "timestamp": True,
# }
```

### 2. 修改默认配置

```python
from AutoScriptor.utils.error_archiver import set_default_context_config

# 禁用 locate_region_result（避免在错误处理中再次识别，可能导致递归）
set_default_context_config({
    "locate_region_result": False
})

# 只启用部分信息
set_default_context_config({
    "mm_current_region": True,
    "bg_active_callbacks": True,
    "locate_region_result": False,
    "bg_signals": False,
    "python_version": False,
    "timestamp": False,
})
```

### 3. 在归档时临时覆盖配置

```python
from AutoScriptor.utils.error_archiver import archive_error, collect_default_context

try:
    # 你的代码
    pass
except Exception as e:
    # 方式1：使用默认配置 + 额外上下文
    archive_error(
        "任务名",
        e,
        mixctrl=mixctrl,
        extra_context={
            "custom_var": "value",
            "retry_count": 3
        }
    )
    
    # 方式2：自定义收集的上下文
    custom_context = collect_default_context({
        "mm_current_region": True,
        "locate_region_result": False,  # 禁用这个
        "bg_active_callbacks": True,
    })
    custom_context["custom_var"] = "value"
    
    archive_error(
        "任务名",
        e,
        mixctrl=mixctrl,
        extra_context=custom_context
    )
```

## 推荐配置

### 生产环境（避免递归错误）

```python
from AutoScriptor.utils.error_archiver import set_default_context_config

# 禁用 locate_region_result，避免在错误处理中再次触发识别
set_default_context_config({
    "mm_current_region": True,        # 使用 MapManager 中存储的值
    "locate_region_result": False,     # 禁用实际识别（避免递归）
    "bg_active_callbacks": True,       # 查看后台任务
    "bg_signals": True,                # 查看信号状态
    "python_version": True,            # Python 版本
    "timestamp": True,                  # 时间戳
})
```

### 调试环境（完整信息）

```python
# 使用默认配置（全部启用）
# 注意：locate_region_result 可能会在错误处理中再次触发错误
```

## 在代码中使用

### 基本用法（自动收集默认上下文）

```python
from AutoScriptor.utils.error_archiver import archive_error

try:
    # 你的任务代码
    ensure_in("极北村庄")
    # ...
except Exception as e:
    archive_error("每日任务/极北/极北村庄/极光天诏", e, mixctrl=mixctrl)
    # 会自动收集所有默认上下文信息
```

### 添加自定义上下文

```python
from AutoScriptor.utils.error_archiver import archive_error

try:
    task_name = "极寒深渊"
    difficulty = "噩梦"
    retry_count = 3
    # ...
except Exception as e:
    archive_error(
        "每日任务/极北/极寒深渊/极渊副本",
        e,
        mixctrl=mixctrl,
        extra_context={
            "task_name": task_name,
            "difficulty": difficulty,
            "retry_count": retry_count,
            "task_params": {"type": "极寒深渊"}
        }
    )
```

## 错误日志格式

错误日志现在包含：

```
================================================================================
最近100行日志（来自主日志文件）:
================================================================================
[日志内容...]

================================================================================
错误信息:
================================================================================

[260105_121016] 每日任务/本命空间/本命空间 执行错误: Click B(50,30,30,30) until <lambda> failed...
异常类型: RuntimeError
异常信息: Click B(50,30,30,30) until <lambda> failed, for until function not satisfied in 30 seconds

================================================================================
上下文信息:
================================================================================
  bg_active_callbacks = ['战斗结束', '战斗失败']
  bg_signals = {'try_exit': False, 'Pause_battle': False}
  error_timestamp = 2026-01-05 12:10:16
  locate_region_result = {'env': '本命空间', 'loc': '本命空间'}
  mm_current_region = {'env': '本命空间', 'loc': '本命空间'}
  python_version = 3.10.0

================================================================================
完整堆栈跟踪（包含局部变量）:
================================================================================
  File "D:\Projects\AutoScriptor\ZmxyOL\task\daily_task\bmkj\bmkj.py", line 34, in task
    click(B(50,30,30,30),until=lambda: ui_T(T("空间任务")))
    局部变量:
      name = 本命空间
      self = <ZmxyOL.battle.procedure.heaven.Heaven object>
      ...

```
