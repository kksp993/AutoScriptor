# 两个 import wheel

autoscriptor contains AutoScriptor/ and [ascli](../reference/ascli.md); zmxyol contains ZmxyOL/tasks/assets/default Hero, exactly depending on matching autoscriptor. Circular imports prevent splitting game/tasks. No orchestrator/backend/frontend/WebUI.

```powershell
.venv\Scripts\python.exe -X utf8 scripts\build_wheels.py
uv pip install --find-links dist zmxyol
```

pyproject.toml owns versions/dependencies/console scripts; requirements/exports remain aligned; never commit dist. Set writable AUTOSCRIPTOR_DATA_DIR before imports/init(); custom_task/ registers tasks.

Source Hero: data/character/hero.py; installed: _default_impl, overridden by user character/hero.py. User professions override matching built-ins.

[Tests](../../../test/framework/test_wheel_packaging.py): contents/RECORD/reproducibility/external imports. [Acceptance](../../../release_probe/README.md): isolated environment/data/live device; not replaced by offline checks.
