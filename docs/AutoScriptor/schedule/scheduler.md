# 后台调度器（Scheduler）与任务系统

## 📖 概述

后台调度器是 AutoScriptor 的**自动任务执行系统**，可以在你不在电脑前时自动运行任务。

### 核心能力

- ⏰ **智能等待**：根据最近到期任务的时间精确 sleep，不浪费等待
- 🚀 **逐个执行**：每次只执行一个到期任务，执行完后保存配置、重新加载、再检查下一个
- 📊 **状态管理**：实时显示调度器状态（待运行/运行中/发生错误）
- 🔄 **外部唤醒**：配置重载后可立即唤醒调度器重新检查到期任务
- 📝 **任务感知日志**：执行任务时日志自动显示当前任务的中文名称

---

## 🎯 什么是"任务"

### 任务的本质

任务是一个用 `@register_task` 装饰的 Python 函数，定义在 `ZmxyOL/task/` 目录下。装饰器会根据文件路径**自动注册**到全局配置 `cfg["tasks"]` 中，形成树形结构。

### 一个最小的任务

```python
# ZmxyOL/task/normal_task/back_to_login.py
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def task():
    ensure_in("登录")
```

只需用 `@register_task` 装饰，系统会自动：
1. 根据文件路径 `normal_task/back_to_login.py` → 翻译为 `一般任务/返回开始`
2. 在 `cfg["tasks"]["一般任务"]["返回开始"]` 中注册此函数
3. 保留用户在 `config.json` 中的 `on`、`next_exec_time` 等配置

### 任务在 config.json 中的结构

```json
{
  "tasks": {
    "每日任务": {
      "村庄": {
        "混沌炼狱塔": {
          "on": true,
          "next_exec_time": 1771794000.0,
          "params": {},
          "last_buy_time": 177172757.063918
        },
        "天选阁": {
          "on": true,
          "next_exec_time": 1771794000.0,
          "params": {}
        }
      }
    },
    "一般任务": {
      "登录": {
        "on": false,
        "next_exec_time": 0,
        "params": {}
      }
    }
  }
}
```

### 任务节点的核心字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `fn` | function | 任务函数引用（运行时注入，不持久化到 JSON） |
| `on` | bool | 是否启用此任务 |
| `next_exec_time` | float | 下次执行的 Unix 时间戳（0 = 立即可执行） |
| `params` | dict | 任务参数（传递给 `fn(**params)`） |
| `order` | int | 注册顺序（控制菜单显示排序） |
| `param_meta` | dict | 枚举参数的类型元数据（用于反序列化） |
| `next_exec_offset_hours` | int | 可选，执行后延迟 N 小时再调度 |

### 任务的四大类别

| 类别 | 目录 | 执行后行为 | 典型场景 |
|------|------|-----------|---------|
| **每日任务** | `daily_task/` | `next_exec_time` 设为明天 05:00 | 每天需要做的日常 |
| **每周任务** | `weekly_task/` | `next_exec_time` 设为下周一 05:00 | 每周一次的任务 |
| **活动任务** | `event_task/` | 同每日任务（明天 05:00） | 限时活动 |
| **一般任务** | `normal_task/` | `on` 设为 `false`（执行一次即关闭） | 登录、返回等辅助操作 |

> 📌 凌晨 05:00 是"日期分界线"——05:00 之前视为前一天。

### 任务的注册流程

```
启动程序
  ↓
ZmxyOL/task/__init__.py 执行
  ↓
gather_py_files() → 收集所有 .py 文件
  ↓
sort_py_files() → 按 _order.txt 排序
  ↓
import_modules() → 逐一导入，触发 @register_task
  ↓
@register_task 根据文件路径写入 cfg["tasks"]
  ↓
normalize_cfg_tasks_to_cn() → 英文路径统一翻译为中文
  ↓
sort_tasks() → 按 order 字段排序
  ↓
cfg.save_config() → 持久化到 config.json
```

### 带参数的任务

任务函数可以接受参数，参数默认值会自动提取到 `params` 字段：

```python
@register_task
def task(battle_loop: int = 1000):
    h.battle_tasks(task_table=TASK_TABLE, max_loops=battle_loop)
```

用户可在 CLI 或 `config.json` 中修改 `params.battle_loop` 的值。

### 带枚举参数的任务

枚举参数会自动序列化为字符串，并记录类型元数据：

```python
from enum import Enum

class Difficulty(Enum):
    easy = "easy"
    hard = "hard"

@register_task
def task(difficulty: Difficulty = Difficulty.hard):
    ...
```

对应 config.json：
```json
{
  "params": { "difficulty": "hard" },
  "param_meta": { "difficulty": "ZmxyOL.task.normal_task.xxx.Difficulty" }
}
```

### 表格参数（TableParam）

多关卡任务可使用 `TableParam` 将每个关卡的配置聚合为一张表格：

```python
from AutoScriptor.utils.table_param import TableParam

@register_task
def task(
    battle_config: TableParam = TableParam(
        {
            "虎神之崖": {"difficulty": Nandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
            "苍龙幽谷": {"difficulty": Nandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        },
        column_labels={"difficulty": "难度", "cancel_on_failed": "不用点券复活", "battle_flow": "战斗招式"},
    ),
):
    for name, row in battle_config.items():
        ...
```

前端自动渲染为可编辑表格，每行一个关卡，每列一个配置项。详见 [`docs/tasks/table-param.md`](../../tasks/table-param.md)。

### 自定义执行间隔

```python
@register_task(default_offset_hours=10)
def task():
    ...  # 执行后 10 小时再调度
```

### 执行排序：_order.txt

每个目录下可放一个 `_order.txt`，每行一个文件/目录名（英文），控制导入和显示顺序：

```
daily_task
weekly_task
event_task
normal_task
```

---

## 📊 调度器状态

调度器有三种状态，用颜色和图标标识：

### 🟢 待运行（PENDING）

**含义**：调度器已启动，但尚未激活自动执行

**触发条件**：
- 程序刚启动时
- 用户退出程序时
- 手动恢复错误状态后

**行为**：不会自动执行任务，只等待用户手动执行

### 🟡 运行中（RUNNING）

**含义**：调度器已激活，正在后台监控并自动执行任务

**触发条件**：
- 用户按下【开始执行 R】后调用 `scheduler.activate()`

**行为**：
- ✅ 根据最近到期任务的时间精确等待（不再固定 1 小时）
- ✅ 发现到期任务后逐个执行，每个任务完成后保存配置并重新加载
- ✅ 可被 `scheduler.wake()` 唤醒，立即中断等待重新检查
- ✅ 执行期间日志显示当前任务中文名称

### 🔴 发生错误（ERROR）

**含义**：调度器因连续失败而停止自动执行

**触发条件**：
- 连续 3 次任务执行失败

**行为**：
- ❌ 停止自动执行任务
- ⚠️ 需要手动恢复才能继续

**恢复方法**：
- CLI：在主菜单选择【开始执行】
- WebUI：点击【恢复调度】按钮

---

## 🔍 工作原理（新版）

### 核心循环

```python
def _loop(self):
    while True:
        interval = self._get_wait_interval()  # 动态计算等待时间
        self._wake.clear()
        self._wake.wait(interval)  # 可被 wake() 打断
        if self._stop.is_set():
            break
        if self.state != SchedulerState.RUNNING:
            continue
        self._check_and_run()
```

**关键改进**：
- ✅ 使用 `_wake.wait(interval)` 代替 `_stop.wait(CHECK_INTERVAL)`
- ✅ 等待时间基于最近到期任务动态计算，不再固定 1 小时
- ✅ 外部可通过 `wake()` 立即唤醒，适用于配置重载后的场景

### 智能等待时间计算

```python
def _get_wait_interval(self):
    # 1. 扫描所有 on=True 的任务，收集 next_exec_time
    # 2. 如果存在已到期任务（next_exec_time <= now）→ 返回 0（立即执行）
    # 3. 否则，等到最近的未来任务到期：min(future_times) - now
    # 4. 没有任何启用的任务 → 默认等待 1 小时
```

### 逐个执行流程

```
_check_and_run() 开始
  ↓
while 循环:
  ├── 扫描到期任务 → 没有？→ 退出循环
  ├── 首次？→ 启动模拟器（如果未运行）
  ├── 取第一个到期任务 task_key
  ├── task_manager.execute_tasks([task_key])  ← 只执行一个
  ├── cfg.save_config()       ← 保存配置
  ├── task_manager.reload_tasks()  ← 重新加载（重新扫描 fn）
  ├── 重新扫描到期任务 → 有下一个？→ 继续循环
  └── 循环结束
  ↓
_post_execution_action()  ← 全部完成后才执行（关闭模拟器等）
```

**为什么逐个执行？**
- 每个任务执行后可能影响其他任务的状态
- 保存后重新加载保证 `fn` 函数引用始终最新
- 重新扫描到期任务可以发现因配置变化而新增的到期任务

### 外部唤醒机制

```python
def wake(self):
    """中断当前等待，立即重新检查到期任务。"""
    self._wake.set()
```

调用场景：
- 用户按 **T（重新加载）** 后，`scheduler.wake()` 立即唤醒
- 手动修改 `config.json` 后重载，调度器不需等到下次检查周期

### 任务感知日志

执行任务时，日志格式自动注入任务名称：

```
[I 返回开始 260222 17:44:49 api:200] Locate: [T('进入游戏')]
[I 返回开始 260222 17:44:49 task_manager:236] ▶️  执行成功: 一般任务/返回开始
```

非任务时保持原始格式：

```
[I 260222 17:44:49 scheduler:211] 📅 定时执行完成: 成功 2, 失败 0
```

实现方式：
- `set_current_task(name)` 设置线程局部变量
- `_TaskAwareFormatter` 继承 `logzero.LogFormatter`，在 format 时注入 `task_prefix`
- `task_manager.execute_tasks()` 在 `fn()` 前/后 设置/清除

---

## 🔧 配置说明

### 检查间隔（回退值）

如果没有任何启用的任务，调度器默认回退到 1 小时检查一次：

```python
CHECK_INTERVAL = 3600  # 秒（1 小时）
```

正常情况下，等待时间根据最近到期任务精确计算。

### 失败阈值

连续失败 **3 次**后进入错误状态：

```python
MAX_CONSECUTIVE_ERRORS = 3
```

**计数规则**：
- 一次执行中，只要有任务失败，就算一次失败
- 成功执行会重置失败计数
- 连续 3 次失败后停止自动执行

---

## 💻 CLI 使用

### 查看状态

在主菜单可以看到调度器状态：

```
🚀 开始执行【R】 🟡运行中 (下次执行: 2026-02-23 05:00)
```

### 激活调度器

1. 选择【开始执行 R】
2. 调度器状态自动变为"运行中"
3. 后台线程开始智能等待并执行到期任务

### 重新加载任务（T）

1. 选择【重新加载 T】
2. 从 `config.json` 重新加载配置
3. 调度器被唤醒，立即重新检查到期任务
4. 如果有到期任务，后台线程立即开始执行

### 恢复错误状态

如果调度器进入错误状态：
1. 选择【开始执行 R】
2. 系统会自动重置错误计数并恢复运行

---

## ⚙️ 执行后动作

任务执行完成后，可以根据配置执行不同动作：

### 配置位置

`config.json` → `emulator.post_execution`

### 可选值

| 值 | 说明 | 行为 |
|----|------|------|
| `NULL` | 什么都不做（默认） | 保持模拟器和游戏运行 |
| `CLOSE_GAME_ONLY` | 仅关闭游戏 | 关闭游戏应用，模拟器继续运行 |
| `CLOSE_MUMU` | 关闭模拟器 | 关闭游戏 + 关闭模拟器 |

### 配置示例

```json
{
  "emulator": {
    "index": 1,
    "adb_addr": "127.0.0.1:16416",
    "post_execution": "CLOSE_MUMU"
  }
}
```

> ⚠️ 执行后动作只在**所有到期任务全部执行完毕**后才触发一次，不是每个任务执行后都触发。

---

## 📝 任务时间工具（time.py）

`ZmxyOL/task/time.py` 提供了便捷的时间计算函数，用于设置 `next_exec_time`：

| 函数 | 说明 | 示例返回 |
|------|------|---------|
| `next_day(5, 0)` | 下一个 05:00 时间戳 | 明天 05:00 |
| `next_week(5, 0)` | 下一个 7 天后 05:00 | 7 天后 05:00 |
| `next_Mon(5, 0)` | 下一个周一 05:00 | 最近的周一 05:00 |
| `next_month(5, 0)` | 下一个月 05:00 | 下月同日 05:00 |

所有函数都支持传入 `now` 参数（datetime/时间戳/None）。

---

## 🔄 完整生命周期

```
程序启动
  ↓
导入任务 → @register_task 注册到 cfg["tasks"]
  ↓
CLI 主菜单显示 → 用户按 R
  ↓
scheduler.activate() → 状态: RUNNING → 后台线程启动
  ↓
_loop(): 计算最近到期任务时间 → sleep
  ↓
到期 / 被 wake() 唤醒
  ↓
_check_and_run():
  ├── 启动模拟器（如果未运行）
  ├── while 有到期任务:
  │     ├── execute_tasks([任务A])
  │     │     ├── set_current_task("任务A")  ← 日志显示任务名
  │     │     ├── fn(**params)               ← 执行任务函数
  │     │     ├── set_current_task(None)     ← 恢复日志格式
  │     │     └── _update_task_post_execution()  ← 更新 next_exec_time
  │     ├── cfg.save_config()
  │     ├── task_manager.reload_tasks()
  │     └── 重新扫描到期任务
  └── _post_execution_action()  ← 关闭模拟器等
  ↓
回到 _loop() → 继续等待下一个到期任务
```

---

## ⚠️ 注意事项

### 1. 模拟器启动

调度器会自动启动模拟器（如果未运行），但需要：
- ✅ 配置正确的 `emulator.emu_path` 和 `emulator.adb_path`
- ✅ 模拟器安装路径正确
- ✅ ADB 连接正常

### 2. 错误处理

- ✅ 单次任务失败不会停止调度器
- ✅ 连续失败 3 次才会进入错误状态
- ✅ `TaskRequireReTry` 异常会按 `max_retry` 重试，不计入连续失败
- ✅ `RequestHumanTakeover` 异常会跳过任务但仍更新其配置

### 3. 并发安全

- 任务配置读写受 `RLock` 保护
- 调度器后台线程通过 `_wake` + `_stop` 两个 Event 控制
- `set_current_task()` 使用 `threading.local()`，线程安全

### 4. 资源消耗

调度器设计为**极低开销**：
- ✅ 绝大部分时间在 `Event.wait()`，几乎不消耗 CPU
- ✅ 只在检查/唤醒时才扫描任务配置
- ✅ 不会影响系统性能

---

## 🔍 故障排查

### 问题：调度器不自动执行任务

**检查清单**：
1. ✅ 状态是否为"运行中"（🟡）？
2. ✅ 任务是否已开启（`on=True`）？
3. ✅ 任务的 `next_exec_time` 是否已到期（<= 当前时间戳）？
4. ✅ 查看日志中是否有 "📅 发现 N 个到期任务" 记录

### 问题：按 T 重载后调度器没有立即执行

**可能原因**：
- 调度器状态不是 RUNNING
- 任务的 `next_exec_time` 仍在未来

**排查**：查看日志中 `_get_wait_interval` 返回的等待时间

### 问题：调度器进入错误状态

**可能原因**：
- 连续 3 次任务执行失败
- 模拟器启动失败
- ADB 连接问题

**解决方法**：
1. 检查日志，找出失败原因
2. 修复问题后，选择【开始执行 R】恢复

### 问题：日志没有显示任务名称

**检查**：
- `setup_task_aware_logging()` 是否在启动时被调用
- `set_current_task()` 是否在 `execute_tasks()` 中正确设置/清除

---

## 📚 相关文档

- [性能优化模块（perf）](./perf.md) - 性能优化机制
- [API 参考](../API.md) - 完整的 API 文档

---

## 🎯 总结

新版调度器的核心改进：

| 特性 | 旧版 | 新版 |
|------|------|------|
| 等待策略 | 固定 1 小时 | 动态计算，精确到秒 |
| 执行方式 | 批量执行所有到期任务 | 逐个执行，每个任务后 save+reload |
| 外部唤醒 | 不支持 | `wake()` 立即中断等待 |
| 日志标识 | `module:lineno` | 任务中文名 + `module:lineno` |
| 配置同步 | 执行完统一保存 | 每个任务后立即保存并重载 |

**核心价值**：
- ✅ **精准**：不多等一秒，到期即执行
- ✅ **可靠**：逐个执行 + 实时保存，中断恢复无损
- ✅ **可观测**：日志清晰显示当前执行的任务
- ✅ **响应快**：配置变更后立即生效
