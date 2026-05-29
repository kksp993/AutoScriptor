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

## Editing Rules

- Do not revert unrelated user changes.
- Prefer package imports, for example `from AutoScriptor.utils.box_grid import make_box_grid, indexof`.
- Keep OCR/recognition semantics separate from business semantics. Example: OCR returns `None` for unreadable empty badges; inventory logic may later map missing item to `0` or visible item without badge to `1`.
- For task state/progress, do not treat "function returned" as "business succeeded" when observable completion state exists.
- For task registration, remember `TaskRegistry` stores runtime data, while `cfg["tasks"]` stores user configuration.
- For account/character data, remember active character tasks and status are persisted in account JSON, then flattened through `cfg` at runtime.
- For paths, use `AutoScriptor.utils.paths`; source mode and packaged mode intentionally differ (`logs/` vs `data/logs/`, root `config.json` vs packaged `data/config.json`).
- For WebUI logs, use native WebSocket `/ws/logs`; do not reintroduce SSE or Socket.IO assumptions.
- For release work, keep three channels separate: source git updater, local same-line `AutoScriptor_Update_x.y.z.zip`, and HTTPS release-content manifest update.
- For release/security scans, the exact 4399 public news pair `85rwm3janyyc` / `123456` is the only allowed real-looking plaintext credential exception; every other account, password, token, deploy secret, private key, and account JSON is sensitive.

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

