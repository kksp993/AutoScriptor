"""Prompt templates for VLM/agent execution."""

from __future__ import annotations

from AutoScriptor.vlm.config import VLM_CONFIG
from AutoScriptor.vlm.skills import load_agent_skills


def build_system_prompt(*, skills: list[str] | None = None) -> str:
    """Build the agent system prompt with live navigation context and skills."""
    from ZmxyOL.nav import mm
    from ZmxyOL.nav.api import locate_region

    try:
        current_location = locate_region(check_only=True)
    except Exception as exc:
        current_location = f"unknown: {exc}"

    configured_skills = skills if skills is not None else VLM_CONFIG.get("skills")
    skill_text = load_agent_skills(configured_skills)
    return (
        "你是 AutoScriptor 的任务生成与执行助手。你需要根据截图、用户目标和工具返回，"
        "生成保守、可验证的下一步操作或脚本草案。\n"
        "如果用户要求生成最终脚本，脚本必须能在没有视觉模型的运行环境执行；"
        "禁止在脚本中输出 V(...)、click(V(...)) 或 locate(V(...))，"
        "应把视觉观察转写为 T(...)、I(...)、B(...)、extract_info(B(...)) 等运行时 API。\n"
        "不要把用户现场的真实内网地址、端口、模型部署名、账号、密码、token、角色名、"
        "兑换码或截图中的私人文本写入脚本、文档、测试或 skill；示例必须使用占位符。\n"
        "如果工具返回包含 __Screenshot_Required__，你必须请求或等待下一张截图，"
        "不要在旧截图上继续推断。\n"
        f"当前可用环境 Env: {list(mm.envs.keys())}\n"
        f"当前可用位置 Loc: {list(mm.locs.keys())}\n"
        f"当前识别位置: {current_location}\n\n"
        f"{skill_text}"
    )


CLICK_PROMPT = """
目标：{intent_desc}
请根据截图，直接输出下一步的点击坐标或操作工具。不要分析。
"""
