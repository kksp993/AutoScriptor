# 脚本编写安全约定

这份文档记录任务脚本、后台监听和战斗 flow 的推荐写法。目标不是限制已有脚本，而是给后续扩展一个更稳的默认姿势。

## 后台监听

优先使用 `bg.scope()` 注册任务局部后台回调。作用域退出时只会清理自己注册的回调，即使任务异常、同名回调被替换，也不会误删别人的监听。

```python
from AutoScriptor import *

with bg.scope("team") as watch:
    watch.add(
        "entered",
        I("加载中"),
        callback=lambda: bg.set_signal("组队进图", True),
    )

    bg.set_signal("组队进图", False)
    bg.wait_signal("组队进图", timeout=60)
```

推荐使用 `BG_SIGNALS` 代替手写内置信号字符串：

```python
from AutoScriptor import BG_SIGNALS

bg.set_signal(BG_SIGNALS.TRY_EXIT, True)
bg.set_signal(BG_SIGNALS.PAUSE_BATTLE, False)
```

只有在确实要终止当前任务所有后台监听时才用 `bg.clear()`。任务局部逻辑不要随手 `clear()`，否则容易清掉 `battle_loop` 或其他模块刚注册的监听。

## 战斗 Flow

职业战斗逻辑尽量写成 `@flow`，任务脚本只选择 `battle_flow`，不要把连招细节塞进任务脚本。flow 内优先使用这些可读性较高的时间辅助：

```python
@flow("战斗循环146")
def default_battle_flow(self):
    if self.first_round():
        self.huashen(4)
    if self.at(50, fast=30):
        self.zhenwu()
    if self.every(60, fast=30):
        self.huashen()
    self.battle("146")
```

`battle_weight` 目前只是兼容旧任务参数，不参与战斗策略。需要调整战斗行为时，优先新增或选择 `battle_flow`。

