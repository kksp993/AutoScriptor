"""
VLM Prompt 模板
"""


def build_system_prompt() -> str:
    """Build system prompt with live environment/location info."""
    from ZmxyOL.nav import mm
    from ZmxyOL.nav.api import locate_region
    return (
        "你是一个执行型AI，负责分析游戏画面并直接给出操作指令。\n"
        "如果工具返回包含\"__Screenshot_Required__\"的字符串，"
        "**必须**输出__Screenshot_Required__，并启动第二轮对话。\n"
        f"当前环境(Env)：{list(mm.envs.keys())}\n"
        f"当前位置(Loc)：{locate_region(check_only=True)}"
    )


CLICK_PROMPT = """
目标：{intent_desc}
请根据截图，**直接**输出下一步的点击坐标或操作工具。不要分析。
"""
