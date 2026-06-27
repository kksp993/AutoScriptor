# 战斗职业与 Flow 维护说明

当前战斗配招只使用 `data/battle_character/` 里的职业脚本；旧 `ZmxyOL/assets/profiles/*.yaml` 资源已移除。

## 当前结构

| 位置 | 职责 |
|------|------|
| [`data/battle_character/hero.py`](../../../data/battle_character/hero.py) | 运行态 `Hero` 基类、`battle_loop` 外壳、职业注册表、`@flow`、`battle_plan` 接入 |
| [`data/battle_character/liuli.py`](../../../data/battle_character/liuli.py) | 示例职业脚本；通过 `profession = "琉离"` 注册 |
| [`AutoScriptor/battle_character/hero.py`](../../../AutoScriptor/battle_character/hero.py) | 兼容入口，加载 `data/battle_character/hero.py` |
| [`AutoScriptor/battle_character/plan.py`](../../../AutoScriptor/battle_character/plan.py) | `BattlePlan` DSL：`first`、`at`、`every`、`combo` |
| [`ZmxyOL/task/battle_task_params.py`](../../../ZmxyOL/task/battle_task_params.py) | 聚合职业与 flow，生成 `HeroProfession`、`BattleFlowName` |
| [`ZmxyOL/task/task_register.py`](../../../ZmxyOL/task/task_register.py) | 任务执行前加载当前职业，并注入 WebUI 选择的 `battle_flow` |

## 生命周期

1. 启动或导入任务参数时，`ensure_battle_heroes_loaded()` 扫描 `data/battle_character/*.py`，跳过 `hero.py`，执行职业脚本。
2. 职业类继承 `Hero` 并显式声明 `profession` 时，通过 `__init_subclass__` 写入 `_hero_registry`。
3. 类上 `battle_plan("流程名")` 或 `@flow("流程名")` 注册 flow；WebUI 的 `BattleFlowName` 由 `get_registered_flows()` 聚合。
4. 任务函数声明 `battle_flow: BattleFlowName` 时，`task_wrapper` 在任务体前调用 `get_battle_profile(h)`，按当前账号 `game.game_profession` 切换全局 `h` 的职业类。
5. `resolve_battle_flow_for_profile()` 只允许当前职业可解析的 flow 生效；配置了其他职业的 flow 会回到任务默认 flow，避免借用错误职业的流程。
6. `battle_loop()` 解析 flow，初始化信号和内置触发器，然后循环执行 flow；`TRY_EXIT`、超时、取消、暂停和前进信号决定退出或跳转。
7. 热重载 `custom_task` 或 `battle_character` 时，scheduler 调用 `reload_battle_character_modules()`，清空注册表、恢复 `h` 为基类并重载职业脚本。

## 编写规则

- 新职业放在 `data/battle_character/<name>.py`，继承 `Hero`，显式写 `profession`。
- 普通循环优先用 `battle_plan()`，少写手动状态判断。
- 需要定制连招时，实现 `combo_xxx()`，再在 plan 中 `.combo("xxx")`。
- 需要职业默认战斗循环时，在类上定义 `default_battle_flow = battle_plan("战斗循环...")...`。
- 需要限制任务可见范围时，使用 `battle_plan("流程名", task="任务路径叶名")` 或 `@flow(..., task=...)`。
- 使用明确的 `battle_flow` 选择战斗流程；所选 flow 只有属于当前角色 `game.game_profession` 对应职业脚本时才会生效，不要再传旧 `battle_weight` 参数。
- 当前角色 `game.game_profession` 找不到同名 `profession` 注册时，会使用 `default` 职业，这是保留的业务默认。
- 全局默认 `战斗循环` / `竞技场循环` 必须由已注册职业提供；缺失会在任务参数导入时直接报错。
- 天庭组队 `heaven_battle()` 中，`抽牌` 可见等同于战斗循环完成。bg 回调只置位 `Pause_battle`/`try_exit`，退出移动和抽牌收尾必须在 `battle_loop()` 返回后的主线程顺序执行，避免 bg callback 异常阻断退出信号。
- `way_to_exit(until=...)` 使用 bg 监听出口迹象，主线程按“到最右侧 → 快速左移到出口附近 → 先确认是否已踩中 → 小步左移搜索 → 看到迹象后原地驻留 → 未出去再向右微调”的节奏移动。3 倍速搜索步长更小、驻留更短；1 倍速按实际约 2 倍速处理。不要在这里重新加入私有检测线程、`fast_until`、OCR 节流或 list/AND 特判。
- 极寒深渊、洪荒遗境这类会触发“混沌先锋”的新 boss 任务，通过 `battle_task(check_pioneer=True)` 打开通用收尾处理。流程必须先按原关卡逻辑正常返回地图并看到“回家”，再开 4 秒短窗口检测 `T("混沌先锋", box=Box(608,494,112,47).margin())`；若短窗口内直接出现“加载中”也按自动进入处理。命中后等待加载消失，额外打一场单倍 `crash_suddenly` 先锋本，返回地图后结束；先锋本不再递归检测先锋。
- 旧 YAML profile 和 `ZmxyOL/battle/skill/*` 不是当前实现入口；不要把新功能写回旧路径。

## 排障入口

- WebUI 下拉缺 flow：检查职业脚本是否在 `data/battle_character/`、是否声明 `profession`、是否被 `ensure_battle_heroes_loaded()` 成功导入。
- 选中的 flow 未执行：检查它是否属于当前职业；不属于时会回到任务默认 flow。
- `battle_loop` 超时：这表示业务未达成退出条件，不等于函数执行成功；应检查 flow 是否能触发 `TRY_EXIT` 或任务后续状态。
- 职业脚本更新后不生效：确认触发了 `custom_task`/`battle_character` reload，或重启服务。
