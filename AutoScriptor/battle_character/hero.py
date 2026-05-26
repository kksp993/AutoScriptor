"""Compatibility entry for the runtime battle character implementation.

The effective Hero/battle-flow code lives in data/battle_character/hero.py so
development and packaged builds use the same editable source of truth. This
module keeps the historical import path stable:
    from AutoScriptor.battle_character.hero import h, Hero, battle_plan
"""
from __future__ import annotations

import sys

from AutoScriptor.utils.paths import get_battle_character_dir


_IMPL_PATH = get_battle_character_dir() / "hero.py"

if not _IMPL_PATH.is_file():
    raise ImportError(f"Missing runtime battle character implementation: {_IMPL_PATH}")

__file__ = str(_IMPL_PATH)
__loader__ = None
__package__ = "AutoScriptor.battle_character"
sys.modules.setdefault("battle_character.hero", sys.modules[__name__])

_code = compile(_IMPL_PATH.read_text(encoding="utf-8"), str(_IMPL_PATH), "exec")
exec(_code, globals(), globals())
