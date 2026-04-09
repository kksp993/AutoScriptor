from typing import Optional, Tuple, Union
import collections
import random

from AutoScriptor.utils.logger import logger


class Box(collections.namedtuple('Box', 'left top width height')):
    __slots__ = ()

    def __new__(cls, left=0, top=0, width=-1, height=-1):
        width = width if width >= 0 else (1280-width) 
        height = height if height >= 0 else (720-height)
        return super(Box, cls).__new__(cls, int(left), int(top), int(width), int(height))

    def center(self):
        return self.left + int(self.width / 2), self.top + int(self.height / 2) 
    
    def __eq__(self, other):
        return self.left == other.left and self.top == other.top and self.width == other.width and self.height == other.height

    def __hash__(self):
        # 使Box对象可哈希，基于其不可变属性
        return hash((self.left, self.top, self.width, self.height))

    def __repr__(self):
        # 紧凑显示
        return f"{self.left},{self.top},{self.width},{self.height}"
    
    def __str__(self):
        return self.__repr__()
    
    def representation(self):
        # 完整显示
        return f"Box(left={self.left}, top={self.top}, width={self.width}, height={self.height})"
    
    def is_in(self, other: 'Box') -> bool:
        return (
            self.left >= other.left and
            self.top >= other.top and
            self.left + self.width <= other.left + other.width and
            self.top + self.height <= other.top + other.height
        )
    
    def overlaps_with(self, other: 'Box', threshold: float = 0.5) -> bool:
        """
        检查两个Box是否重叠
        Args:
            other: 另一个Box对象
            threshold: 重叠面积比例阈值，默认0.5表示重叠面积超过50%认为重叠
        Returns:
            bool: 是否重叠
        """
        # 计算重叠区域
        left_overlap = max(self.left, other.left)
        top_overlap = max(self.top, other.top)
        right_overlap = min(self.left + self.width, other.left + other.width)
        bottom_overlap = min(self.top + self.height, other.top + other.height)
        
        # 如果没有重叠区域
        if left_overlap >= right_overlap or top_overlap >= bottom_overlap:
            return False
        
        # 计算重叠面积
        overlap_area = (right_overlap - left_overlap) * (bottom_overlap - top_overlap)
        # 计算两个Box中较小的面积
        min_area = min(self.width * self.height, other.width * other.height)
        
        # 如果重叠面积超过较小Box面积的阈值，认为重叠
        return overlap_area / min_area > threshold
    
    def distance_to(self, other: 'Box') -> float:
        """
        计算两个Box中心点之间的欧几里得距离
        """
        center1 = self.center()
        center2 = other.center()
        return ((center1[0] - center2[0]) ** 2 + (center1[1] - center2[1]) ** 2) ** 0.5

    @property
    def area(self) -> int:
        return self.width * self.height

    def intersection(self, other: 'Box') -> 'Box':
        left_overlap = max(self.left, other.left)
        top_overlap = max(self.top, other.top)
        right_overlap = min(self.left + self.width, other.left + other.width)
        bottom_overlap = min(self.top + self.height, other.top + other.height)
        if left_overlap >= right_overlap or top_overlap >= bottom_overlap:
            return Box(0, 0, 0, 0)
        return Box(left_overlap, top_overlap, right_overlap - left_overlap, bottom_overlap - top_overlap)
    
    def sim_box(self, other: 'Box', threshold: float = 0.75)->bool:
        # 交并比，这个指标要求很高，https://blog.csdn.net/weixin_43272781/article/details/113757298
        inter = self.intersection(other)
        union_area = self.area + other.area - inter.area
        if union_area == 0: return False
        logger.debug(f"{self} {other} => {inter.area / union_area > threshold}({inter.area / union_area})")
        return inter.area / union_area > threshold
    
    @staticmethod
    def merge_overlapping_boxes(boxes: list, overlap_threshold: float = 0.5, distance_threshold: int = 5) -> list:
        """
        合并重叠或距离很近的Box
        Args:
            boxes: Box对象列表
            overlap_threshold: 重叠面积比例阈值
            distance_threshold: 距离阈值（像素）
        Returns:
            list: 去重后的Box列表
        """
        if not boxes:
            return []
        
        # 按左上角坐标排序，便于处理
        sorted_boxes = sorted(boxes, key=lambda b: (b.top, b.left))
        merged_boxes = []
        
        for box in sorted_boxes:
            is_duplicate = False
            
            # 检查是否与已合并的Box重叠或距离很近
            for existing_box in merged_boxes:
                if (box.overlaps_with(existing_box, overlap_threshold) or 
                    box.distance_to(existing_box) < distance_threshold):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                merged_boxes.append(box)
        
        return merged_boxes
    
    def __add__(self, other: dict) -> 'Box':
        """
        平移/缩放 Box，语义与 ``click(..., offset=..., resize=...)``、``b2p`` 一致。

        右侧须为 ``dict``，键名与 click 一致：``offset``、``resize``（均可省略；亦可显式写
        ``(0, 0)`` / ``(-1, -1)``）。未出现的键按 ``offset=(0,0)``、``resize=(-1,-1)``（保持宽高）。
        可与 ``click`` 共用同一 dict：``T(..., box=base + delta)``、``click(..., **delta)``。
        """
        if not isinstance(other, dict):
            raise TypeError('Box + 仅支持 dict，键为 "offset"、"resize"，与 click/b2p 对齐')
        o = other.get("offset", (0, 0))
        rz = other.get("resize", (-1, -1))
        if len(o) != 2 or len(rz) != 2:
            raise ValueError("dict 中 offset、resize 须为二元组（若缺省键则使用默认）")
        return box_with_offset_resize(self, (int(o[0]), int(o[1])), (int(rz[0]), int(rz[1])))

    def __sub__(self, other: 'Box') -> dict[str, tuple[int, int]]:
        """
        被减数相对减数的变换量：``a - b`` 得到 ``dict``，满足 ``b + (a - b) == a``
        （与 ``+`` / ``box_with_offset_resize`` 同一套 ``offset``、``resize`` 语义）。

        返回值**固定**含 ``"offset"``、``"resize"`` 两键（不省略），可为 ``(0, 0)``、``(-1, -1)`` 等显式值。
        """
        if not isinstance(other, Box):
            raise TypeError("Box - 仅支持与另一个 Box 相减")
        return box_sub_as_delta(self, other)

    def margin(self, margin: int=20) -> 'Box':
        "扩大box的区域，用于ocr识别（自动裁剪到屏幕范围 0,0,1280,720）"
        l = max(0, self.left - margin)
        t = max(0, self.top - margin)
        r = min(1280, self.left + self.width + margin)
        b = min(720, self.top + self.height + margin)
        return Box(l, t, max(0, r - l), max(0, b - t))


def box_cell_in_grid(
    found: Optional[Box],
    grid: Union[list[list[Box]], list[Box]],
) -> Optional[Tuple[int, int, Box]]:
    """
    判断 found 的中心点落在 grid 的哪一格中。
    grid 可为二维列表（外层行、内层列），或一维 list[Box]（视为单行，row 恒为 0）。
    命中则返回 (row, col, 该格 Box)，否则 None。
    """
    if found is None or not grid:
        return None
    cx, cy = found.center()
    if isinstance(grid[0], Box):
        for c, cell in enumerate(grid):
            if (
                cell.left <= cx < cell.left + cell.width
                and cell.top <= cy < cell.top + cell.height
            ):
                return (0, c, cell)
        return None
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if (
                cell.left <= cx < cell.left + cell.width
                and cell.top <= cy < cell.top + cell.height
            ):
                return (r, c, cell)
    return None


def dp(r: Box) -> Tuple[Union[int, None], Union[int, None]]:
    center_x, center_y = r.center()
    offset_x = random.randint(-r.width // 6, r.width // 6)
    offset_y = random.randint(-r.height // 6, r.height // 6)
    return center_x + offset_x, center_y + offset_y

def centre(r: Box) -> Tuple[Union[int, None], Union[int, None]]:
    return r.center()

def offset_box(r: Box, offset_x: int, offset_y: int) -> Box:
    return Box(r.left + offset_x, r.top + offset_y, r.width, r.height)      

def resize_box(r: Box, width: int, height: int) -> Box:
    return Box(r.left, r.top, width, height)


def box_with_offset_resize(
    r: Box,
    offset: Tuple[int, int] = (0, 0),
    resize: Tuple[int, int] = (-1, -1),
) -> Box:
    """
    先按 offset 平移左上角，再按 resize 调整宽高（分量 <=0 则保留原宽高）。
    与 ``click(..., offset=..., resize=...)``、``b2p``、``Box + {...}`` 使用同一套参数语义。
    """
    return Box(
        r.left + offset[0],
        r.top + offset[1],
        resize[0] if resize[0] > 0 else r.width,
        resize[1] if resize[1] > 0 else r.height,
    )


def box_sub_as_delta(minuend: Box, subtrahend: Box) -> dict[str, tuple[int, int]]:
    """
    求 ``minuend`` 相对 ``subtrahend`` 的 ``offset`` / ``resize``，使得
    ``subtrahend + delta == minuend``（与 ``+`` / ``box_with_offset_resize`` 一致）。

    返回的 dict **始终**同时包含 ``"offset"``、``"resize"``（可与 ``click(..., **delta)`` 对齐）；
    无平移时为 ``(0, 0)``，某维宽高与减数相同时该维为 ``-1``（与 ``+`` 缺省 ``resize`` 一致）。
    """
    rw = minuend.width if minuend.width != subtrahend.width else -1
    rh = minuend.height if minuend.height != subtrahend.height else -1
    off = (minuend.left - subtrahend.left, minuend.top - subtrahend.top)
    rz = (rw, rh)
    return {"offset": off, "resize": rz}


def b2p(
        r: Box, 
        offset: tuple[int, int] = (0, 0),
        resize: tuple[int, int] = (-1, -1)
    ) -> Tuple[int, int]:
    """
    将Box转换为点击坐标点（带偏移和大小调整）
    
    变换流程：
    1. 先应用 offset：将Box从左上角 (left, top) 偏移到 (left+offset[0], top+offset[1])
    2. 再应用 resize：如果指定了resize且>0，将Box大小调整为 (resize[0], resize[1])
    3. 最后返回：变换后Box的中心点 + 随机偏移（±width/6, ±height/6）
    
    Args:
        r: 原始Box对象
        offset: 偏移量 (x, y)，相对于原Box左上角
            - 示例: offset=(120, 120) 表示向右偏移120px，向下偏移120px
            - 用途：当目标区域较大，需要点击其内部特定位置时使用
        resize: 调整Box大小 (width, height)
            - 如果为(-1, -1)则保持原Box大小
            - 如果>0则调整为指定大小（位置不变，仍基于左上角）
            - 用途：缩小点击范围，提高点击精度
    
    Returns:
        Tuple[int, int]: 最终点击坐标 (x, y)
    
    Examples:
        # 原Box: Box(100, 200, 200, 100)  # left=100, top=200, width=200, height=100
        # 中心点: (200, 250)
        
        # 不偏移，直接点击中心附近
        b2p(Box(100, 200, 200, 100), offset=(0, 0))  
        # -> 变换后Box: Box(100, 200, 200, 100)，点击中心附近
        
        # 偏移到右下角区域
        b2p(Box(100, 200, 200, 100), offset=(120, 120))  
        # -> 变换后Box: Box(220, 320, 200, 100)，点击新中心附近
        
        # 先偏移，再缩小范围
        b2p(Box(100, 200, 200, 100), offset=(120, 120), resize=(80, 80))  
        # -> 变换后Box: Box(220, 320, 80, 80)，点击新中心附近
    """
    return dp(box_with_offset_resize(r, offset, resize))
