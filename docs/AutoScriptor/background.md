# 后台监控系统（Background Monitor）

## 📖 概述

后台监控系统（`BackgroundMonitor`）是 AutoScriptor 的核心组件，用于在任务执行过程中**持续监控屏幕状态**，并在检测到特定 UI 元素时**自动触发回调函数**。

### 核心能力

- 🔍 **持续监控**：后台线程每 0.2 秒扫描一次屏幕，检测已注册的 UI 元素
- ⚡ **自动响应**：检测到目标元素时立即执行对应的回调函数
- 🔄 **并发支持**：支持 `allow_concurrent` 机制，允许某些 callback 在其他 callback 执行期间也能被触发
- 📡 **信号机制**：提供线程安全的信号传递功能，用于任务间通信

---

## 🚀 快速开始

### 基本用法

```python
from AutoScriptor import bg, T, click

# 注册一个监控事件：检测到"知道了"按钮时自动点击
bg.add(
    name="突发事件-知道了",
    identifier=T("知道了"),
    callback=lambda: click(T("知道了"), if_exist=True),
    once=False  # 持续监控，不自动移除
)
```

### 典型场景

1. **弹窗自动处理**：战斗过程中自动点击"知道了"、"取消"等弹窗
2. **突发事件响应**：检测到特殊事件（如"玉虚殿"）时自动执行特定逻辑
3. **状态监控**：持续监控游戏状态，触发相应的处理流程

---

## 📚 API 参考

### `bg.add(name, identifier, callback, once=True, throttle=0, allow_concurrent=False)`

注册一个后台监控事件。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 事件名称（唯一标识，用于后续 `remove()`） |
| `identifier` | `Target \| tuple[Target, ...]` | 要检测的 UI 元素（单个 Target 或元组） |
| `callback` | `Callable[[], None]` | 检测到元素时执行的回调函数 |
| `once` | `bool` | 是否只执行一次后自动移除（默认 `True`） |
| `throttle` | `float` | 防抖间隔（秒），同一事件两次触发的最小间隔（默认 `0`） |
| `allow_concurrent` | `bool` | 是否允许在其他 callback 执行期间也被触发（默认 `False`） |

**示例**：

```python
# 示例 1：一次性事件（执行后自动移除）
bg.add(
    name="战斗结束",
    identifier=T("站在这里"),
    callback=lambda: bg.set_signal("try_exit", True),
    once=True
)

# 示例 2：持续监控（不自动移除）
bg.add(
    name="突发事件",
    identifier=(T("知道了"), T("取消")),
    callback=lambda: click((T("知道了"), T("取消")), if_exist=True),
    once=False
)

# 示例 3：防抖（0.5 秒内最多触发一次）
bg.add(
    name="频繁弹窗",
    identifier=T("确认"),
    callback=lambda: click(T("确认")),
    throttle=0.5
)

# 示例 4：并发支持（即使其他 callback 正在执行也能触发）
bg.add(
    name="全局弹窗-知道了",
    identifier=T("知道了"),
    callback=lambda: click(T("知道了"), if_exist=True),
    allow_concurrent=True  # 关键：允许并发触发
)
```

### `bg.remove(name)`

移除指定的监控事件。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 要移除的事件名称 |

**示例**：

```python
bg.remove("突发事件")
```

### `bg.clear(clear_signals=False)`

清空所有监控事件。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `clear_signals` | `bool` | 是否同时清空所有信号（默认 `False`） |

**示例**：

```python
# 只清空监控事件
bg.clear()

# 清空监控事件和信号
bg.clear(clear_signals=True)
```

### `bg.set_signal(key, value)`

设置一个信号值（用于任务间通信）。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `key` | `str` | 信号键名 |
| `value` | `Any` | 信号值 |

**返回值**：设置的 `value`

**示例**：

```python
bg.set_signal("try_exit", True)
bg.set_signal("Pause_battle", False)
```

### `bg.signal(key, default=None)`

获取一个信号值。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `key` | `str` | 信号键名 |
| `default` | `Any` | 如果信号不存在，返回的默认值（默认 `None`） |

**返回值**：信号值，如果不存在则返回 `default`

**示例**：

```python
if bg.signal("try_exit", False):
    logger.info("检测到退出信号")
```

---

## 🔄 并发机制（allow_concurrent）

### 问题背景

默认情况下，`BackgroundMonitor` 是**单线程顺序执行**的：

```
主循环扫描 → 检测到"玉虚殿" → 执行 callback（可能耗时很长）
  ↓
  此时屏幕弹出"知道了"对话框
  ↓
  但主循环被阻塞在 callback 中，永远检测不到"知道了"
  ↓
  结果：卡死 ❌
```

### 解决方案

通过 `allow_concurrent=True` 标记某些 callback 为"并发安全"，系统会在常规 callback 执行期间启动**临时子线程**持续扫描这些并发 callback。

### 工作原理

```
常规 callback 开始执行（如"玉虚殿"）
  ├── 设置 _in_callback = True
  ├── 启动子线程 BG-Concurrent
  │     └── 持续扫描所有 allow_concurrent=True 的 callback
  │           └── 检测到"知道了" → 立即触发 ✅
  ├── 常规 callback 继续执行...
  └── 执行完毕 → _in_callback = False → 子线程自动退出
```

### 使用场景

**适用**：全局弹窗、紧急中断事件（如"知道了"、"取消"）

**不适用**：需要与主流程同步的事件、可能产生竞态条件的操作

### 示例

```python
# 昆仑山任务：玉虚殿 callback 执行期间，仍能响应"知道了"弹窗
bg.add(
    name="昆仑山-突发事件",
    identifier=(T("知道了"), T("取消")),
    callback=lambda: [
        logger.info("昆仑山突发事件"),
        sleep(0.03),
        click((T("知道了"), T("取消")), if_exist=True),
    ],
    once=False,
    allow_concurrent=True  # 关键：允许在玉虚殿 callback 执行期间触发
)

bg.add(
    name="昆仑山-玉虚殿",
    identifier=I("昆仑山-玉虚殿"),
    callback=kls_yxd_callback,  # 这是一个耗时很长的 callback
    once=False
    # 默认 allow_concurrent=False，不会干扰其他 callback
)
```

---

## ⚙️ 工作原理

### 主循环

```python
def run(self):
    while not self._stop_event.is_set():
        # 1. 扫描常规（非 allow_concurrent）的 callback
        for name, info in list(self._callbacks.items()):
            if info.get('allow_concurrent'):
                continue  # concurrent 的在下面统一处理
            
            if ui_T(info['idf']):  # 检测到目标元素
                # 执行常规 callback，同时启动子线程扫描 concurrent callback
                self._in_callback = True
                checker = Thread(target=self._concurrent_loop, daemon=True)
                checker.start()
                info['cb']()  # 执行 callback
                self._in_callback = False
                checker.join(timeout=2)
        
        # 2. 空闲时也扫描一轮 concurrent callback
        self._check_concurrent()
        time.sleep(self._interval)  # 默认 0.2 秒
```

### 并发扫描子线程

```python
def _concurrent_loop(self):
    """在常规 callback 执行期间，持续扫描 allow_concurrent 的 callback。"""
    while self._in_callback and not self._stop_event.is_set():
        self._check_concurrent()
        time.sleep(self._interval)
```

### 扫描间隔

默认扫描间隔为 **0.2 秒**（`DEFAULT_INTERVAL`），可通过 `bg.set_interval(interval)` 调整。

---

## 📝 完整示例

### 示例 1：昆仑山任务

```python
def kunlunshan_battle(num: int = 5):
    for _ in range(num):
        # 1. 注册"知道了"弹窗监控（并发安全）
        bg.add(
            name="昆仑山-突发事件",
            identifier=(T("知道了"), T("取消")),
            callback=lambda: [
                logger.info("昆仑山突发事件"),
                sleep(0.03),
                click((T("知道了"), T("取消")), if_exist=True),
            ],
            once=False,
            allow_concurrent=True  # 允许在玉虚殿 callback 执行期间触发
        )
        
        # 2. 注册"玉虚殿"监控（常规）
        if cfg.get("status.kunlunshan.has_YuxuDian_ticket", False):
            bg.add(
                name="昆仑山-玉虚殿",
                identifier=I("昆仑山-玉虚殿"),
                callback=kls_yxd_callback,  # 耗时很长的 callback
                once=False
            )
        
        # 3. 注册"战斗结束"监控（一次性）
        bg.add(
            name="昆仑山-战斗结束",
            identifier=T("站在这里"),
            callback=lambda: [
                bg.set_signal("try_exit", True)
            ],
            once=True
        )
        
        # 4. 执行战斗循环
        h.battle_loop(max_duration=1000)
        
        # 5. 清理监控事件
        for name in ("昆仑山-突发事件", "昆仑山-玉虚殿", "昆仑山-战斗结束"):
            bg.remove(name)
```

### 示例 2：信号通信

```python
# 任务 A：设置信号
bg.add(
    name="检测到退出条件",
    identifier=T("退出按钮"),
    callback=lambda: bg.set_signal("should_exit", True),
    once=True
)

# 任务 B：检查信号
def battle_loop():
    while True:
        if bg.signal("should_exit", False):
            logger.info("收到退出信号，停止战斗")
            break
        h.battle()
```

---

## ⚠️ 注意事项

### 1. 线程安全

- ✅ `bg.add()`、`bg.remove()`、`bg.clear()` 都是线程安全的（使用 `RLock`）
- ✅ 信号读写是线程安全的
- ⚠️ **callback 函数本身需要是线程安全的**（如果使用 `allow_concurrent=True`）

### 2. 性能考虑

- 扫描间隔默认 0.2 秒，平衡响应速度和 CPU 占用
- 每个 callback 都会调用 `ui_T()` 进行屏幕检测，避免在 callback 中执行耗时操作
- `throttle` 参数可以防止过于频繁的触发

### 3. 生命周期管理

- `once=True` 的事件执行后会自动移除
- `once=False` 的事件需要手动 `remove()` 或 `clear()`
- 建议在任务结束时清理所有相关监控事件，避免内存泄漏

### 4. allow_concurrent 使用建议

**何时使用**：
- ✅ 全局弹窗（"知道了"、"取消"等）
- ✅ 紧急中断事件
- ✅ 不影响主流程的辅助操作

**何时不用**：
- ❌ 需要与主流程严格同步的操作
- ❌ 可能产生竞态条件的操作
- ❌ 需要访问共享状态但未加锁的操作

### 5. 异常处理

所有 callback 的异常都会被捕获并记录，不会影响主循环：

```python
try:
    info['cb']()
except Exception:
    logger.exception('bg cb error %s', name)
```

---

## 🔍 故障排查

### 问题：callback 没有被触发

**检查清单**：
1. ✅ `identifier` 是否正确？使用 `ui_T(identifier)` 手动测试
2. ✅ `name` 是否唯一？重复的 `name` 会覆盖之前的注册
3. ✅ 是否在正确的时机注册？确保在需要监控的时间段内注册
4. ✅ `once=True` 的事件是否已经执行过一次？

### 问题：allow_concurrent 的 callback 没有被触发

**检查清单**：
1. ✅ 是否设置了 `allow_concurrent=True`？
2. ✅ 是否有常规 callback 正在执行？只有在常规 callback 执行期间才会启动并发扫描
3. ✅ 查看日志是否有 `bg concurrent cb error` 错误信息

### 问题：callback 执行太频繁

**解决方案**：使用 `throttle` 参数设置防抖间隔：

```python
bg.add(
    name="频繁事件",
    identifier=T("按钮"),
    callback=lambda: click(T("按钮")),
    throttle=1.0  # 1 秒内最多触发一次
)
```

---

## 📚 相关文档

- [API 参考](./API.md) - 完整的 API 文档
- [任务系统](./schedule/scheduler.md) - 任务定义与调度

---

## 🎯 总结

后台监控系统的核心价值：
- ✅ **自动化**：无需手动检查，自动响应 UI 变化
- ✅ **并发安全**：`allow_concurrent` 机制解决长时间 callback 阻塞问题
- ✅ **灵活配置**：支持一次性/持续监控、防抖、并发等多种模式
- ✅ **线程安全**：所有操作都有锁保护，可安全地在多线程环境中使用

**记住**：对于全局弹窗等需要"随时响应"的场景，使用 `allow_concurrent=True` 可以避免被其他长时间 callback 阻塞。
