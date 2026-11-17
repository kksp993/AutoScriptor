# ascli

Entry: `scripts/ascli.bat` / `.venv`'s `ascli` / `python -m AutoScriptor.cli`; wheel excludes WebUI.

```sh
ascli help click
ascli check flow.as
ascli transform flow.as -o flow.py
ascli run flow.as --timeout 300
ascli status RUN_ID
ascli logs RUN_ID
ascli artifacts RUN_ID
ascli stop RUN_ID
```

Global --url/--json; AUTOSCRIPTOR_URL overrides AUTOSCRIPTOR_PORT/5000; AUTOSCRIPTOR_AUTH_TOKEN authenticates. Platform unlock required; no local-controller fallback.

## Grammar

UTF-8 `.as`: command/line, optional `ascli`, quotes/comments; no shell/expansion/Python/loops. Quoted quotes/backslashes escape. Preflight source/imports/templates/signatures before actions.

```sh
wait-appear -T "Settings" --timeout 10
click -B 332 33 22 44 --until -T "Done" --timeout 20
wait-disappear -T "Loading" --timeout 10
```

`-B x y [w h]`, `-T text`, `-I key`; `--box x y w h`/`--color`/`--margin` modify preceding target. `--any`=tuple, `--all`=list where supported; `--next`=sequence, `--to`=swipe endpoint. `--until/--until-gone` REPEAT clicks. Sequence timeout: per-step. Plain coordinates cannot verify transitions; AND waits use separate commands.

`--save-as frame` names screenshot; `--frame frame` reuses BGR. Python: inline targets, call/line, existing runtime, no init/exception boilerplate. Service owns recording.

## Execution

AutomationService shares gate/cancellation/runtime; no queue. `--detach`=acceptance only. Request IDs deduplicate; disconnects never replay. Restart interrupts unfinished runs. Accepted cancellation overrides cleanup, clears verified, retains occupancy; native calls cannot be forcibly stopped.

Recording required. Success/cancel/failure retain bounded video, traces, source/Python/map/result under `get_logs_root()/ascli/RUN_ID`. Gaps/damage explicit; recording-start failure prevents actions. Limits:3600s/512 commands. No terminal observation: `verified=false`, not business acceptance.

ADB shell/push require `run --allow-unsafe`; push reads backend files, pull/screenshots stay under run artifacts/. Never embed credentials. `task run PATH`: registered executor, preserved scene, acceptance only, normal task debug/video policy.

`task show PATH` inspects; `task debug PATH on|off|inherit` persists overrides while idle (`inherit` removes). Restore original settings explicitly after debugging.

`AutoScriptor.cli` exports AscliClient/AutomationService/parse_script/transform_script/transform_with_map. Tests: test/framework/test_ascli.py, test/runtime/test_ascli_adapter.py, test/webui/test_ascli_routes.py.
