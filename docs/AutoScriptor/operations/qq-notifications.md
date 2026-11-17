# QQ 通知

Install: `scripts\install.bat qq`; console: `scripts\run.bat qq`; background: qq-notify/2-start.cmd. Official v4.18.9: SHA-256/path/wrapper validation, no DLL assembly. NAPCAT_DISABLE_MULTI_PROCESS=1; no service/autostart registration.

Management/OneBot: loopback, independent random tokens, CORS/WS disabled. Reinstall preserves ports/tokens/cache; corruption fails. WaitForSingleObject detects exit; no duplicates. Missing PID uses listener; stop verifies executable, never desktop QQ.

## 登录与账号

Settings: aligned sender/recipient, no sidebar/preview; folded endpoint/token/history. Tutorial: prepare, login/confirm, recipient, test/save. Practice: no APIs/draft changes; skip/replay/close/unmount safe.

Confirm QR/cached login, verify/remember identity. Sync confirms draft discard; saves endpoint/token only. Cache expires; running/config-matched isn't logged-in/delivered.

GET/POST `/api/notify/qq/login`: local peer/Host, same-origin, X-QQ-Login:1, unlock/deployment auth. POST: action(qr/quick/refresh_qr/remember), account, confirm_switch, _timestamp; reject unknown/password/token/session fields. Idle transaction/delivery exclusion; pending/in-flight sends reject switching. Local delivery awaits verified remember; no replay. Process-local confirmation.

Backend-only management auth; no proxies/redirects/upstream errors/QQ passwords. Local QR, no-store/no-referrer; no browser-stored/URL admin credentials. Bounded polling stops on errors/unmount. Identity remembered atomically. NapCat sessions never exported/committed/shared; same-user malware outside guarantees.

Autostart requires unlock, enabled notifications, installation, remembered/cached account; no initial QR/enabling/recipient edits. Lifecycle owns config.

notify.qq: enabled/endpoint/target_type(private|group)/target_id/access_token; global, failed saves rollback/version unchanged. Tokens never echoed: UI blank preserves, explicit clear deletes; API omission preserves/empty clears; export strips/import omission preserves. Draft tests never save/connect devices; busy permits tests, not saves.

FIFO freezes identity/results, merges retries by run-id; actual tasks only, pending=interrupted, deferred=continuation, neither completed nor failed. Omit unknown metrics; ticket use isn't completion. OneBot requires status=ok/retcode=0/message_id; text prevents CQ injection. No redirects/secrets/game retries/resend; memory history isn't delivery proof.

Remote: [standalone](../../../scripts/qq-robot-standalone/README.md), private LAN/VPN IPv4, executable/port/single-source firewall; management loopback, no credential transfer/local handoff. Firewall tests use stubs; never alter host firewall.

Sources: [delivery](../../../orchestrator/delivery.py), [robot](../../../backend/core/qq_bot.py), [login](../../../backend/core/qq_login.py), [tests](../../../test/notifications/), [UI](../../../test/webui/test_qq_login_interface.py).
