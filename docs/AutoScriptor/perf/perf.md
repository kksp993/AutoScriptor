# 性能优化模块（perf）使用指南

## 📖 概述

`perf` 模块是 AutoScriptor 的性能优化工具，专门解决 Windows 系统在后台运行时的性能问题。

### 核心问题

当你关闭显示器或让电脑进入低功耗模式时，Windows 会自动降低 CPU 频率和进程优先级，导致：
- 🐌 模拟器运行变慢、卡顿
- ⏱️ 任务执行时间大幅延长
- 💤 系统可能进入休眠，任务中断

`perf` 模块通过提升进程优先级和阻止系统休眠，确保任务在后台也能全速运行。

---

## 🚀 快速开始

### 基本使用

```python
from AutoScriptor.utils.perf import boost, unboost

# 启用性能优化（一行搞定）
boost()

# 执行你的任务...
# ...

# 任务完成后恢复（通常不需要手动调用，程序退出时会自动恢复）
unboost()
```

### 自动延迟执行

**重要**：`perf` 模块采用**延迟执行**机制，只有在真正使用 API（如 `click()`、`locate()`）时才会启用性能优化。

这意味着：
- ✅ 验证账号时：不会触发性能优化
- ✅ 执行任务时：首次调用 API 时自动启用
- ✅ 避免不必要的性能开销

你不需要手动调用 `boost()`，系统会在需要时自动启用。

---

## ⚙️ 功能详解

### 1. 进程优先级提升

**Python 进程**：提升到 `HIGH_PRIORITY_CLASS`（高优先级）
- 确保 Python 脚本获得更多 CPU 时间
- 避免被其他进程抢占

**MuMu 模拟器进程**：提升到 `ABOVE_NORMAL_PRIORITY_CLASS`（高于正常）
- 自动识别并提升以下进程：
  - `MuMuPlayer.exe`（模拟器 UI）
  - `MuMuVMMSVC.exe`（虚拟机服务）
  - `MuMuVMMHeadless.exe`（无头虚拟机）

### 2. 阻止系统休眠

使用 Windows API `SetThreadExecutionState` 实现：
- ✅ **阻止系统休眠**：即使长时间无操作，系统也不会进入休眠
- ✅ **离开模式（Away Mode）**：关闭显示器后仍以全速运行
- ❌ **不阻止显示器关闭**：默认允许关闭显示器以省电

### 3. 线程优先级提升

提升当前主线程优先级到 `THREAD_PRIORITY_HIGHEST`，确保关键操作优先执行。

---

## 🔧 高级配置

### 自定义参数

```python
from AutoScriptor.utils.perf import boost, HIGH_PRIORITY_CLASS, ABOVE_NORMAL_PRIORITY_CLASS

# 保持显示器开启（一般不推荐，更耗电）
boost(keep_display=True)

# 使用不同的进程优先级
boost(process_priority=ABOVE_NORMAL_PRIORITY_CLASS)  # 高于正常（更温和）

# 不提升 MuMu 进程（如果模拟器还没启动）
boost(boost_mumu=False)
```

### 优先级级别说明

| 级别 | 常量 | 说明 | 使用场景 |
|------|------|------|----------|
| 正常 | `NORMAL_PRIORITY_CLASS` | 默认优先级 | 恢复时使用 |
| 高于正常 | `ABOVE_NORMAL_PRIORITY_CLASS` | 略高于正常 | MuMu 进程 |
| 高 | `HIGH_PRIORITY_CLASS` | 高优先级 | Python 进程（默认） |
| 实时 | `REALTIME_PRIORITY_CLASS` | 实时优先级 | ⚠️ 不推荐，可能影响系统稳定性 |

---

## 🛡️ 自动恢复机制

`perf` 模块实现了**多重保障**，确保程序退出时自动恢复：

### 1. atexit 钩子
程序正常退出时自动调用 `unboost()`

### 2. 信号处理器
捕获 `SIGINT`（Ctrl+C）和 `SIGTERM` 信号，异常终止时也会恢复

### 3. finally 块
各入口点（CLI、WebUI）的 `finally` 块中显式调用 `unboost()`

**结果**：无论程序如何退出，优先级和电源策略都会被正确恢复。

---

## 📊 工作原理

### 延迟执行机制

```python
# api.py 中的实现
_boosted = False

def _ensure_boosted():
    """只在首次真正使用 API 时才执行性能优化"""
    global _boosted
    if _boosted:
        return
    _boosted = True
    boost()  # 首次调用时才执行

# 在主要 API 函数中调用
def click(...):
    _ensure_boosted()  # 首次点击时才 boost
    # ... 执行点击逻辑
```

**优势**：
- ✅ 验证账号时不会触发（只导入模块，不调用 API）
- ✅ 执行任务时自动启用（首次调用 `click()` 或 `locate()`）
- ✅ 避免不必要的性能开销

### 进程追踪

`perf` 模块会记录所有被提升过优先级的进程 PID，退出时统一恢复：

```python
_boosted_pids = []  # 记录被提升的进程

# boost 时记录
_boosted_pids.append(pid)

# unboost 时恢复
for pid in _boosted_pids:
    set_process_priority(pid, NORMAL_PRIORITY_CLASS)
```

---

## ⚠️ 注意事项

### 1. 管理员权限

提升进程优先级通常不需要管理员权限，但如果遇到权限问题：
- Windows 可能提示需要管理员权限
- 某些安全软件可能阻止优先级修改

### 2. 系统资源

- 提升优先级不会消耗额外 CPU 或内存
- 只是改变调度策略，让关键进程优先获得资源

### 3. 多进程场景

- `perf` 模块是**进程级别**的优化
- 每个 Python 进程独立管理自己的优先级
- 子进程不会继承父进程的优先级设置

### 4. 模拟器未启动

如果 MuMu 模拟器尚未启动，`boost_mumu_processes()` 会跳过（不会报错）
- 日志会提示："未找到 MuMu 进程（模拟器可能尚未启动）"
- 模拟器启动后，可以手动调用 `boost_mumu_processes()` 或等待下次任务执行时自动提升

---

## 🔍 故障排查

### 问题：性能优化没有生效

**检查清单**：
1. ✅ 确认是否调用了 `click()` 或 `locate()` 等 API（延迟执行机制）
2. ✅ 查看日志中是否有 "⚡ 性能优化已就绪" 消息
3. ✅ 检查是否有权限问题（Windows 安全策略）

### 问题：MuMu 进程没有被提升

**可能原因**：
- 模拟器尚未启动
- 进程名称不匹配（检查日志中的进程名）
- 权限不足

**解决方法**：
```python
from AutoScriptor.utils.perf import boost_mumu_processes

# 手动提升 MuMu 进程
boost_mumu_processes()
```

### 问题：系统仍然进入休眠

**检查**：
- 确认 `SetThreadExecutionState` 调用成功（查看日志）
- 检查 Windows 电源设置（控制面板 → 电源选项）
- 某些 BIOS 设置可能覆盖 Windows 设置

---

## 📝 示例代码

### 示例 1：基本使用（推荐）

```python
from AutoScriptor import click, T

# 不需要手动调用 boost()
# 首次调用 click() 时会自动启用性能优化
click(T("开始按钮"))
```

### 示例 2：手动控制（高级）

```python
from AutoScriptor.utils.perf import boost, unboost

# 手动启用
boost()

try:
    # 执行任务
    # ...
    pass
finally:
    # 手动恢复（通常不需要，程序退出时会自动恢复）
    unboost()
```

### 示例 3：延迟提升 MuMu（模拟器启动后）

```python
from AutoScriptor.utils.perf import boost_mumu_deferred

# 等待 5 秒后再提升 MuMu 进程（给模拟器启动时间）
boost_mumu_deferred(delay=5.0)
```

---

## 📚 相关文档

- [后台调度器（scheduler）](./scheduler.md) - 定时任务执行机制
- [API 参考](../API.md) - 完整的 API 文档

---

## 🎯 总结

`perf` 模块的核心价值：
- ✅ **自动化**：延迟执行，无需手动管理
- ✅ **可靠性**：多重保障，确保正确恢复
- ✅ **高效性**：最小开销，最大收益
- ✅ **智能性**：只在需要时启用，避免浪费资源

**记住**：大多数情况下，你不需要手动调用 `boost()`，系统会在首次使用 API 时自动启用性能优化。
