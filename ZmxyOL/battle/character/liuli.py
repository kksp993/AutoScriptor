"""兼容入口：琉离实现位于 data/battle_character/liuli.py。"""
from AutoScriptor.battle_character.hero import ensure_battle_heroes_loaded, _hero_registry

ensure_battle_heroes_loaded()
LiuLi = _hero_registry.get("琉离")
if LiuLi is None:
    raise ImportError("未找到职业脚本: data/battle_character/liuli.py")

__all__ = ["LiuLi"]
