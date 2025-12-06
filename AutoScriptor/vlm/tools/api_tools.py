import cv2
from AutoScriptor import B, click, mixctrl
from ZmxyOL.nav import *
from logzero import logger
from AutoScriptor.vlm.tools.toolkits import register_tool
from AutoScriptor.vlm.utils import  parse_qwen_vl_coordinates, make_box_target

@register_tool(name="click", description="""
在指定归一化坐标位置执行点击
请如需使用clickToolTool目标的**图标**或**边缘**，不要点击文字中心
请优先点击【图形实体】，而非汉字/数字。
Args:
    coordinates: 归一化坐标，范围 0-1000
Returns:
    str: "__Screenshot_Required__"
""")
def click_tool(coordinates: tuple[int, int]):
    click(B(*parse_qwen_vl_coordinates(coordinates)))
    return "__Screenshot_Required__"


