from typing import Tuple, Union
import collections
import random

from logzero import logger


class Box(collections.namedtuple('Box', 'left top width height')):
    __slots__ = ()

    def __new__(cls, left, top, width, height):
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
    
    def sim_box(self, other: 'Box', threshold: float = 0.8)->bool:
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
    
    def __add__(self, other: tuple) -> 'Box':
        if len(other) == 2:
            return Box(self.left + other[0], self.top + other[1], self.width, self.height)
        elif len(other) == 4:
            return Box(self.left + other[0], self.top + other[1], other[2], other[3])
        else:
            raise ValueError("other must be a tuple of length 2 or 4")

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

def b2p(
        r: Box, 
        offset: tuple[int, int] = (0, 0),
        resize: tuple[int, int] = (-1, -1)
    ) -> Tuple[int, int]:
    """基于左上角进行变换，返回点"""
    r_new = Box(
        r.left+offset[0],
        r.top+offset[1],
        resize[0] if resize[0]>0 else r.width,
        resize[1] if resize[1]>0 else r.height
    )
    return dp(r_new)
