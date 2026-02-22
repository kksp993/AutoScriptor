# 调度与任务系统文档

本目录包含 AutoScriptor 任务系统、后台调度和性能优化的完整文档。

## 📚 文档索引

### [后台调度器与任务系统（scheduler）](./scheduler.md)

详细介绍任务的定义、注册和自动调度执行：

- ✅ **任务是什么**：`@register_task` 装饰器、四大任务类别、config.json 结构
- ✅ **调度器核心**：智能等待、逐个执行、每个任务后 save+reload
- ✅ **状态管理**：待运行（🟢）/ 运行中（🟡）/ 发生错误（🔴）
- ✅ **外部唤醒**：配置重载后 `wake()` 立即中断等待
- ✅ **任务感知日志**：执行时日志自动显示任务中文名称
- ✅ **完整生命周期**：从注册到执行到时间更新的全流程

**适用场景**：
- 需要了解任务系统的工作原理
- 编写新任务或修改现有任务
- 排查调度器不执行/延迟执行等问题

---

### [性能优化模块（perf）](./perf.md)

详细介绍 `perf` 模块的功能和使用方法：

- ✅ **核心功能**：进程优先级提升、阻止系统休眠、线程优化
- ✅ **延迟执行机制**：只在真正使用 API 时才启用，避免不必要的开销
- ✅ **自动恢复机制**：多重保障，确保程序退出时正确恢复
- ✅ **故障排查**：常见问题和解决方法

**适用场景**：
- 需要了解性能优化的工作原理
- 遇到后台运行卡顿问题
- 需要自定义性能优化参数

---

## 🚀 快速开始

### 编写一个任务

```python
# ZmxyOL/task/daily_task/village/my_task.py
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def task():
    ensure_in("村庄")
    click(T("目标按钮"))
```

启动后自动注册为 `每日任务/村庄/my_task`（英文文件名会被翻译为中文，如果在 `translations.py` 中有映射的话）。

### 带参数的任务

```python
@register_task(default_offset_hours=10)
def task(battle_loop: int = 100):
    # 用户可在 CLI 中调整 battle_loop 参数
    for i in range(battle_loop):
        ...
```

### 后台调度

1. **激活调度器**：在 CLI 选择【开始执行 R】
2. **查看状态**：主菜单显示调度器状态和下次执行时间
3. **自动执行**：调度器根据 `next_exec_time` 精确等待并逐个执行到期任务
4. **重新加载**：按 T 重载配置后，调度器被唤醒立即重新检查

### 性能优化

大多数情况下，你**不需要**手动调用 `boost()`，系统会在首次使用 API 时自动启用：

```python
from AutoScriptor import click, T

# 首次调用 click() 时会自动启用性能优化
click(T("开始按钮"))
```

---

## 📖 相关文档

- [API 参考](../API.md) - 完整的 API 文档
- [日志归档](../log_archiver_usage.md) - 错误日志归档机制

---

## 💡 常见问题

### Q: 调度器为什么不自动执行任务？

**A**: 检查以下几点：
1. 调度器状态是否为"运行中"（🟡）？
2. 任务是否已开启（`on=True`）？
3. 任务的 `next_exec_time` 是否已到期？
4. 按 T 重载配置后调度器是否被唤醒？

### Q: 如何让任务立即执行？

**A**: 在 `config.json` 中将任务的 `next_exec_time` 设为 `0`，然后按 T 重新加载。调度器会被唤醒并立即执行该任务。

### Q: 如何自定义任务执行间隔？

**A**: 两种方式：

1. **装饰器参数**：

```python
@register_task(default_offset_hours=6)
def task():
    ...  # 执行后 6 小时再运行
```

2. **config.json 字段**：

```json
{
  "某个任务": {
    "on": true,
    "next_exec_offset_hours": 6,
    "params": {}
  }
}
```

优先级：函数参数 > 任务节点字段 > 默认类别规则（每日/每周/活动）。

### Q: 为什么日志显示的是 api:298 而不是任务名？

**A**: 确认 `setup_task_aware_logging()` 是否在启动时被调用（`api.py` 和 `run.py` 中各调用一次）。任务名只在 `execute_tasks()` 执行 `fn()` 期间显示。

---

## 🔗 相关链接

- [项目主页](../../../README.md)
- [完整文档索引](../)
