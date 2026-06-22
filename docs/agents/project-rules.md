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

1. Locate the failing layer: install/update, WebUI/frontend, backend service, scheduler, AutoScriptor core execution, task authoring, recognition/OCR, config/account/status, or packaging.
2. Trace the lifecycle end to end: initialization, registration, runtime state, persistence, reload, retry/error path, cleanup, API payload, and UI projection.
3. Check local evidence first: `rg`, nearby tests, docs, and git history for touched files when the area is subtle or recently changed.
4. Identify the violated assumption before editing.
5. Make the smallest targeted fix using existing APIs and local patterns. Avoid new abstractions unless they remove real complexity.
6. Validate with focused tests or a reproducible probe. Check normal path, edge path, and lifecycle side effects.
7. Audit `docs/AutoScriptor/` for every behavior/API/lifecycle/state/packaging change. Use `docs/AutoScriptor/README.md` as the map, check every affected functional domain, then update shared agent rules or skills when the change teaches a reusable rule or workflow.

Avoid permanent state traps such as "once marked, never runs again" unless explicitly intended.

## Release Workflow Discipline

Before every release build, package generation, or update-package validation, perform a fresh packaging preflight. Do not assume the last build's package-surface decision still applies.

- Read the release skills and docs first: `autoscriptor-install-deployment-release`, `autoscriptor-packaging-content-config`, `windows-powershell-command-hygiene`, `docs/AutoScriptor/release/build-and-run.md`, `docs/AutoScriptor/release/nuitka-reference.md`, and `docs/AutoScriptor/release/vm-acceptance.md`.
- Classify the current diff into backend/runtime/task logic, WebUI/Electron static files, runtime external assets, data/docs content, installer/update-contract changes, and dependency/Nuitka/bootstrap changes. The classification determines whether `--skip-nuitka`, full Nuitka, full Electron, and same-line update zip are valid.
- When a packaged build or smoke test exposes a new class of failure, pause and update the relevant docs plus skill references before retrying. The goal is to prevent the same pitfall from becoming another ad hoc terminal session.
- VM install/update acceptance is a release gate, not a follow-up. Before pushing a release commit/tag to GitHub, publishing artifacts, or saying the release is complete, restore/use the clean VM, run the required full installer acceptance and same-line update acceptance, collect the report JSON/logs, and confirm the generated artifacts passed. If VM acceptance is not complete, report only "artifacts built, release not published/accepted" and stop before any public push or tag.
- An interrupted build, a build without packaged runtime import smoke, or a package without VM install/update acceptance is not a releasable artifact and must not be reported as accepted or published.
- When the user asks to verify the real installer UI, run the portable installer in the VM through GUI interaction, not the headless PowerShell install path. Use VirtualBox keyboard/mouse injection plus screenshots, then verify the resulting install tree, `install.json`, launcher behavior, and WebUI health with collected evidence before release.
- If a portable installer launched from `\\VBOXSVR\release` or the mapped shared drive exits without showing the Electron window, copy the exe to a local guest path such as `%USERPROFILE%\Downloads` and launch that local copy. Do not assume a fixed VirtualBox shared-folder drive letter such as `Y:`; use the UNC path or the drive letter created by `pushd` for that command. The installer wizard's primary button must be keyboard reachable; Enter should advance the current primary action when focus is not in an editable input control.
- Do not treat all of `dist_electron/` as a release artifact. It is not automatically cleaned and may contain stale manual install directories with local `data/accounts/*.json` or logs; clear or quarantine those directories before packaging and scan only the current outputs you will distribute.
- After generating a same-line update zip, inspect `update_manifest.json` or the generator summary. If the current diff includes WebUI static, collector scripts, runtime docs/JSON, or other backend-owned external assets but the manifest only replaces `backend/autoscriptor-engine.exe`, the update zip is incomplete and must be regenerated with explicit `--include-backend` entries before validation.
- Same-line update zips should stay lightweight by default. Do not include the full portable installer as `造笔.exe` just because the recorded release version advances; first VM-test the previous installed launcher after update. Only include/replace the launcher when the post-update launcher probe fails because the old shell cannot start the updated backend, and treat update zips over 100 MB as a release decision that needs explicit justification or falling back to full-installer-only distribution.
- For source portable releases under `packaging/source_portable/`, do not run the Nuitka/C++ release path unless the user explicitly redirects back to it. Starting with the v1.0.3 reinstall baseline, the accepted source portable layout is `runtime/python/`, `backend/backend.pyz`, external `backend/services/webui/static|vendor`, and seed `data/`; update packages must replace `backend/backend.pyz` plus needed external Web assets and use `config_defaults` for missing config keys. Do not claim compatibility with pre-v1.0.3 source update packages. Do not distribute electron-builder single-file portable exe artifacts unless they pass an explicit startup smoke; large self-extracting payloads can fail the fast-window requirement.
- During VirtualBox VM acceptance launched from Win+R or keyboard injection, wrap shared-folder batch commands with `cmd /c "pushd \\VBOXSVR\release && call <script>.cmd"`. Starting a batch file directly from a UNC current directory can make `cmd.exe` fall back to `C:\Windows` and leave acceptance logs empty.
- VM acceptance scripts must not use unbounded WMI/CIM diagnostics after the WebUI check; add an operation timeout so report writing cannot hang after the actual install/runtime validation has already succeeded.
- Keep VM release results layered: basic installer/WebUI acceptance does not prove Paddle/OCR or MuMu task execution when runtime smoke fails with `libpaddle.pyd` initialization errors. Claim those only after an AVX-capable VM or MuMu-capable host passes the runtime/device acceptance.
- Windows PowerShell 5.1 guest scripts should avoid raw UTF-8 Chinese executable name literals such as `造笔.exe` unless saved with BOM; synthesize them with char codes so launcher/start/kill checks do not fail from mojibake.
- For same-line update VM tests, record the pre-update baseline launcher result, update application/data-preservation result, post-update launcher result, and direct backend WebUI result separately. If the baseline launcher already fails under `VBoxManage guestcontrol`, do not blame the update package for the post-update launcher failure. The WebUI file-picker update path is an Electron IPC path and is not proven by backend direct startup alone.
- Before the post-update launcher probe in same-line VM tests, stop the baseline launcher by captured PID and install-root process path, not just by the Chinese image name. A lingering `造笔.exe` can hold Electron's single-instance lock and create a false post-update launcher failure with no backend startup logs.
- VM guest scripts that write JSON markers consumed by Electron/Node, such as `install.json` or `.autoscriptor/release_version.json`, must write UTF-8 without BOM. Windows PowerShell 5.1 `Set-Content -Encoding UTF8` writes a BOM, which can make `JSON.parse(fs.readFileSync(path, "utf8"))` fail and send the launcher down the wrong install-root/installer path. Post-install acceptance must read `install.json.dataRoot` and validate `dataRoot/config.json`, not stale install-root `data/config.json`.
- Packaged installer uninstallers must not rely on deleting the running script from inside the install root. Keep the visible `Uninstall.ps1`/bat as launchers only; copy or generate a worker under `%TEMP%`, run it from `%TEMP%`, and let that worker remove app files, registry entries, markers, and optional external `dataRoot`. Windows Apps registry entries should be written with `New-ItemProperty -PropertyType` for String/DWord values and include `EstimatedSize`, `InstallDate`, `NoModify`, and `NoRepair`; `Set-ItemProperty -Type` is not a valid registry-writing pattern in Windows PowerShell.
- On Windows, avoid shell-glob assumptions in release scans. Use explicit `"config.json"` and `"config template.json"` paths rather than bare `config*`, mask sensitive values in command output, and exclude third-party reference or vendored/minified trees such as `docs/refs/**`, `docs/AutoScriptor/3rdparties/**`, `services/webui/vendor/**`, and `webapp/node_modules/**` when classifying source hits. Artifact scans must still cover built `dist` / `dist_electron` outputs.

## Editing Rules

- Do not revert unrelated user changes.
- Prefer package imports, for example `from AutoScriptor.utils.box_grid import make_box_grid, indexof`.
- Keep OCR/recognition semantics separate from business semantics. Example: OCR returns `None` for unreadable empty badges; inventory logic may later map missing item to `0` or visible item without badge to `1`.
- For task state/progress, do not treat "function returned" as "business succeeded" when observable completion state exists.
- For task registration, remember `TaskRegistry` stores runtime data, while `cfg["tasks"]` stores user configuration.
- For account/character data, remember active character tasks and status are persisted in account JSON, then flattened through `cfg` at runtime.
- For paths, use `AutoScriptor.utils.paths`; source mode and packaged mode intentionally differ (`logs/` vs data-root `logs/`, root `config.json` vs packaged `install.json.dataRoot/config.json`). In packaged/Electron data-root mode, stale absolute `accounts.dir` values must be normalized to `dataRoot/accounts`; config/account save errors must expose the real config path, accounts dir, and dataRoot instead of generic "unknown error" UI text. If Windows ACL allows file writes but denies atomic replace/delete, persistence may fall back to direct target writes with a warning instead of making all saves fail.
- For config/account persistence, keep atomic same-directory replace, but do not add unconditional `fsync` to WebUI interactions; low-RAM or antivirus-constrained Windows hosts can turn tiny JSON writes into multi-second stalls. Use `save_global_config()` for global-only settings so account JSON is not rewritten unnecessarily.
- Runtime JSON/data assets should be packaged under `dist/data/assets/...` and read through data-root helpers. Do not ship backend `docs/` as runtime payload; `docs/refs/**` is third-party reference material and must stay ignored/excluded.
- For packaged Electron startup, create the visible loading window before slow checks such as port cleanup, packaged path probing, or Python backend startup. Loading UI and `gui.py` must emit phase logs for Python process creation, WebUI import, worker start, and WebUI polling so first-run delays are observable.
- For MuMu TCP ADB checks, remember `adb start-server` does not connect `127.0.0.1:<port>` devices. Device readiness probes should `adb connect <configured adb_addr>` and retry `get-state` before treating `device not found` as a real failure; NemuIpc screenshot success does not prove ADB is connected.
- For WebUI logs, use native WebSocket `/ws/logs`; do not reintroduce SSE or Socket.IO assumptions.
- For release work, keep three channels separate: source git updater, local same-line `AutoScriptor_Update_x.y.z.zip`, and HTTPS release-content manifest update.
- For release/security scans, the exact 4399 public news pair `85rwm3janyyc` / `123456` is the only allowed real-looking plaintext credential exception. It is a public runtime dependency for 4399 news/forum proxying and must remain plaintext; do not remove it as a leak. Every other account, password, token, deploy secret, private key, and account JSON is sensitive.

## Project Reference Map

- AutoScriptor docs index: `docs/AutoScriptor/README.md`
- Task authoring: `docs/AutoScriptor/tasks/script-authoring.md`
- Task safety: `docs/AutoScriptor/tasks/script-authoring-safety.md`
- Battle flows: `docs/AutoScriptor/tasks/battle-flows.md`
- Runtime lifecycle: `docs/AutoScriptor/runtime/lifecycle.md`
- Background monitor: `docs/AutoScriptor/runtime/background.md`
- Scheduler docs: `docs/AutoScriptor/schedule/scheduler.md`
- WebUI API contract: `docs/AutoScriptor/webui/api-contract.md`
- Release docs: `docs/AutoScriptor/release/build-and-run.md`
- Release VM acceptance: `docs/AutoScriptor/release/vm-acceptance.md`
- Error archives: `docs/AutoScriptor/operations/log-archiver.md`
- Refactor index: `docs/AutoScriptor/refactor/README.md`
- Online screenshot testing: `docs/agents/online-screenshot-test.md`
- Project skill references:
  - `docs/agents/skill-references/architecture-lifecycle.md`
  - `docs/agents/skill-references/task-authoring-style.md`
  - `docs/agents/skill-references/webui-release-news.md`

## Validation

Use `.venv\Scripts\python.exe -X utf8` on Windows unless there is a clear reason not to. Prefer targeted `unittest`/`py_compile` or a small live probe over broad slow runs. If a tool such as `pytest` is unavailable, say so and use the closest available validation.

After moving, renaming, or materially rewriting docs, run `rg` for stale paths and stale behavior claims across `docs/AutoScriptor`, `docs/agents`, README, INSTALL, tests, and scripts.

Before finishing, report:

- The root cause or lifecycle mismatch.
- What changed and why it is minimal.
- What validation ran.
- Whether docs or skills were updated.

