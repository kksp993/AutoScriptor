# 失败排查

先留证据，再修复复验。

- Await observable changes, not sleep/nonempty stale OCR. Wrap tuple-like Box in B; plain B always hits.
- Overlays swallow input: unique modal anchors, not generic confirm. Repeated App timeout needs bounded TaskManager MuMu recovery, not endless App/ADB retries; PageRouter/try_close_via_x.
- Actions aggregate per second; inspect action_history. Derived index/ADB values follow defaults only; preserve manual entries.
- Moving icons: full-frame templates, two separated validation frames. Ambiguous text needs ROI. Animated multi-matches: click_all freezes one frame; if_exist/assure_stable=False only deliberately; close dialogs between rounds.
- Portrait720x1280 IPC taps failed where ADB worked; whole login uses ADB proxy/finally restore. HZ4399 submit: same-point700ms swipe, not tap.
- Stale backend: inspect port5000 ownership; never kill unrelated processes. MuMu discovery owns DLL paths; emu_path=Manager, not Player.
- Asset roots: ui_manager.get_ui(), not stale ui. AutoScriptor.utils.paths, not cwd; check leaked AUTOSCRIPTOR_DATA_DIR.
- Tests isolate config/accounts/subprocess AUTOSCRIPTOR_DATA_DIR, including atexit. Freeze runner detection at app_config import; Paddle later imports unittest.

`Unknown predecessor`: check import failures/partial discovery before changing dependencies. [Regression](../../test/task_domain/test_task_catalog_loading.py). Restart backend after `ZmxyOL` export edits.

Logs identify source. Measured OCR/frame checks aren't live acceptance. Runtime fixes need smoke/[archives](operations/log-archiver.md). Test unregistered/deprecated tasks. No host power/priority/affinity workaround.
