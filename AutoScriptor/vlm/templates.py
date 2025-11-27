"""
VLM Prompt 模板
"""
from ZmxyOL.nav import mm
from ZmxyOL.nav.api import locate_region
SYSTEM_PROMPT = f"""
你是一个执行型AI，负责分析游戏画面并直接给出操作指令。
如果工具返回包含"__Screenshot_Required__"的字符串，**必须**输出__Screenshot_Required__，并启动第二轮对话。
当前环境(Env)：{list(mm.envs.keys())}
当前位置(Loc)：{locate_region(check_only=True)}
这两个都属于关键词，里面的字一定要准确无误，不能有任何错误。
请使用贪心的方法去做，不要进行全局规划，请先做出每一步，再去调用工具看新的截图，再思考如此进行下去。
优先级=>正确的Env=>正确的Loc=>正确的ui界面=>正确的操作。
如果当前意图已经完成，请输出规定字符串 __END_OF_TASK__。
"""

CLICK_PROMPT = """
目标：{intent_desc}
请根据截图，**直接**输出下一步的点击坐标或操作工具。不要分析。
"""

def build_messages(user_prompt: str, base64_image: str) -> list[dict]:
    """构建 vLLM 消息格式"""
    image_url = f"data:image/jpeg;base64,{base64_image}"
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": SYSTEM_PROMPT}],
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]

