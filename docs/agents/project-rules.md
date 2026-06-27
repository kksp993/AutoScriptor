# AutoScriptor Agent Rules

This file is the shared project rule source for Codex, Claude Code, Cursor, and other coding agents. Tool-specific entry files should point here instead of maintaining separate rule copies.

## Entry Points

- Codex: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- Cursor: `.cursor/rules/00-shared-project-rules.mdc`
- Optional local skills may point here, but `.codex/` and `.claude/` are git-ignored and must not become the durable source of truth.

When rules conflict, prefer the most specific project rule, then the tool's system/developer instruction, then the user's latest instruction.

## Core Workflow

Use this workflow for bug fixes, anomalies, regressions, and project improvements:

1. Record failures or stale evidence first, then fix and rerun.
2. Locate the failing layer: source startup, WebUI/frontend, backend service, scheduler, AutoScriptor core execution, task authoring, recognition/OCR, config/account/status, or update state.
3. Trace the lifecycle end to end: initialization, registration, runtime state, persistence, reload, retry/error path, cleanup, API payload, and UI projection.
4. Check local evidence first: `rg`, nearby tests, docs, and git history for touched files when the area is subtle or recently changed.
5. Identify the violated assumption before editing.
6. Make the smallest targeted fix using existing APIs and local patterns. Avoid new abstractions unless they remove real complexity.
7. Validate with focused tests or a reproducible probe. Check normal path, edge path, and lifecycle side effects.
8. Audit `docs/AutoScriptor/` for every behavior/API/lifecycle/state change. Use `docs/AutoScriptor/README.md` as the map, check every affected functional domain, then update shared agent rules or skill references when the change teaches a reusable rule or workflow.

Avoid permanent state traps such as "once marked, never runs again" unless explicitly intended.
For exception handling, fail precisely in install/run/update/config/security/path code. Runtime device/OCR/task boundaries may catch and record operational failures, and error archive/log cleanup may protect the original error, but do not add broad fallback paths that hide programming errors or resurrect removed product surfaces.
WebUI dynamic option/status probes must return visible API errors when imports, enum classes, config reads, or Paddle/OCR probes fail; do not synthesize empty lists, `false`, `0`, or `unknown` to make panels appear healthy.

## Source Workflow Discipline

The `src` branch is source-run only. The durable user paths are:

- Install source dependencies: `scripts\install.bat`.
- Desktop shell: `scripts\run.bat electron` or root `start.bat`.
- Backend WebUI: `scripts\run.bat webui`, root `webui.bat`, or `.venv\Scripts\python.exe -X utf8 services\webui\gui.py`.
- Static WebUI assets: `services/webui/static/`.
- Source updater: `scripts\update.bat` for manual Git updates; `/api/update/status`, `/api/update/check`, `/api/update/run` for WebUI updates.

Do not restore deleted command-menu shells, desktop distribution builders, setup wizards, binary delta services, or extra update channels unless the user explicitly asks for that product surface again.
Do not restore Nuitka/compiled-runtime bootstraps, runtime import smoke probes, MuMu packaged-runtime probes, generated task manifests, or package/frozen data-root fallbacks unless the user explicitly asks for those product surfaces again.

For source startup:

- Keep `start.bat`, `webui.bat`, `local_start.bat`, `scripts/install.*`, `scripts/run.*`, `scripts/update.*`, compatibility `scripts/launcher.*`, `scripts/bootstrap-python310.ps1`, and `webapp/main.js` aligned with source execution.
- Source install uses winget for Git/Node.js LTS/uv, then `uv venv --python 3.10.15` for `.venv`, then `uv pip install`, then `npm install` inside `webapp`.
- Keep `webapp/package.json` focused on source Electron startup. Do not hide Python bootstrap or Git update work inside npm lifecycle hooks.
- Keep WebUI logs on native WebSocket `/ws/logs`; do not reintroduce SSE or Socket.IO assumptions.
- Source Git updater must disable itself outside a Git working tree or non-source runtime instead of pretending another update path exists. It must reject detached HEAD, check with a single explicit `git fetch origin main`, compare `HEAD` against `origin/main` with ahead/behind counts, fast-forward only the current checked-out branch from `origin/main`, and surface the exact git stderr/timeout/start failure through WebUI status instead of collapsing failures to empty output, generic messages, or slow retry loops.

After moving, renaming, or materially rewriting docs, run `rg` for stale paths and stale behavior claims across `docs/AutoScriptor`, `docs/agents`, README, `docs/AutoScriptor/INSTALL.md`, tests, and scripts.

## Editing Rules

- Do not revert unrelated user changes.
- Do not keep a root `tools/` directory for one-off experiments. Durable source-maintenance scripts belong in `scripts/`; reusable runtime helpers belong in package modules such as `AutoScriptor/utils`; personal probes should stay untracked.
- Prefer package imports, for example `from AutoScriptor.utils.box_grid import make_box_grid, indexof`.
- Keep OCR/recognition semantics separate from business semantics. Example: OCR returns `None` for unreadable empty badges; inventory logic may later map missing item to `0` or visible item without badge to `1`.
- For task state/progress, do not treat "function returned" as "business succeeded" when observable completion state exists.
- For task registration, remember `TaskRegistry` stores runtime data, while `cfg["tasks"]` stores user configuration.
- Treat `ZmxyOL/task/**/_order.txt` as explicit task source ordering. Task loading may read it, but should not rewrite source-tree order files during normal startup.
- Do not leave incomplete debug placeholders registered as built-in tasks. A script that hard-stops, prints internal tables, or leaves the real flow unreachable should be deleted or kept unregistered.
- Do not add task-file direct-run wrappers with broad `try/except`, `traceback.print_exc()`, `bg.stop()`, or `exit(0)`. Use WebUI direct run and task `debug_mode` metadata so scheduler logging, cancellation, retry, and cleanup semantics stay intact.
- When editing Chinese task/source files on Windows, read and write UTF-8 explicitly and rerun a mojibake scan plus `py_compile`; do not trust terminal display alone.
- For account/character data, remember active character tasks and status are persisted in account JSON, then flattened through `cfg` at runtime.
- For paths, use `AutoScriptor.utils.paths`; source mode uses `data/config.json`, `data/accounts`, `data/custom_task`, `data/battle_character`, and `logs`.
- WebUI Editor custom-code execution must stay aligned with task authoring APIs, including `AutoScriptor` core helpers plus public `ZmxyOL.nav.api.*` and `ZmxyOL.nav.envs.decorators.*` symbols. Editor-saved scripts must be persisted under `get_custom_task_dir()` as registered custom tasks with explicit `path_cn`, normalized under the `自定义任务` cfg root, migrate stale omitted-root config leaves when possible, then reload tasks through the lifecycle service so the WebUI task tree observes the new script.
- Do not delete MuMu dynamic adapter attributes or task-authoring helpers solely because `rg` cannot find direct callers. `BaseMumuControl.__getattr__`, `from AutoScriptor import *`, and user scripts can reach these APIs dynamically.
- Long-lived runtime modules must not keep imported `mixctrl`/`mumu` snapshots from `from AutoScriptor import *` or `from AutoScriptor import mixctrl`; read the current object from `runtime_ctx` or `AutoScriptor.core.api` at the call site.
- For config/account persistence, keep atomic same-directory replace and do not fall back to direct target-file writes after replace failure. Do not add unconditional `fsync` to WebUI interactions; low-RAM or antivirus-constrained Windows hosts can turn tiny JSON writes into multi-second stalls. Use `save_global_config()` for global-only settings so account JSON is not rewritten unnecessarily.
- Scheduler/runtime-owned writes to `data/config.json` or the current account JSON (task state, progress, `next_exec_time`) must not be mistaken for external hot-reload edits on the next scheduler tick. Rebaseline those handled config/account files while keeping `data/custom_task/` and `data/battle_character/` script changes observable.
- WebUI stop controls are signal-only paths: overview, scheduler, and daily/weekly/general/custom task pages must reuse the overview `stop-dispatch` / `stopDispatch()` frontend action; after `POST /api/stop`, apply the returned lightweight runtime projection immediately and let background refresh or normal polling fetch `/api/runtime/snapshot`; do not synchronously wait for full task-tree/config snapshots in the click handler.
- Static runtime JSON/data assets belong under `data/assets/...` when they are needed at runtime; mutable generated caches belong under `logs/` via `get_logs_root()`. Do not treat `docs/refs/**`, `docs/*.json`, or third-party reference material as runtime payload.
- Optional OpenAI Agents SDK examples must stay outside the main source runtime, for example under `examples/`, unless the user explicitly asks to integrate OpenAI API calls into AutoScriptor. Do not add `openai` or `openai-agents` to `requirements.txt` for optional examples alone; document the opt-in setup instead.
- For source Electron startup, create the visible loading window before slow checks such as port cleanup or Python backend startup. Loading UI and `services\webui\gui.py` must emit phase logs for Python process creation, WebUI import, worker start, and WebUI polling so first-run delays are observable. Do not change the Windows console code page from Electron; port cleanup failures must be logged visibly.
- For source Electron GPU/Chromium stalls, keep mitigation inside `webapp/main.js` render-mode startup switches. Configure `AUTOSCRIPTOR_ELECTRON_RENDER_MODE` before `app.whenReady()`: default `software`, optional `d3d11`, or `default` for comparison. Do not use host power, process priority, thread priority, CPU affinity, or MuMu priority fallbacks for Electron stalls.
- For MuMu TCP ADB checks, remember `adb start-server` does not connect `127.0.0.1:<port>` devices. Device readiness probes should `adb connect <configured adb_addr>` and retry `get-state` before treating `device not found` as a real failure; NemuIpc screenshot success does not prove ADB is connected.
- After `MuMuManager launch` succeeds, treat it as command acceptance only. `Power.start()` must wait for the configured ADB device and Android boot completion before package resolution, App startup, or other Android-side checks.
- Treat NemuIpc as a single native IPC lane. Runtime screenshot, touch, swipe, release, and disconnect calls must go through the `NemuIpc` wrapper lock; do not bypass it with `nemu_ipc.nemu_ipc.*`, and do not paper over deterministic IPC contention with broader retries or fallback sleeps.
- Source runtime must not change Windows power state, away mode, display keepalive, CPU affinity, process priority, thread priority, or MuMu process priority as a performance fallback. `AutoScriptor.utils.perf` has been removed; fix OCR frequency, screenshot reuse, ADB state, NemuIpc serialization, or task loops instead.
- Do not spread `interval=0.5` through task scripts just to get the default click-until polling cadence. `click(..., until=...)` owns that default; plain `click()` remains immediate unless the caller explicitly passes an interval.
- `Hero.way_to_exit()` uses `bg.scope()` to watch for exit signs while the main thread moves in phases: reach the far right, move left near the exit, check whether it already landed, pulse-search left, hold briefly when an exit sign appears, then micro-adjust right only if the hold did not complete. Do not reintroduce private detector threads, `fast_until`, OCR throttling, or list/AND special cases inside this method.
- For Heaven team dungeons, visible `抽牌` means the battle loop should stop. The `heaven_battle()` background callback must only set `Pause_battle`/`try_exit`; run `way_to_exit()` and draw-card cleanup after `battle_loop()` returns on the main thread so callback exceptions cannot swallow the exit signal.
- For latest boss dungeons that may trigger "混沌先锋", task scripts should pass `battle_task(check_pioneer=True)` and keep the detection/extra-battle handling in the shared heaven battle procedure. The normal post-battle return-home flow must finish first; only then open the short pioneer detection window. Do not wrap the previous not-yet-home exit flow inside the pioneer watcher, and do not scatter one-off pioneer checks or auto-entry quickfixes through individual task scripts.
- For WebUI logs, use native WebSocket `/ws/logs`.
- For update work, keep the single source Git channel separate from manual dependency/bootstrap changes.
- For security scans, the exact 4399 public news pair `85rwm3janyyc` / `123456` is the only allowed real-looking plaintext credential exception. It is a public runtime dependency for 4399 news/forum proxying and must remain plaintext; do not remove it as a leak. Every other account, password, token, deploy secret, private key, and account JSON is sensitive.

## Project Reference Map

- AutoScriptor docs index: `docs/AutoScriptor/README.md`
- Current architecture baseline: `docs/AutoScriptor/architecture.md`
- Task authoring: `docs/AutoScriptor/tasks/script-authoring.md`
- Task safety: `docs/AutoScriptor/tasks/script-authoring-safety.md`
- Battle flows: `docs/AutoScriptor/tasks/battle-flows.md`
- Runtime lifecycle: `docs/AutoScriptor/runtime/lifecycle.md`
- Background monitor: `docs/AutoScriptor/runtime/background.md`
- Scheduler docs: `docs/AutoScriptor/schedule/scheduler.md`
- WebUI API contract: `docs/AutoScriptor/webui/api-contract.md`
- WebUI user trajectories: `docs/AutoScriptor/webui/user-trajectories.md`
- OpenAI multi-agent optional example: `docs/AutoScriptor/reference/openai-multi-agents.md`
- Error archives: `docs/AutoScriptor/operations/log-archiver.md`
- Online screenshot testing: `docs/agents/online-screenshot-test.md`
- Project skill references:
  - `docs/agents/skill-references/architecture-lifecycle.md`
  - `docs/agents/skill-references/task-authoring-style.md`
  - `docs/agents/skill-references/webui-electron-news.md`

## Validation

Use `.venv\Scripts\python.exe -X utf8` on Windows unless there is a clear reason not to. Prefer targeted `unittest`/`py_compile` or a small live probe over broad slow runs. If a tool such as `pytest` is unavailable, say so and use the closest available validation.

Before finishing, report:

- The root cause or lifecycle mismatch.
- What changed and why it is minimal.
- What validation ran.
- Whether docs or skills were updated.
