from __future__ import annotations

from pathlib import Path
from typing import Iterable


_SKILL_DIR = Path(__file__).with_name("agent_skills")
_DEFAULT_SKILLS = (
    "autoscriptor_api",
    "safe_task_execution",
    "vision_grounding_patterns",
    "custom_task_authoring",
)


def _normalize_skill_names(names: Iterable[str] | None) -> list[str]:
    if not names:
        return list(_DEFAULT_SKILLS)
    return [str(name).strip() for name in names if str(name).strip()]


def load_agent_skills(names: Iterable[str] | None = None) -> str:
    """Load prompt skills that teach an LLM how to use AutoScriptor safely."""
    chunks: list[str] = []
    skill_root = _SKILL_DIR.resolve()
    for name in _normalize_skill_names(names):
        path = (skill_root / f"{name}.md").resolve()
        if not path.is_file() or skill_root not in path.parents:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            chunks.append(f"## Skill: {name}\n{text}")
    return "\n\n".join(chunks)
