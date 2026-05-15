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

职业战斗逻辑尽量声明成 `battle_plan`，任务脚本只选择 `battle_flow`，不要把连招细节塞进任务脚本。推荐把 flow 写成类属性，这样“什么时候做什么”一眼能读懂：

```python
from AutoScriptor.battle_character import Hero, battle_plan


class LiuLi(Hero):
    profession = "琉离"

    default_battle_flow = battle_plan("战斗循环146") \
        .first("huashen", 4) \
        .at(50, "zhenwu", fast=30) \
        .at(60, "huashen_long", 1, fast=35) \
        .every(60, "huashen", fast=30) \
        .combo("146")
```

`profession` 必须显式写在职业子类上，且要和 WebUI 角色职业一致；未显式声明 `profession` 的辅助子类不会进入职业注册表，避免误覆盖 `default`。任务执行前会按当前账号角色的 `game.game_profession` 自动切换职业脚本，`battle_loop()` / `jjc_battle()` 在未显式传 `flow_name` 时会使用 WebUI 选择的 `battle_flow`。

需要非常特殊的逻辑时，旧的 `@flow` 函数仍然可用；但普通职业循环优先用 `battle_plan`，避免手写 `first_round/once_at/every` 状态判断。

`battle_weight` 目前只是兼容旧任务参数，不参与战斗策略。需要调整战斗行为时，优先新增或选择 `battle_flow`。
