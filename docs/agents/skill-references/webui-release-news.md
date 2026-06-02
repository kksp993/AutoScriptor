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
- Keep `npm run verify-pack` strict: public Electron artifacts must fail when they contain source maps, asar `devDependencies`/npm scripts, unpacked npm payloads, or npm packages outside the small production dependency whitelist.
- Relevant areas: `webapp/`, Electron builder config, `scripts/build_release.py`, release staging logic.
- For Nuitka runtime stdlib helpers, treat `collections`, `_collections_abc`, and `ctypes` as special: compile them through a same-version source CPython `Lib` overlay that contains only those modules, using explicit `--include-package=collections` / `--include-module=_collections_abc` / `--include-package=ctypes`. Keep larger stdlib helpers such as `contextlib`, `inspect`, `json`, and `wave` on nofollow plus post-copy. Keep `multiprocessing` post-copy-only: it needs the copied package for `Manager` / `Process`, but `--nofollow-import-to=multiprocessing` can conflict with Nuitka's multiprocessing plugin. Embedded `python310.zip/*.pyc` can otherwise make Nuitka emit an empty namespace shell that breaks `from collections import deque`, `ctypes.c_longlong`, `importlib._abc`, or `multiprocessing`; `gui.py` should repair copied `importlib._abc` / `importlib._common`, `importlib` search locations, and broken package shells at startup. Windows post-copy must include stdlib `.pyd` files plus companion DLLs, including examples such as `pyexpat.pyd`, `_ssl.pyd`, `_overlapped.pyd`, `libssl-1_1.dll`, `libcrypto-1_1.dll`, `libffi-7.dll`, and `sqlite3.dll`.
- For copied stdlib packages such as `importlib.metadata`, `gui.py` must load with standard importlib specs (`spec_from_file_location` / `module_from_spec` / `loader.exec_module`) instead of hand `compile/exec` with `loader=None`; otherwise package-relative imports can leave a half-initialized `importlib.metadata` without `version`, `distributions`, or `EntryPoints`.
- Cache those importlib loader helpers before mutating copied `importlib.__path__`. Importing `importlib.util` during the repair can load copied `util.py` before `importlib._abc` is registered, causing `No module named 'importlib._abc'` and then broken `importlib.metadata`.
- Do not trust a source-mode direct probe alone for this bootstrap path. In the compiled Nuitka runtime, copied `dist/gui.dist/importlib` can make the top-level `importlib.util` helper cache fail before repair starts. Keep a `SourceFileLoader`/`ModuleSpec` fallback that can load `importlib._abc` without `importlib.util`, and cover the fallback by monkeypatching the cached helpers to `None` in tests before rerunning a long build.
- For `importlib.metadata`, pre-load package helper modules in dependency order before executing `metadata/__init__.py`: `_functools`, `_text`, `_adapters`, `_collections`, `_itertools`, `_meta`. Otherwise compiled runtime can fail inside `from . import _adapters, _meta`, leaving `metadata` without `version`, `distributions`, or `EntryPoints`.
- For `importlib.resources`, pre-load the companion `importlib.readers` module as well as `_common`; `certifi.where()` reaches it through `resources.path()`, and a copied `resources.py` alone can fail packaged smoke with `No module named 'importlib.readers'`.
- If smoke reports `cannot import name 'Manager' from 'multiprocessing'`, treat it as a broken Nuitka stdlib package shell. Load the copied `multiprocessing/__init__.py` as a real package during startup instead of only deleting the shell, but do not add `multiprocessing` to the nofollow list.
- If copied files exist but smoke still reports `No module named 'encodings.idna'` or `cannot import name 'context' from 'multiprocessing'`, fix startup package state instead of adding more copy rules. Mount copied `encodings/` on the existing package search path, preload `encodings.idna`, and clear all `multiprocessing*` modules before loading the copied package.
- If a source-mode probe loads copied `multiprocessing` but compiled smoke still fails on `multiprocessing.context`, `multiprocessing.util`, or bootstrap stderr says `cannot import name 'process' from 'multiprocessing'`, remember Nuitka's compiled `multiprocessing` can be a namespace package with pre/post-load plugin hooks. The bootstrap must pre-create the copied parent package, pre-load and attach `multiprocessing.process` plus `multiprocessing.util`, attach every child module to the parent before executing it, then export API names from `context._default_context`; do not rely on executing copied `multiprocessing/__init__.py` first.
- If `--runtime-import-smoke` passes but `engine --electron` dies when creating `Event()` with `No module named 'multiprocessing.synchronize'`, preload and attach copied `multiprocessing.synchronize` before the engine uses `Event()`. Tests should call `Event()`, not only assert the attribute exists.
- If `Event()` works but `Process.start()` fails with `No module named 'multiprocessing.popen_spawn_win32'`, export `context._default_context` APIs to the parent package first, then preload and attach copied `multiprocessing.reduction`, `multiprocessing.spawn`, and `multiprocessing.popen_spawn_win32`. `spawn.py` imports `get_start_method` / `set_start_method` from the parent package, so loading it before export is a real order bug. Tests should simulate the Windows `_Popen` path instead of only checking `Process` construction.
- If `--runtime-import-smoke` passes but `engine --electron` reports `program tried to call itself with '-c' argument`, the multiprocessing Windows spawn path is now reaching Nuitka's self-execution deployment guard. Keep `--no-deployment-flag=self-execution` in the release build; this is required by the WebUI worker process and is not a missing-copy or port issue.
- If `engine --electron` stops becoming ready and WMI shows a process storm where `autoscriptor-engine.exe` command lines are `dist\gui.dist\python.exe -S -s -c "from multiprocessing.spawn import spawn_main..."`, the packaged runtime is taking the non-frozen multiprocessing path and recursively entering `gui.py`. Clean the spawned engines first, then fix `gui.py` so packaged Windows startup sets `sys.frozen`, restores the real current exe into `sys.executable`, and calls `multiprocessing.freeze_support()` before single-instance locking or any worker loop.
- If the worker reaches Uvicorn but `uvicorn._subprocess` fails in `multiprocessing.allow_connection_pickling()` with `cannot import name 'connection' from 'multiprocessing'`, preload and attach copied `multiprocessing.connection` after exporting `context._default_context` APIs. This is a bootstrap parent-package state issue, not usually a missing copied file.
- If FastAPI/Starlette smoke reports `Protocols can only inherit from other protocols` for `_collections_abc.Awaitable`, patch both `typing._PROTO_ALLOWLIST["collections.abc"]` and `typing._PROTO_ALLOWLIST["_collections_abc"]` in the packaged bootstrap to include the normal async/collection ABCs used by Starlette.
- Before every release build, reclassify the current diff and package surfaces. If WebUI static, runtime collector scripts, JSON docs, or other backend-owned external files changed, confirm they are copied into `gui.dist`/`backend.zip` and explicitly included in the same-line update zip when needed.
- After creating a same-line update zip, inspect `update_manifest.json` or the generator summary. If the current diff includes WebUI static, collector scripts, runtime docs/JSON, or other backend-owned external assets but the manifest only replaces `backend/autoscriptor-engine.exe`, discard that zip and regenerate it with repeated `--include-backend` entries for the changed external assets.
- Keep VM acceptance layered. A VM can pass installation and basic WebUI response while Paddle/OCR runtime smoke fails with `paddle\base\libpaddle.pyd` initialization errors or `name 'libpaddle' is not defined`; do not claim OCR, MuMu, or task-execution readiness until an AVX-capable VM or MuMu-capable host passes that layer.
- If packaged runtime smoke fails with a new import/bootstrap/package issue, update `docs/AutoScriptor/release/` and this skill reference before retrying the build.
- Release sensitive scans should not dump minified vendored libraries or third-party reference documents. Exclude `services/webui/vendor/**`, `docs/AutoScriptor/3rdparties/**`, `docs/refs/**`, and `webapp/node_modules/**` for source classification, then scan built artifacts separately.

## 4399 News Routes

- `config template.json` may contain the project-level 4399 news account in `news.account` / `news.password`.
- The exact pair `85rwm3janyyc` / `123456` is the only public credential exception, is scoped to 4399 news/forum/gift-code proxy use, and must remain plaintext because the project depends on it for public announcement fetching.
- Treat any other `news.*`, all `game.*`, account JSON, tokens, SSL/private keys, and deploy passwords as sensitive.
- News route credential lookup should prefer configured `news.*`; if an old config has no `news` section, use the public pair for compatibility. Fall back to `game.*` only when intended.
- Forum fetches may use the exact public news pair without credential unlock; non-public news or game credentials still require WebUI credential unlock.
- News list opening must force `/api/news/posts?force=1`; do not rely on the 30-minute cache for first display after auth or tab entry.
- News proxy should retry once with a fresh 4399 session when the upstream page redirects to the 4399 login wall; stale cached sessions must not become permanent placeholders.
- The gift-code collector should inspect official announcements only: last 10 days, at most 15 posts, with `checked_post_ids`/active rows in `docs/zmxy_redeem_codes.json` for incremental refresh.
- The gift-code dialog iframe should load local `/api/news/gift_codes/page` and refresh through `/api/news/gift_codes?refresh=1`; do not use the stale external 4399 gift-code page.
- Gift-code redemption uses `/api/news/redeem_targets` and `POST /api/news/gift_codes/redeem`; keep credential unlock/security-key checks, support `redeem_code` and batched `redeem_codes`, switch to the selected `server:character`, force login even for debug-mode redeem tasks, and pass each code as a one-time task param override to the built-in normal task `一般任务/活动/兑换豪礼礼品兑换`.
- Keep the release-owned redeem task under `ZmxyOL.task.normal_task.huodong.redeem_gift`, not only under `data/custom_task`; same-line update packages protect user `data/custom_task`, so backend-owned redemption logic must ship through the engine.
- Public config must not expose plaintext credentials.
- Do not reuse the news account for game automation unless the user explicitly asks.

## Useful Tests And Docs

- `docs/AutoScriptor/webui/api-contract.md`
- `docs/AutoScriptor/webui/user-trajectories.md`
- `test/test_webui_contracts.py`
- Existing WebUI/Electron packaging tests under `test/` and `webapp/scripts/`


