"""Character package entry.

``hero.py`` is the import entry for the runtime implementation, which lives in
``data/character/hero.py`` so source runs edit one file. Professions are loaded
from ``character/pros/`` (shipped with the repo) and ``data/character/``
(user-owned), in that order, so a user script can override a built-in one.
"""
from __future__ import annotations

from ZmxyOL.character.hero import Hero, battle_plan, flow, h
from ZmxyOL.character.plan import BattlePlan

__all__ = [
    "BattlePlan",
    "Hero",
    "battle_plan",
    "flow",
    "h",
]
