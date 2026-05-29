# WebUI, Release, And News Reference

Read this when changing WebUI, Electron shell, release packaging, source-map handling, or 4399 news routes.

## WebUI Architecture

- Backend: FastAPI + uvicorn.
- Logs: native WebSocket at `/ws/logs`, not Socket.IO.
- Frontend: Vue 3 CDN + Element Plus + Tailwind; no build step for `services/webui/static`.
- API routes use `/api/`.
- Frontend pulls config through `GET /api/refresh`; do not reintroduce Jinja config injection.
- Public config must strip sensitive fields such as encryption, account, password, and runtime-only task fields.
- Task save must strip runtime fields through `TaskTreeService.strip_runtime_fields()`; WebUI projections may inject fields such as `param_meta`, `param_keys`, `beta`, `custom`, `debug_mode`, `task_description`, `task_doc_flow`, `_due`, and `progress_display`.
- Component state is managed in `app.js`; components receive props and emit events upward.

Component convention:

1. Add component files under `services/webui/static/js/components/`.
2. Export as a global const, for example `const MyComponent = {...}`.
3. Load in `index.html` after dependencies and before `app.js`.
4. Register in `createApp({ components: ... })`.

## Version Coupling

- Electron package version comes from `webapp/package.json`.
- About panel display version in `services/webui/static/js/components/AboutPanel.js` must match it.
- Bump both when releasing a desktop version.
- Patch releases normally bump `x.y.z` patch. Minor-line changes (`x.y.z` second component) require explicit user confirmation during release/deployment work.

## Update Channels

- Source deployment git updater: `/api/update/*`; unavailable for packaged release users.
- Local same-line update package: `AutoScriptor_Update_x.y.z.zip` with `update_manifest.json`; protects user data and is cumulative within the same `x.y` line.
- Release content manifest: `/api/content-update/*`; pulls `deploy.content_manifest_url`, checks hash/signature/path policy, and writes only allowed install-root files.
- `backend_incremental.zip` remains a maintainer fallback for backend file diffs; it is not the default user update path.

Protected release-update paths include config, accounts, custom tasks, battle character scripts, logs, and `.autoscriptor` state.

## Packaging Data Facts

- `scripts/build_release.py collect_data()` copies `config template.json` to `dist/data/config template.json` and `dist/data/config.json`.
- It creates empty `dist/data/accounts/`, copies `data/battle_character/`, `data/custom_task/`, `ZmxyOL/assets/config/`, `ZmxyOL/assets/pic/`, and creates `dist/data/logs/`.
- It does not copy `data/accounts/*.json` or old `ZmxyOL/assets/profiles/*.yaml`.
- Portable artifact: `AutoScriptor_Zao_Install_<version>.exe`; NSIS artifact: `AutoScriptor_Zao_installer_<version>.exe`.

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

## Source Map Release Security

- Do not ship public `*.map` files that expose `sourcesContent`.
- Exclude source maps from public npm/Electron/tarball artifacts unless they are private symbol-server assets.
- Add or preserve release checks that fail when public artifacts contain source maps.
- Relevant areas: `webapp/`, Electron builder config, `scripts/build_release.py`, release staging logic.

## 4399 News Routes

- `config template.json` may contain the project-level 4399 news account in `news.account` / `news.password`.
- The exact pair `85rwm3janyyc` / `123456` is the only public credential exception and is scoped to 4399 news/forum/gift-code proxy use.
- Treat any other `news.*`, all `game.*`, account JSON, tokens, SSL/private keys, and deploy passwords as sensitive.
- News route credential lookup should prefer configured `news.*`; if an old config has no `news` section, use the public pair for compatibility. Fall back to `game.*` only when intended.
- Forum fetches may use the exact public news pair without credential unlock; non-public news or game credentials still require WebUI credential unlock.
- The gift-code dialog iframe should load local `/api/news/gift_codes/page`; keep the external 4399 page as an explicit "open original" action.
- Public config must not expose plaintext credentials.
- Do not reuse the news account for game automation unless the user explicitly asks.

## Useful Tests And Docs

- `docs/AutoScriptor/webui/api-contract.md`
- `docs/AutoScriptor/webui/user-trajectories.md`
- `test/test_webui_contracts.py`
- Existing WebUI/Electron packaging tests under `test/` and `webapp/scripts/`


