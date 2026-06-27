# 主机性能策略基线

源码运行不再主动修改 Windows 主机性能策略。

## 当前默认

| 场景 | 行为 |
|------|------|
| API 首次使用 | 不执行主机级性能切换 |
| 调度执行 | 直接刷新 `runtime_ctx` 并执行任务，不切换进程优先级 |
| WebUI 直接运行 | 线程使用普通系统调度，不提升到高优先级 |
| MuMuManager subprocess | 直接调用，不再围绕 subprocess 切换性能状态 |
| `AutoScriptor.utils.perf` | 已移除 |

## 为什么移除

旧策略同时修改 CPU 亲和性、系统休眠状态、Python 进程优先级和当前线程优先级。调度器和 MuMuManager 子进程边界还会反复执行 `unboost()` / `boost()`，导致日志出现“恢复默认优先级与电源策略”后又“性能优化已启用”。

这不是临时故障，而是确定性的生命周期策略问题。源码运行应避免在应用层强行接管整机功耗与调度，尤其不要启用 away mode 或把任务线程提到高优先级。

## 维护要求

- 不要在任务、WebUI direct-run、调度器或 MuMu 生命周期里重新添加 Windows 进程/线程优先级提升。
- 不要在应用代码里强制设置系统休眠、away mode、显示器保持点亮或 CPU 亲和性。
- 需要排查性能时优先看 OCR 频率、截图复用、NemuIpc 串行化、ADB 连接状态和任务循环，而不是给 Python/MuMu 加主机级 boost。
- 不要恢复 `AutoScriptor.utils.perf` 兼容壳；旧导入应直接改掉，避免把主机级性能策略重新带回运行链路。

修改设备启动或调度执行顺序时，同步检查 [runtime/lifecycle.md](../runtime/lifecycle.md) 和 `docs/agents/project-rules.md`。
