# WebUI, Electron, And News Source Reference

Read this when changing WebUI, the source Electron shell, source update UI, or 4399 news routes.

## WebUI Architecture

- Backend: FastAPI + uvicorn.
- Logs: native WebSocket at `/ws/logs`, not Socket.IO.
- Frontend: Vue 3 + Element Plus + Tailwind from local static/vendor assets; no build step for `services/webui/static`.
- API routes use `/api/`.
- Frontend pulls config through `GET /api/refresh`; do not reintroduce Jinja config injection.
- Public config must strip sensitive fields such as encryption, account, password, and runtime-only task fields.
- Task save must strip runtime fields through `TaskTreeService.strip_runtime_fields()`; WebUI projections may inject fields such as `param_meta`, `param_keys`, `beta`, `custom`, `debug_mode`, `task_description`, `task_doc_flow`, `_due`, and `progress_display`.
- Task-list run actions must send `execution_source=task_list`; this preserves the current in-game login and skips character validation only for those direct runs. Do not spread this policy to scheduler, cross-character, default direct-run, or gift-code execution, and do not bypass credential unlock or runtime busy guards.
- Overview, scheduler, and task-list stop buttons must share `stop-dispatch` and `/api/stop`. Stopping preserves cooperative cancel until workers exit, but immediately restores scheduler `pending`, consecutive-error budget, and retry-exhaustion budget; post-cancel failures must not consume the restored budget.
- Component state is managed in `app.js`; components receive props and emit events upward.

Component convention:

1. Add component files under `services/webui/static/js/components/`.
2. Export as a global const, for example `const MyComponent = {...}`.
3. Load in `index.html` after dependencies and before `app.js`.
4. Register in `createApp({ components: ... })`.

## Source Electron Shell

- Desktop source entry is `scripts\run.bat electron` or root `start.bat`; direct `cd webapp; npm start` is only the low-level command after source dependencies are installed.
- `webapp/main.js` starts `services\webui\gui.py --electron` with the repo root as cwd and only uses the source `.venv`; if it is missing, run `scripts\install.bat python`.
- `webapp/preload.js` should expose only source runtime IPC needed by the shell.
- `webapp/package.json` should stay focused on `start`, `electron`, and runtime helpers actually used by the source shell. Python install/bootstrap belongs in `scripts\install.*`, not npm lifecycle hooks.
- `webapp/scripts/start-dev.cjs` should resolve the executable through Electron's package entry (`require('electron')`), not by hardcoding `node_modules/electron/dist/electron.exe`.
- Keep the loading window visible before slow backend checks, and keep startup phase logs useful for first-run diagnosis.
- Configure source Electron render mode before `app.whenReady()`. `AUTOSCRIPTOR_ELECTRON_RENDER_MODE` defaults to `software` to disable the fragile Windows GPU/Chromium paths; use `d3d11` to keep GPU with ANGLE D3D11, or `default` to compare the unmodified Electron behavior.
- Do not change the Windows console code page from Electron. Encoding is handled by Python UTF-8 flags/env.
- Port `5000` cleanup failures must be logged to startup logs and loading UI; do not hide them behind silent fallback.

## Version Coupling

- Electron package version comes from `webapp/package.json`.
- About panel display version in `services/webui/static/js/components/AboutPanel.js` should match it when the desktop-facing version changes.
- Version display changes are source metadata only on this branch; do not add distribution machinery just to bump a displayed version.

## Source Update Channel

- Source deployment Git updater uses `/api/update/*`.
- `GET /api/update/status` returns `kind: "source-git"` and disables itself outside a Git working tree or non-source runtime.
- `POST /api/update/check` fetches `origin main` once and compares `HEAD` with `origin/main`.
- `POST /api/update/run` requires runtime idle, refuses dirty worktrees, fetches `origin main`, pulls the current checked-out branch with `--ff-only origin main`, and triggers backend restart when available. Dependency changes are handled by `scripts\install.*`, not the updater.
- Detached HEAD is rejected, and Git stderr/timeout/start failures must be surfaced through `last_error`.
- The update panel must not show secondary desktop update choices.

## Runtime Data Facts

- Source runtime config is `data/config.json`.
- User account data is `data/accounts/*.json` and must not be committed.
- User scripts live in `data/custom_task/` and `data/battle_character/`.
- Runtime logs and error archives live under `logs/`.
- Gift-code JSON is read from `logs/zmxy_redeem_codes.json`; it is mutable runtime cache and must not live under `docs/`.
- Do not use docs or third-party references as mutable runtime state.

## Debug Cleanup

If you started WebUI or Electron during a task, close them before finishing or explicitly remind the user.

PowerShell port cleanup for default backend port:

```powershell
$pids = (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
foreach ($p in $pids) { if ($p -and $p -ne 0) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } }
```

Electron cleanup:

```powershell
Get-Process -Name "electron" -ErrorAction SilentlyContinue | Stop-Process -Force
```

## 4399 News Routes

- `data/config.template.json` may contain the project-level 4399 news account in `news.account` / `news.password`.
- The exact pair `85rwm3janyyc` / `123456` is the only public credential exception, is scoped to 4399 news/forum/gift-code proxy use, and must remain plaintext because the project depends on it for public announcement fetching.
- Treat any other `news.*`, all `game.*`, account JSON, tokens, SSL/private keys, and deploy passwords as sensitive.
- News route credential lookup should prefer configured `news.*`; if an old config has no `news` section, use the public pair for compatibility. Fall back to `game.*` only when intended.
- Forum fetches may use the exact public news pair without credential unlock; non-public news or game credentials still require WebUI credential unlock.
- News list opening must force `/api/news/posts?force=1`; do not rely on the 30-minute cache for first display after auth or tab entry.
- News proxy should retry once with a fresh 4399 session when the upstream page redirects to the 4399 login wall; stale cached sessions must not become permanent placeholders.
- The gift-code collector should inspect official announcements only: last 10 days, at most 15 posts, with `checked_post_ids` and active rows in runtime `logs/zmxy_redeem_codes.json` for incremental refresh.
- The gift-code dialog iframe should load local `/api/news/gift_codes/page` and refresh through `/api/news/gift_codes?refresh=1`; do not use the stale external 4399 gift-code page.
- Gift-code redemption uses `/api/news/redeem_targets` and `POST /api/news/gift_codes/redeem`; keep credential unlock/security-key checks, support `redeem_code` and batched `redeem_codes`, switch to the selected `server:character`, force login even for debug-mode redeem tasks, and pass each code as a one-time task param override to the built-in normal task `一般任务/活动/兑换豪礼礼品兑换`.
- Keep the redeem task under `ZmxyOL.task.normal_task.huodong.redeem_gift`, not only under `data/custom_task`.
- Public config must not expose plaintext credentials.
- Do not reuse the news account for game automation unless the user explicitly asks.

## Useful Tests And Docs

- `docs/AutoScriptor/webui/api-contract.md`
- `docs/AutoScriptor/webui/user-trajectories.md`
- `test/test_webui_contracts.py`
