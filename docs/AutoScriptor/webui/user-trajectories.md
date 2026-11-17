# 验收轨迹

Offline checks != business success; spending/QQ requires approval.

- Await init-status before config; snapshot stays device-free. Character status isolated; queues deduplicated/persisted.
- Saves strip projections/params_doc, retain debug/reschedule; reject unknown/cyclic dependencies. Graph stacking preserves constraints; search/layout never persist. FIFO isolates characters/drafts. Labels follow current task metadata, never stale previous-task labels.
- task_list skips relogin, not declared entry navigation; dispatch/redemption verify login. Manual idle only, busy=409. Shared stopDispatch; cancellation≠failure.
- Settings: aligned connection/runtime cards; fold paths/performance/access/diagnostics. Autosave validates ADB, preserves addresses, pauses busy; no refresh loops. QQ/deploy save independently; diagnostics mounts on expansion.
- Embedded QQ: aligned cards, folded advanced/history, no preview/sidebar. Tutorial preserves drafts; skip/replay/narrow-screen safe. Sync confirms discard, never login. Confirm switching/identity before tests; no passwords/session. [Offline tests](../../../test/webui/test_qq_login_interface.py) aren't delivery proof.

## Editor 安全合同

Import/cached recognition/preview are device-free; simulation uses virtual mixctrl, real actions require unlock/shared gate. Click/preview/save use native coordinates; non1280x720 T/I retain `.margin(frame_size=(width, height))`.

preview-extract post_process: only strip/pretext/posttext/prenum/postnum, never expressions; integer 0 valid, failures never fabricate 0. execute-code restricts builtins/imports/dangerous AST, exposes h/navigation APIs, is not a security sandbox; stop via execute-code/stop.

save-custom-task: traversal validation, atomic save/full reload. Required ensure_in/ANYWHERE; static checks never execute. Wrapper navigates, generated bodies don't. None/mixed/unimported ANYWHERE rejected before writes. Parameter descriptions generate params_doc.

Playback: serial captures, 500ms after responses, no per-frame OCR; pause retains settled frame. Import/unmount cancels; errors stop visibly. Real completion recaptures after 1.5s; virtual/rejected/transport-failed runs never do. Imports invalidate delayed captures.

Tutorial: seven optional local steps; shared Canvas/Menu, simulated recognition/execution/save. No device/Python/draft changes. Entry pauses preview; exit never resumes; busy blocks entry. Skip/replay/close/unmount cancel timers; narrow navigation remains usable. [Tests](../../../test/webui/test_editor_tutorial.py),[editor](../../../test/webui/),[routes](../../../backend/webui/routes/editor.py).

Editor: Tab=4 spaces, Shift-Tab=outdent; double-click edits functions. Selected-region `ui_T()` reuses click's T/I/B. Verify scrolling inside background menus, character skills and right-side buttons.

API docs: sidebar/editor-dialog, example-first; search/filter/copy, folded source. No execution/draft changes. Entry pauses preview; abort stale/unmounted requests; visible auth/network/schema failures. [Tests](../../../test/webui/test_api_docs_interface.py).

News forces entry refresh; redemption iframe load refreshes, mask blocks stale-table interaction, pages use no-store. Official incremental collection: last 10 days/15 posts. Redemption switches identity/forces login. Proxy retries login wall once; 202/429 never cache success or retry login. Only public plaintext exception: news 85rwm3janyyc/123456; other credentials remain sensitive and proxy access requires unlock.
