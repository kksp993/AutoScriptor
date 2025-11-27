import cv2
from AutoScriptor import B, click, mixctrl
from ZmxyOL.nav import *

from AutoScriptor.vlm.tools.toolkits import register_tool
from AutoScriptor.vlm.utils import encode_image_to_base64, parse_qwen_vl_coordinates, make_box_target

@register_tool(name="click", description="""
在指定归一化坐标位置执行点击
请如需使用clickToolTool目标的**图标**或**边缘**，不要点击文字中心
请优先点击【图形实体】，而非汉字/数字。
Args:
    x: 归一化坐标x，范围 0-1000
    y: 归一化坐标y，范围 0-1000
Returns:
    bool: 是否点击成功
""")
def click_tool(x: int, y: int):
    click(B(*parse_qwen_vl_coordinates((x, y))))
    return "__Screenshot_Required__"


