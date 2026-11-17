# Shared project rules

Authority: AGENTS.md/CLAUDE.md/Cursor. Ignore private caches; read relevant domains.

## Workflow

Record failures before fixes; rerun afterward. Trace initialization/registration/execution/persistence/reload/cancellation/cleanup and evidence/tests/history. Reuse APIs, preserve user work, fix minimally; report cause/changes/validation/limitations.

Update [functional docs](../AutoScriptor/README.md), then guidance; preserve constraints/defaults/failures/source-test references. Docs <=10000 words total, <=500 each; count Han characters individually and alphanumeric words, including code. Exclude only third-party `docs/refs/` clones. Run `.venv\Scripts\python.exe -X utf8 scripts/check_docs_budget.py --details`; no relocation/whitespace tricks. Check links/stale claims.

## Boundaries

- [Source install/run/update](../AutoScriptor/INSTALL.md): no resurrected launchers/distribution/wizards/Nuitka/frozen bootstraps/manifests/Canvas/Socket.IO/VLM/secondary update channels without request. Optional wheels remain separate.
- [Registration/lifecycle](skill-references/architecture-lifecycle.md): single owners for registry/identity/reload/gate/persistence; device-free polling.
- [Authoring](skill-references/task-authoring-style.md): required `ensure_in`/`ANYWHERE`, execution-wrapper navigation; inline `T/I/B/Box`, never hoist. Input/return≠business completion.
- [Script API version policy](../AutoScriptor/reference/API.md): actual public changes only; MINOR for substantial/user-requested releases, otherwise accumulate; synchronize catalog/records/tests.
- [WebUI/news](skill-references/webui-electron-news.md): preserve auth/editable persistence/projection/transactions; fail visibly, never fabricate healthy empty/false statuses.
- [Live checks](online-screenshot-test.md): fixed-frame evidence; no unapproved resource-consuming actions.

## Safety and validation

Use package APIs/`AutoScriptor.utils.paths`; maintenance: `scripts/`, probes/evidence: logs. No root tools, broad install/config/security/path fallback, or hidden programming errors.

Never commit accounts/tokens/private keys/passwords/runtime evidence. Sole public plaintext exception: 4399 news `85rwm3janyyc` / `123456`, never game credentials.

Windows: UTF-8/project venv; verify encoding from files, not console. Serialize Python checks touching identical modules. No power/affinity/process/thread-priority tweaks.

Follow [tests](../../test/README.md): targeted regression/compilation, then full discovery when feasible. Isolate config/accounts/app-subprocess `AUTOSCRIPTOR_DATA_DIR` in temporary paths. Freeze test detection at config import, before Paddle. Stop only owned services; disclose leftovers.
