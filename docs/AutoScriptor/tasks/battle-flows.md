# 战斗职业与 Flow 维护说明

当前战斗配招不再使用旧 `ZmxyOL/assets/profiles/*.yaml` 作为运行主线。`get_profiles_dir()` 仍保留兼容说明，但职业逻辑应维护在 `data/battle_character/`。

## 当前结构

| 位置 | 职责 |
|------|------|
| [`data/battle_character/hero.py`](../../../data/battle_character/hero.py) | 运行态 `Hero` 基类、`battle_loop` 外壳、职业注册表、`@flow`、`battle_plan` 接入 |
| [`data/battle_character/liuli.py`](../../../data/battle_character/liuli.py) | 示例职业脚本；通过 `profession = "琉离"` 注册 |
| [`AutoScriptor/battle_character/hero.py`](../../../AutoScriptor/battle_character/hero.py) | 兼容入口，加载 `data/battle_character/hero.py` |
| [`AutoScriptor/battle_character/plan.py`](../../../AutoScriptor/battle_character/plan.py) | `BattlePlan` DSL：`first`、`at`、`every`、`combo` |
| [`ZmxyOL/battle/character/hero.py`](../../../ZmxyOL/battle/character/hero.py) | 历史导入兼容入口 |
| [`ZmxyOL/task/battle_task_params.py`](../../../ZmxyOL/task/battle_task_params.py) | 聚合职业与 flow，生成 `HeroProfession`、`BattleFlowName` |
| [`ZmxyOL/task/task_register.py`](../../../ZmxyOL/task/task_register.py) | 任务执行前加载当前职业，并注入 WebUI 选择的 `battle_flow` |

## 生命周期

1. 启动或导入任务参数时，`ensure_battle_heroes_loaded()` 扫描 `data/battle_character/*.py`，跳过 `hero.py`，执行职业脚本。
2. 职业类继承 `Hero` 并显式声明 `profession` 时，通过 `__init_subclass__` 写入 `_hero_registry`。
3. 类上 `battle_plan("流程名")` 或 `@flow("流程名")` 注册 flow；WebUI 的 `BattleFlowName` 由 `get_registered_flows()` 聚合。
4. 任务函数声明 `battle_flow: BattleFlowName` 时，`task_wrapper` 在任务体前调用 `get_battle_profile(h)`，按当前账号 `game.game_profession` 切换全局 `h` 的职业类。
5. `resolve_battle_flow_for_profile()` 只允许当前职业可解析的 flow 生效；否则忽略旧配置，回到任务默认 flow。
6. `battle_loop()` 解析 flow，初始化信号和内置触发器，然后循环执行 flow；`TRY_EXIT`、超时、取消、暂停和前进信号决定退出或跳转。
7. 热重载 `custom_task` 或 `battle_character` 时，scheduler 调用 `reload_battle_character_modules()`，清空注册表、恢复 `h` 为基类并重载职业脚本。

## 编写规则

- 新职业放在 `data/battle_character/<name>.py`，继承 `Hero`，显式写 `profession`。
- 普通循环优先用 `battle_plan()`，少写手动状态判断。
- 需要定制连招时，实现 `combo_xxx()`，再在 plan 中 `.combo("xxx")`。
- 需要职业默认战斗循环时，在类上定义 `default_battle_flow = battle_plan("战斗循环...")...`。
- 需要限制任务可见范围时，使用 `battle_plan("流程名", task="任务路径叶名")` 或 `@flow(..., task=...)`。
- `battle_weight` 目前只保留兼容并打印一次警告；新逻辑应使用明确的 `battle_flow`。
- 旧 YAML profile 和 `ZmxyOL/battle/skill/*` 不是当前实现入口；不要把新功能写回旧路径。

## 排障入口

- WebUI 下拉缺 flow：检查职业脚本是否在 `data/battle_character/`、是否声明 `profession`、是否被 `ensure_battle_heroes_loaded()` 成功导入。
- 选中的 flow 未执行：检查它是否属于当前职业；不属于时会被 `resolve_battle_flow_for_profile()` 忽略并记录 warning。
- `battle_loop` 超时：这表示业务未达成退出条件，不等于函数执行成功；应检查 flow 是否能触发 `TRY_EXIT` 或任务后续状态。
- 职业脚本更新后不生效：确认触发了 `custom_task`/`battle_character` reload，或重启服务。
