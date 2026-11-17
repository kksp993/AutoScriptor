# WebUI API

api_ok/api_error; WebUIApi.request reads detail. 400=invalid,401/403=auth,409=busy; never fabricate results.

deploy.password guards /api/* (auth_token Cookie/X-Auth-Token), except auth/deploy. Login clears unlock; actions require decrypted credentials. Reverification revokes sessions; credential/revoke requires idle; rate-limited auth.

## Routes under /api/

- State: init-status, refresh, runtime/snapshot, run/status; POST stop. Device-free snapshots; refresh newer versions only; task_list preserves submission order.
- Config: POST config, config/sync; export/import/deploy. config/sync preserves bg; tasks saves without reload; tasks/reload=light, reload-all=full, idle/clear bg.
- Tasks: tasks, task-ordering, task-planning/locations; selection_policy=nearest_ready|list_ready. after_tasks/preferred_locations: omission inherits, [] clears. Validate graph; ensure_in/planning_* readonly; layout no-op.
- Readonly `params_doc`: registry parameter → label, not account JSON/global maps; missing labels=keys. [Authoring](../tasks/script-authoring.md).
- `continuation_pending`: persisted per-character, pending even when `_due=False`; `next_exec_time` schedules continuation, not completion.
- Status/progress: read-only expiry filtering, character-isolated summaries; reset clears tags/deadline. [Cycles](../tasks/script-authoring.md).
- Identity: accounts/characters list/add/delete/switch, game_profession/task/all_tasks_summary; dispatch/queue deduplicates/filters. Creation persists/switches/unlocks/invalidates login/refreshes.
- Device: diagnostics defaults without capture/OCR/UI Map; discover suggests; discover/apply saves idle.
- Editor: cached ingest-image/ocr/color/locate-image/save/store-template are device-free; screenshot/remote/execute-code acquire sessions. execute-code/stop cancels cooperatively; save-custom-task fully reloads.
- CLI: ascli/capabilities/status; POST check/transform/runs; runs/{id}, logs/artifacts/file?name=; POST runs/{id}/stop. [Contract](../reference/ascli.md); shared auth/gate; device-free status/compile.
- Script metadata: GET script-api/version,script-api/reference; no-store,authenticated,device-free. [Policy](../reference/API.md).
- Operations: update/status/check/run; notify/qq/test/local; GET/POST notify/qq/login (local/unlocked/same-origin/no-store, [contract](../operations/qq-notifications.md)); error-archives list/detail/file/DELETE/import; news/posts/proxy/redeem_targets, gift_codes/page/redeem. Logs: native /ws/logs, not SSE; [battle summaries](../tasks/battle-flows.md), unfiltered files.

Rollback preserves config_version; imports strip deploy secrets/certificates, views redact secrets. Global runtime_state checkpoints never exposed/exported/imported/edited. [FIFO/autosave](../../agents/skill-references/webui-electron-news.md); [occupancy/stop](../runtime/lifecycle.md).

GET /api/editor/navigation-options: groups+任意位置 (ANYWHERE, no map identifier). ensure_in=readonly list. POST /api/editor/save-custom-task:

```json
{"code": "pass", "metadata": {"task_path": "自定义任务/示例/操作设置", "description": "一句话描述", "task_doc": "补充说明正文", "ensure_in": "村庄", "params": [{"name": "modes", "type": "enum_multi", "enum_options": ["普通", "困难"], "default": ["普通"]}]}}
```

`自定义任务/<path>` maps to `data/custom_task/<path>.py`, e.g. `data/custom_task/背包清空/进阶仙宝.py`.

Payloads/security: [routes](../../../backend/webui/routes/), [tests](../../../test/webui/test_webui_contracts.py), [acceptance](user-trajectories.md).
