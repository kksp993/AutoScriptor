# 战斗职业与 Flow

[Hero](../../../data/character/hero.py): h/registry/loop/flows; [plan](../../../ZmxyOL/character/plan.py): first/at/every/combo. data/character registers subclasses. Unknown profession=default; missing global 战斗循环/竞技场循环 fails import. YAML/old skills/battle_weight obsolete.

Prefer default_battle_flow=battle_plan/combo_xxx; @flow exceptional. task= restricts leaves. [Parameters](../../../tasks/battle_task_params.py) aggregate flows. BattleFlowName resolves by game.game_profession, incompatible=task default; sets h.task_context_battle_flow. battle_loop/jjc_battle inherit unless flow_name explicit. Reload registry/h in-place: [contract](../runtime/lifecycle.md).

WebUI: one `自动战斗中...` per battle_loop/Yuxu loop; nested details backend-only. Advance/way_to_exit/warnings/errors visible. [Tests](../../../test/webui/test_battle_log_summary.py).

## 退出与监控

battle_loop resets exit/pause/advance, protects clear/scopes built-ins; exit/timeout/cancel/error terminate, pause/advance alter flow. Timeout≠success. Use [BG_SIGNALS](../runtime/background.md).

way_to_exit: bg watches; main moves rightmost → left near exit → registers 战斗-离开标记 → left pulses → holds at 秒 → right adjustment. mumu long-press, nemu after each move. 还有/秒 indicate position, until requires loading/home/cards. No private threads/fast_until/OCR throttling/AND special cases. hero.speed_x controls distance; forced 1× scenes set speed_x=1, finally restore.

Heaven bg.interval(0.1) gets fresh frames; 抽牌 ends battle. Callback sets PAUSE_BATTLE/TRY_EXIT, failure adds FAILED. Main thread handles exit/cards/revive/retry afterwards. exit_after_battle=False returns FAILED, never recursive retries.

Recovery: shared map/reentry → next round; failed round consumed ticket/progress. Main owns index; callbacks flag failure/exit, propagate TaskCancelled. Bound recovery, reset try_exit/hidden, exhaustion raises.

Kunlun: `yuxu_ticket_consumed=True` after Yuxu detection; reentry preserves, daily 05:00 expires. Ignore undated legacy flag. One-shot callback captures task_path. [Tests](../../../test/performance/test_kunlunshan_yxd_speed.py).

## 混沌先锋

`battle_task(check_pioneer=True)` opts in; per-row `fight_pioneer` controls shared challenge/exit. After normal return + 回家, detect 4s at `T("混沌先锋", box=Box(608,494,112,47).margin())`; 加载中=automatic entry. Cleanup resets pioneer_seen; no recursion/source-dungeon names/reverse inference/mutable global context.
