# 错误归档

get_error_archives_dir(): logs/errors. Archive exceptions, not takeover/retry/cancel; debug archives without recovery.

error.log: recent logs, traceback/locals, background events, action_history/recognition_trace. current_screenshot.png=failure; debug_screenshots=original frames, never reconstructed. Tracer stages; TaskManager applies debug override precedence; MixControl supplies frames. Normal success/cancel discards video.

task_video: <=180s finalized/decode-checked rolling segments. [ascli](../reference/ascli.md) retains all even on success/cancel; missing/broken=evidence failure. c/s/e/r=click/failure/extraction/routine. Throttling preserves actions; histories prove attempts, exclude credentials; summaries never rerun OCR/device work.

Startup: stage=device_startup, task/instance/ADB/Android cause; no probes/stale frames; image optional.

Terminal INFO/detail DEBUG; files rotate. WebUI deploy.log_level plus thread-local battle summaries: browser-only filtering, warnings/exceptions visible; files/action_history unchanged. Rich file:/// links; native persisted paths.

error-archives list/detail/file/DELETE/import: containment checks, zip imports into new directories, Shift-range selection.

上限/扩展见 [归档器](../../../AutoScriptor/logging/log_archiver.py)、[tracer](../../../AutoScriptor/logging/tracer.py)、[录屏](../../../AutoScriptor/logging/task_video_recorder.py)。
