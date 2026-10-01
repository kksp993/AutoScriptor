"""Import entry for the runtime battle character implementation.

The effective Hero/battle-flow code lives in data/character/hero.py so source
runs edit one file. An installed distribution has no editable data tree, so the
copy shipped inside this package is used instead. This module keeps the public
package import stable:
    from ZmxyOL.character.hero import h, Hero, battle_plan
"""
from __future__ import annotations

from pathlib import Path

from ZmxyOL.accounts import get_character_dir


# Captured before __file__ is repointed at the implementation below.
_PACKAGE_DIR = Path(__file__).resolve().parent

# Written by scripts/build_wheels.py. A source checkout never has it, because
# there data/character/hero.py is the source of truth.
_PACKAGED_IMPL_PATH = _PACKAGE_DIR / "_default_impl" / "hero.py"


def _resolve_impl_path() -> Path:
    """Editable implementation when present, otherwise the shipped copy."""
    editable = get_character_dir() / "hero.py"
    if editable.is_file():
        return editable
    return _PACKAGED_IMPL_PATH


_IMPL_PATH = _resolve_impl_path()

if not _IMPL_PATH.is_file():
    raise ImportError(
        "Missing runtime battle character implementation. Looked for the editable "
        f"copy at {get_character_dir() / 'hero.py'} and the shipped copy at "
        f"{_PACKAGED_IMPL_PATH}."
    )

__file__ = str(_IMPL_PATH)
__loader__ = None
__package__ = "ZmxyOL.character"

_code = compile(_IMPL_PATH.read_text(encoding="utf-8"), str(_IMPL_PATH), "exec")
exec(_code, globals(), globals())
