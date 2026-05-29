# 性能优化当前基线

`AutoScriptor.utils.perf` 只负责 Windows 进程调度和电源策略，不决定任务成功与否。

## 当前默认

| 场景 | 行为 |
|------|------|
| API 首次使用 | `AutoScriptor.core.api._ensure_boosted()` 调用 `boost(process_priority=ABOVE_NORMAL_PRIORITY_CLASS)` |
| 调度执行 | 设备启动前先 `unboost()`，设备就绪后温和 boost |
| MuMu 进程 | 默认不提升，避免影响同机其他 MuMu 用户 |
| MuMuManager subprocess | 用 `mumu_safe_subprocess()` 临时取消 boost |
| 退出 | `atexit` 和信号处理会尽力 `unboost()` |

`boost()` 函数本身默认参数仍是 `HIGH_PRIORITY_CLASS`，但任务/API 默认路径使用更温和的 `ABOVE_NORMAL_PRIORITY_CLASS`。

## boost 做什么

```python
from AutoScriptor.utils.perf import boost, unboost, ABOVE_NORMAL_PRIORITY_CLASS

boost(process_priority=ABOVE_NORMAL_PRIORITY_CLASS)
...
unboost()
```

启用时会：

1. 根据 `cfg["app"]["cpu_cores"]` 限制 Python 进程 CPU 亲和性。
2. 调用 `SetThreadExecutionState` 阻止系统休眠，并启用 away mode。
3. 设置当前 Python 进程优先级。
4. 提升当前线程优先级。
5. 仅当显式 `boost_mumu=True` 时提升 MuMu 相关进程。

恢复时会还原亲和性、电源策略、进程优先级和线程优先级，并尽力恢复记录过的 MuMu 进程。

## CPU 亲和性

`config.json -> app.cpu_cores`：

| 值 | 行为 |
|----|------|
| 缺失、`0`、负数 | 不限制 |
| 正整数 N | 限制 Python 使用前 N 个核心 |

该限制用于防止自动化进程占满所有核心导致机器卡死。退出或 `unboost()` 时恢复原掩码。

## MuMu subprocess 边界

不要在 boost 状态下直接调用 MuMuManager 子进程。当前代码在这些路径会临时 `unboost()`：

- `ensure_app_running()` 启动/确认模拟器前。
- `TaskManager._try_recover_app()` 的 close/launch/restart 恢复。
- `Scheduler._safe_shutdown_emulator()` 关闭模拟器。

原因：MuMu 子进程继承高优先级时，虚拟化/权限检测可能误判并返回启动失败。

## 何时手动调用

大多数任务脚本不需要手动调用。只有排查性能问题或做独立工具时才考虑：

```python
from AutoScriptor.utils.perf import boost_mumu_processes

boost_mumu_processes()
```

显式提升 MuMu 进程前要确认这台机器没有其他依赖 MuMu 的自动化程序。

## 排查

| 现象 | 检查 |
|------|------|
| API 没有 boost | 是否真的调用了 `click/locate/swipe` 等 API |
| MuMu 启动异常 | 是否在 boost 状态下跑了 MuMuManager |
| 机器卡顿 | 降低 `app.cpu_cores` 或使用更低 `process_priority` |
| 子进程行为异常 | 确认走了 `mumu_safe_subprocess()` 或先 `unboost()` |

修改 `perf.py`、设备启动或调度执行顺序时，同步检查 [runtime/lifecycle.md](../runtime/lifecycle.md)。
