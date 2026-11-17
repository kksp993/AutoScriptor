# Live screenshot checks

Read-only != task execution. [Emulator/tasks](../../.cursor/skills/autoscriptor-live-check/SKILL.md). Authorized tasks reuse functions/registered runs: inspect logs/screenshots/video, fix/rerun same entrypoint. Restore owned overrides using fresh state. Probes resolve evidence gaps, never clone workflows.

New flows use [ascli](../AutoScriptor/reference/ascli.md): plan start/transitions/end, submit one complete `.as`, inspect its run evidence, rerun the whole section. Isolated clicks never prove continuity. Registered tasks retain their executor; no replacement click scripts.

## Procedure

1. Check occupancy; backend owns the gate, no competing controller. Otherwise standalone: `runtime_ctx.ensure_device_session(reason=...,launch_app=False)` -> `(mixctrl,mumu)`; explicit `init(start_emulator=...,launch_app=...)`.
2. Venv, `-X utf8`; original BGR frames/probes/crops/overlays/JSON: `<logs-root>/<topic>_<timestamp>/` via `AutoScriptor.utils.paths`, never production code.
3. Record dimensions/`getFrameSize()`/Box xywh/crops; prove coordinates with overlays. No low-confidence irreversible actions.
4. Same frame: `locate/ui_T(...,screenshot=frame)`, `extract_info(...,screenshot_frame=frame)`, `ocr(frame,targets)`, `ocr_for_box(frame,box)`. OCR takes Box list/target; extraction preserves scalar/list/nested shape, unreadable=None. `mode="both"`: images then OCR. Batch, not per-box loops.
5. `perf_counter`: separate warm-up/capture/recognition/total. Report evidence/dimensions/boxes/grid/raw/missing/accuracy basis; distinguish coordinate/recognition/postprocessing failures. Respect implement-before-inspection.

## Transitions

Define page/target/template/timeout/interval/resource risk; timestamp/evaluate each frame. Stylized text: prefer templates; record text/confidence/blockers/pass-fail.

Timeout: classify navigation/state/coordinates/recognition/wait/lifecycle; keep timeline, fix/rerun identical specification, compare timings. Never reconstruct evidence.

Clicks/battles/purchases/item-use/sweeps/challenges/claims require explicit step approval. Input acceptance is not rendering/completion. Pause at ambiguity/manual consent; offline mocks are not live success.
