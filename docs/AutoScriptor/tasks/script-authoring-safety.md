# 脚本安全

Use AutoScriptor.sleep, never time.sleep. Local [bg.scope](../runtime/background.md), ordinary stateful callbacks, BG_SIGNALS; propagate TaskCancelled. No main wrappers, blanket catches, traceback/exit/bg.stop templates or registered placeholders. [Debug/progress](../schedule/scheduler.md).

OCR None≠zero. After input observe target/region/value change, not merely nonempty text. Cache fingerprints complete images. Extraction text/img/both preserves shape; postprocessors retry then None. Fixed-frame checks pass screenshot; no RecognitionResult dependency.

Game coordinates: absolute 1280×720, B=left/top/width/height; mismatch warns, never resizes. Portrait uses native regions/ADB, finally restores mode. init defaults launch_app=False; pass instance/address without cfg mutation. [Session](../runtime/lifecycle.md).

Realtime ROI screenshot_region, edge-triggered fingers 1..10 independent of click/swipe; finally release_all_fingers. No full-frame OCR polling.

try_close_via_x: modal first, alternate actual X candidates, re-recognize each click; 20-click budget (last success valid), loading 30s, cancellable. Exhaustion raises into archive/recovery, never unlimited restart.

Grid: snap name centers to measured column boundaries, not offsets; wide numeric boxes, image/color price-state buttons versus text names. Scan during swipe_precise, step below actionable band (120px/26 scans baseline); purchases may reset scroll.

Mail one-shot/debug/off: village → claim; claim_interval=3s, timeout=600s. Exact 1/1, five extra claims/reconfirm; changed/missing page resets count, never 1/10; timeout raises. 天道树 daily/world-map/off: verify tier10 (1/5/10), confirm twice/dialog disappears, close two panels/return village; failures propagate, no unapproved consumption.

Persist through cfg/lifecycle/task-state, not account JSON or fn/order/param_meta/_due. Keep personal workflows, identities and site data out of shared source and examples.
