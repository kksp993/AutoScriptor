# Background Monitor 当前基线

`AutoScriptor.core.background` 提供任务运行期后台监听、信号和作用域清理。它用于弹窗处理、战斗退出信号、内置前进检测等场景。

## 当前实现要点

| 机制 | 当前行为 |
|------|----------|
| 实例 | `bg` 是懒加载 `BackgroundProxy`，首次访问时创建 `BackgroundMonitor` 线程 |
| 默认间隔 | `DEFAULT_INTERVAL = 1.0` 秒 |
| 临时加速 | 延迟敏感流程可用 `bg.interval(...)` 临时降低轮询间隔，例如天庭组队战斗结束/抽牌检测使用 `bg.interval(0.2)` |
| 截图策略 | 主循环每轮尽量共享一张截图，批量 `_locate_all()`，避免每个回调单独截图 |
| throttle | 全部回调都在冷却内时不截图，直接等待 |
| 普通回调 | `allow_concurrent=False`，按 `priority` 从高到低扫描 |
| 并发回调 | `allow_concurrent=True`，优先扫描；普通回调执行期间会由 `BG-Concurrent` 子线程继续扫描 |
| 事件历史 | `get_event_history()` 返回最近 50 条回调、信号、clear 记录 |
| 运行期异常 | 截图或识别异常会写入事件历史并限频 warning；监控线程继续运行 |
| 信号 | `set_signal()` / `signal()` / `wait_signal()` 线程安全 |

## 注册与清理

```python
from AutoScriptor import bg, T, click

bg.add(
    "global:known",
    T("知道了"),
    callback=lambda: click(T("知道了"), if_exist=True),
    once=False,
    throttle=1.0,
    allow_concurrent=True,
)

bg.remove("global:known")
```

`bg.add()` 参数：

| 参数 | 说明 |
|------|------|
| `name` | 唯一名称；重复名称会替换旧回调 |
| `identifier` | `Target` 或 `Target` 序列 |
| `callback` | 命中后执行的无参函数 |
| `once` | 默认 `True`，触发后自动移除 |
| `throttle` | 同一回调两次触发的最小间隔 |
| `allow_concurrent` | 是否在普通回调执行期间也允许触发 |
| `priority` | 仅普通回调有效；越大越先扫描 |

## 推荐作用域

任务局部监听优先用 `bg.scope()`，不要靠任务尾部手写一串 `remove()`。

```python
from AutoScriptor import bg, BG_SIGNALS, T

with bg.scope("battle") as watch:
    watch.add(
        "finish",
        T("站在这里"),
        callback=lambda: bg.set_signal(BG_SIGNALS.TRY_EXIT, True),
        once=True,
    )
    bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
    ...
```

作用域退出时只清理由本作用域注册的回调。若同名回调已经被其他代码替换，`expected_info` 会阻止误删。

## clear 保护

`bg.clear()` 会清空全部回调，容易误删 `battle_loop` 内置监听。战斗外壳使用 `bg.protect_clear()` 保护关键区：

- 外部线程调用 `bg.clear()` 会被忽略并记录事件。
- bg 自己的回调线程仍可清理，避免必要的内部收尾被挡住。
- 需要强制清空时可 `bg.clear(force=True)`，但任务脚本通常不应这样做。

## 内置信号

优先用 `BG_SIGNALS`，避免手写大小写不一致的字符串：

| 常量 | 值 | 用途 |
|------|----|------|
| `TRY_EXIT` | `try_exit` | 战斗循环退出 |
| `PAUSE_BATTLE` | `Pause_battle` | 暂停战斗循环 |
| `BUILTIN_ADVANCE` | `_builtin_advance` | 内置“前进”检测 |
| `FAILED` | `failed` | 失败信号 |
| `EXIT` | `Exit` | 历史退出信号 |

```python
bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
bg.wait_signal(BG_SIGNALS.TRY_EXIT, True, timeout=60)
```

## battle_loop 交互

`data/battle_character/hero.py` 的 `battle_loop()` 会：

1. 重置 `TRY_EXIT`、`PAUSE_BATTLE`、`BUILTIN_ADVANCE`。
2. 进入 `bg.protect_clear()`。
3. 用 `bg.scope()` 注册 `_builtin_advance` 和 `_builtin_bao`。
4. 循环执行当前 flow，直到 `TRY_EXIT`、超时、取消或异常。

内置 `_builtin_advance` 使用 `BG_PRIORITY_BUILTIN_ADVANCE` 低优先级，避免同一帧里先于任务自定义弹窗回调触发。

## 编写建议

- 弹窗、确认按钮、爆字等不依赖主流程顺序的监听可以设 `allow_concurrent=True`。
- 会修改共享状态、切换地图或执行长流程的监听保持普通回调，并设置清晰的 `priority`。
- 回调中仍应使用 `AutoScriptor.sleep()` / `click()`，保持可取消。
- 不要在局部任务中随手 `bg.clear()`；用 `bg.scope()` 表达生命周期。
- 排查时先看错误归档里的 `bg_event_history`、`bg_active_callbacks`、`bg_signals`；若出现 `bg截图异常`、`bg常规识别异常` 或 `bg并发识别异常`，优先检查设备会话、NemuIpc、OCR/目标数据，而不是只看任务超时。
