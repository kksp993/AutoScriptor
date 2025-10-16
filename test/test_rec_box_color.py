import traceback
import numpy as np
import cv2
from AutoScriptor.recognition.rec import locate_on_screen
from AutoScriptor.utils.box import Box
from AutoScriptor import bg

def create_color_image(height, width, bgr_color):
    """
    创建纯色图像，用于颜色过滤测试
    """
    return np.full((height, width, 3), bgr_color, dtype=np.uint8)


def test_box_color_match():
    # 创建纯红图像
    img = create_color_image(50, 50, (0, 0, 255))  # BGR格式的红色
    box = Box(0, 0, 50, 50)
    # 指定颜色为红色，应该匹配
    res = locate_on_screen(img, [box], confidence=1.0, pf_boxes=[box], colors=["红色"])
    assert res == [[box]]


def test_box_color_no_match():
    # 创建纯红图像
    img = create_color_image(50, 50, (0, 0, 255))
    box = Box(0, 0, 50, 50)
    # 指定颜色为绿色，不应匹配
    res = locate_on_screen(img, [box], confidence=1.0, pf_boxes=[box], colors=["绿色"])
    assert res == [None]


def test_box_no_color():
    # 创建纯任意颜色图像
    img = create_color_image(50, 50, (100, 100, 100))
    box = Box(10, 10, 20, 20)
    # 不指定颜色，应直接返回 box 元素
    res = locate_on_screen(img, [box], confidence=1.0, pf_boxes=[box], colors=[None])
    assert res == [[box]]
    
if __name__ == "__main__":
    try:
        test_box_color_match()
        test_box_color_no_match()
        test_box_no_color()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
