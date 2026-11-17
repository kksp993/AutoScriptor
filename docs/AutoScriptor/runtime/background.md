# 后台监听

BackgroundProxy lazy, default1s; bg.interval(0.1) for sensitive detection. Shared fresh frame/batch locate; all throttled skips capture. Capture/recognition failures: history/rate-limited warnings, monitor survives; history50.

bg.add(name,identifier,callback): name replaces; Target/sequence, zero-argument callback, once=True, throttle minimum gap; ordinary priority descending. allow_concurrent=False default; enabled scans first/continues through BG-Concurrent during ordinary callbacks; independent popups only, not shared-state/map flows. Waits/callbacks cancellable.

bg.scope removes owned registrations only; expected_info protects replacements. No casual global clear. protect_clear ignores/records external clears; callback threads may clear, force=True emergency only.

Task-state callbacks require captured task_path; execution-thread context is not inherited. [Example](../tasks/battle-flows.md).

Use BG_SIGNALS: TRY_EXIT=try_exit, PAUSE_BATTLE=Pause_battle, BUILTIN_ADVANCE=_builtin_advance, FAILED=Failed (lowercase failed alias only), EXIT=Exit legacy. set_signal/signal/wait_signal thread-safe, aliases normalized; specify wait timeout.

battle_loop resets exit/pause/advance, scopes _builtin_advance/_builtin_bao; protected clear, low-priority advance behind popups. TRY_EXIT/timeout/cancel/error terminate. [Battle](../tasks/battle-flows.md).

Inspect archive bg_event_history/bg_active_callbacks/bg_signals; recognition warnings suggest device/IPC/OCR/targets, not merely timeout. [Lifecycle](lifecycle.md) owns reload clearing.
