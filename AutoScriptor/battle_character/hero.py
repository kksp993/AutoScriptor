"""Import entry for the runtime battle character implementation.

The effective Hero/battle-flow code lives in data/battle_character/hero.py so
source runs use one editable source of truth. This module keeps the public
package import stable:
    from AutoScriptor.battle_character.hero import h, Hero, battle_plan
"""
from __future__ import annotations

from AutoScriptor.utils.paths import get_battle_character_dir


_IMPL_PATH = get_battle_character_dir() / "hero.py"

if not _IMPL_PATH.is_file():
    raise ImportError(f"Missing runtime battle character implementation: {_IMPL_PATH}")

__file__ = str(_IMPL_PATH)
__loader__ = None
__package__ = "AutoScriptor.battle_character"

_code = compile(_IMPL_PATH.read_text(encoding="utf-8"), str(_IMPL_PATH), "exec")
exec(_code, globals(), globals())
