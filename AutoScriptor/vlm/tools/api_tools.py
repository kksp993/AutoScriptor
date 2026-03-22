import AutoScriptor.core.api as _core_api
from AutoScriptor import B, click
from AutoScriptor.vlm.tools.toolkits import register_tool
from AutoScriptor.vlm.utils import parse_qwen_vl_coordinates


@register_tool(
    name="click",
    description=(
        "在指定归一化坐标位置执行点击。"
        "请优先点击【图形实体】（图标/边缘），而非汉字/数字中心。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "coordinates": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "归一化坐标 [x, y]，范围 0-1000",
            },
        },
        "required": ["coordinates"],
    },
)
def click_tool(coordinates: list[int] | tuple[int, int]):
    click(B(*parse_qwen_vl_coordinates(tuple(coordinates))))
    return "__Screenshot_Required__"
