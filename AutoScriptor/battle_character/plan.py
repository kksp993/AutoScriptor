"""Declarative battle flow plans."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class BattlePlan:
    """Small DSL for readable and reusable battle flows.

    A plan separates scheduling ("when") from actions ("what") while still
    executing regular Hero methods. It can be used either inside a @flow method
    or directly as a class-level flow declaration.
    """

    def __init__(self, flow_name: str = None, *, task: str = None):
        self._steps: list[tuple[str, str, Any, Callable[[Any], Any]]] = []
        self.__name__ = "battle_plan" if flow_name is None else f"battle_plan_{flow_name}"
        if flow_name is not None:
            self._flow_registrations = [(flow_name, task)]

    def __call__(self, hero):
        return self.run(hero)

    def first(self, action: str | Callable[[Any], Any], *args, **kwargs) -> "BattlePlan":
        return self._add("first", None, action, *args, **kwargs)

    def at(self, seconds: float, action: str | Callable[[Any], Any], *args, fast: float = None, **kwargs) -> "BattlePlan":
        return self._add("at", (seconds, fast), action, *args, **kwargs)

    def every(self, seconds: float, action: str | Callable[[Any], Any], *args, fast: float = None, **kwargs) -> "BattlePlan":
        return self._add("every", (seconds, fast), action, *args, **kwargs)

    def each_round(self, action: str | Callable[[Any], Any], *args, **kwargs) -> "BattlePlan":
        return self._add("each", None, action, *args, **kwargs)

    def combo(self, combo: str = None, no_cd: str = None) -> "BattlePlan":
        return self.each_round("battle", combo, no_cd=no_cd)

    def run(self, hero):
        for step_key, kind, params, action in self._steps:
            if kind == "first":
                if hero.first_round():
                    action(hero)
            elif kind == "at":
                seconds, fast = params
                if hero.at(seconds, fast=fast, key=step_key):
                    action(hero)
            elif kind == "every":
                seconds, fast = params
                if hero.every(seconds, fast=fast, key=step_key):
                    action(hero)
            elif kind == "each":
                action(hero)
            else:
                raise RuntimeError(f"未知 BattlePlan step: {kind}")
        return hero

    def _add(self, kind: str, params: Any, action: str | Callable[[Any], Any], *args, **kwargs) -> "BattlePlan":
        step_key = f"{self.__name__}:{len(self._steps)}:{kind}"
        self._steps.append((step_key, kind, params, self._action(action, *args, **kwargs)))
        return self

    @staticmethod
    def _action(action: str | Callable[[Any], Any], *args, **kwargs) -> Callable[[Any], Any]:
        if isinstance(action, str):
            def call(hero):
                return getattr(hero, action)(*args, **kwargs)
            return call

        if callable(action):
            def call(hero):
                return action(hero, *args, **kwargs)
            return call

        raise TypeError(f"BattlePlan action must be method name or callable, got {type(action)!r}")


def battle_plan(flow_name: str = None, *, task: str = None) -> BattlePlan:
    """Create a declarative battle plan.

    Passing flow_name makes the plan directly registrable as a class-level flow:
        default_battle_flow = battle_plan("战斗循环").first(...).combo()
    """
    return BattlePlan(flow_name, task=task)
