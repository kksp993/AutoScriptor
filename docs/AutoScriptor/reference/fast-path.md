# Nemu快速路径

MixControl defaults to nemu input; capture always IPC. Input failure logs error, falls back to ADB for this run; switch_to_nemu re-arms. Portrait720x1280 input is unreliable: whole login uses ADB proxy, finally restores prior mode.

Two locks: `NemuIpcImpl.io_lock` guards connection lifecycle/reused capture buffer; `NemuIpc._ipc_lock` serializes compound gestures only. Capture/input concurrent; no global/caller-held worker-capture lock. Raw BGRA views need copying across frames; public RGB owns arrays.

`screenshot_region(Box|xywh)` converts ROI only, rejects overflow. `finger_down/move/up/multi_finger_down` use IDs1..10; repeated down moves. Numbered contacts are independent from legacy click/swipe. Use ROI color/scanlines, not full-frame OCR; send edges only; cancellation/loss/timeout must `release_all_fingers()` in finally.

`replay`: timestamped down/move/up, normalized coordinates, executed count; absolute timing/speed/windows. Reject orientation mismatch/invalid IDs; remap recording slots, never clamp/modulo. Abort releases replay-owned contacts only. External conversion handles mmor. Contract: `test/runtime/test_replay_events.py`.

Historical2026-09-29, MuMu5.30.1.3586/1280x720: p50 full/ROI3.07/2.35ms, down+up0.23ms;30Hz simple detection3.2ms/iteration, effective29.3Hz, not game-response promises. Evidence: `logs/fastpath_online_20260929/`; `test/device/test_nemu_ipc_concurrency.py`. Keepalive display changes currently require human handling. No host power/keepalive/priorities/affinity performance fallback; optimize sampling/locks, not beyond fresh-frame rate.
