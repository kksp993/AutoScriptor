# WebUI, Electron and news checklist

Read [API](../../AutoScriptor/webui/api-contract.md), [acceptance](../../AutoScriptor/webui/user-trajectories.md) and [installation](../../AutoScriptor/INSTALL.md).

## UI and saves

FastAPI/uvicorn; local Vue/Element Plus/Tailwind, no build/Jinja. `/api/refresh`, native `/ws/logs`, no SSE/Socket.IO. Components after dependencies/before app.js; app owns state, components emit. Battle summaries filter browser only, never diagnostic sinks; scopes restore on failure/cancel.

Strip credentials/runtime fields through shared projection/flattening, never duplicate `INJECTED_TASK_FIELDS`. Task/order/graph saves share snapshot-at-enqueue FIFO; ordering responses cannot overwrite tasks. Polling settles pending saves and refreshes only newer `config_version`.

Settings remain editable/persisted: validate before autosave; compare app/emulator/ocr/scheduler snapshots only at unchanged config_version. Server refresh rebaselines, not resaves; queue in-flight edits. Preserve explicit manual values over derived defaults except empty/placeholders/:0. Dynamic option/status failures are visible errors, not healthy empty values.

QQ: [contract](../../AutoScriptor/operations/qq-notifications.md); embedded in Settings, independent saves, aligned cards/tutorial. No admin credentials or readiness=login. Switching requires confirmation, idle/delivery exclusion, verified identity.

Task-list runs send `execution_source=task_list`; preserve graph queue order, skip cached character verification, never credentials/gate/retry/restart policies. All stop buttons share `stop-dispatch`: cooperative cancellation, pending scheduler and restored error/retry budgets; immediately apply lightweight response without blocking on full refresh.

Editor uses native coordinates; T/I preserve margin frame_size. Shared EditorMenuBar: teleported scrollable menus/live props. Navigation objects use `mm.locs[name].identifier`, excluding ANYWHERE. Saves generate declarations, not duplicate navigation. Input recaptures after 1.5s, not transition proof. Sequence clicks once through gate; virtual/until never injects extra input.

## Electron

Source .venv only; loading window precedes slow checks, with phase/port-cleanup logs. Resolve Electron via require('electron'); no npm Python bootstrap. Port defaults 5000, shifts if occupied, and matches backend. Render mode before app.whenReady(): software default, optional d3d11/default. Never change console codepage or host priorities. Package/About versions agree. Clean up only your debug processes; disclose leftovers. Source update has one Git channel; see installation.

## 4399

Prefer configured news credentials; absent legacy section uses public `85rwm3janyyc`/`123456`. Only this pair bypasses unlock; all others remain sensitive. Never expose credentials or use the public account for game automation. Force posts refresh on entry; retry a login-wall response once with fresh session. HTTP 202/429 is rejection even with cookies; safe escaped no-store error page, manual retry, no cached success.

Gift collection: official posts, last 10 days, maximum 15; checked_post_ids and active codes in logs/zmxy_redeem_codes.json. Dialog uses local gift_codes/page and refresh API. Redemption requires unlock/security key, selected server:character and forced login, accepting single/batched codes as one-time overrides for the built-in redeem task. See [routes](../../../backend/webui/routes/news.py).
