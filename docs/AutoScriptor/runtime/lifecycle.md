# Runtime Lifecycle

## 启动与设备会话

RuntimeContext owns mixctrl/mumu/bg. Startup/polling/diagnostics device-free; ready=context/config/tasks. Electron loading/logs before checks: UTF-8, unchanged codepage, project-only cleanup, visible failures. Before app.whenReady: software default, optional d3d11/default. AUTOSCRIPTOR_PORT=5000; launcher selects/backend binds. OCR device/models frozen until restart; worker builds models, lazy Mumu GUI. Electron GPU independent.

ensure_device_session lazy; refresh releases/rebuilds; shutdown clears. init defaults launch_app=False; emulator_index=0/adb_addr bind without cfg mutation. Validate local host, instances 0..31, Manager identity/address (recheck after launch), ADB device/sys.boot_completed=1, read-only IPC frame before publishing/App launch. Failure/cancel releases IPC; no test clicks/instance fallback. Launch/process alive≠ready; explicit MuMuStartupError preserves context, no repeated launch/repair/Hyper-V changes. TCP disconnect/connect heals offline; IPC≠ADB readiness.

nemu default; IPC failure visibly switches to ADB; switch_to_nemu re-arms. Portrait/login ADB, finally restore; HZ4399 ends after submission (700ms hold), game clients select characters. io_lock=connection/capture buffer; _ipc_lock=compound gestures, capture/input concurrent. DLL discovery=mumu_discovery; frame mismatch warns/no resize. No raw IPC.

## 恢复与每日重启

restart_on_error: close/relaunch → ADB restart; three non-running recoveries → release_session → power.restart → refresh(launch_app=False) → launch. Cooldown 10min, success resets, independent attempts.

Daily: first normal execution after local 05:00 closes MuMu; refresh restarts/invalidates login. Global `runtime_state.daily_restart_day`: ISO date saved before attempt; save failure=rollback/no shutdown. Shutdown failure consumes attempt; recovery independent. Survives process/reload/character/reset; debug/list skip, not entry navigation.

## 执行与数据边界

Single gate: scheduler/direct/Editor/remote/[ascli](../reference/ascli.md). running≠occupied; manual nonblocking 409 runtime_busy, scheduler blocks/rechecks. guard_idle protects mutations. Stop cancels/invalidates login/resets error/retry budgets; recovery retains exhaustion. Cancellation lasts until worker exit; ignore subsequent failures. CLI cleans before gate release; interrupted runs never replay. Lightweight responses/background snapshots.

Global=data/config.json; character tasks/status/profession=account JSON→cfg. Ordering=IDs, status tasks/task_cycles=paths; preserve deadlines/filter expired status. Strip runtime/secrets. Atomic same-directory replace, no fallback; AUTOSCRIPTOR_STRICT_FSYNC=1 opt-in. Global saves exclude accounts. Transactions: save/projection/version/wake. Frontend frozen FIFO; preserve drafts/accept newer versions after saves. Assets=data/assets, caches=logs, never docs.

## 热重载

Watch config/account/custom_task/character/ZmxyOL Python/UI map; internal saves rebaseline JSON, not scripts. Busy: preserve credentials/defer rebuild. Sync preserves bg/registry; light reload clears bg/projections; full rebuilds scripts/game/exports/characters/registry/UI cache, bg last. Reload idle; character switching lightweight. Import failure skips prune/save; empty registry never prunes data.

Preserve registry/task_params/state/time/TableParam/accounts/profession/Hero/plan/h identities; rebuild tasks/battle_task_params, characters in-place. [Contract](../../../test/task_domain/test_task_reload_contract.py), [catalog](../../../orchestrator/catalog.py).
