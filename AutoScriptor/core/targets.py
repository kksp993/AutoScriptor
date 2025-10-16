# auto_zmxy/core/targets.py
from abc import ABC
from typing import Union
from numpy import ndarray
import copy
from logzero import logger
from AutoScriptor.utils.box import Box
from AutoScriptor.recognition.img_rec import _load_cv2
    
class UiEntry:
    def __init__(self, name="Lambda_UiEntry", box: Box = None, img: ndarray = None, text: str = None, px_py: tuple = None, color:str = None):
        self.name = name
        self.img = img if isinstance(img, ndarray) else _load_cv2(img) if img else None
        self.text = text
        self.px_py = px_py
        self.box = box or Box(*px_py, 1, 1)
        self.color = color

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"UiEntry(name='{self.name}', prefered_box={self.box})" if self.text is None else f"UiEntry(text='{self.text}', prefered_box={self.box})"

    def set_box(self, box:Box):
        # 返回具有新 box 属性的新对象，而不改变原对象
        new_self = copy.copy(self)
        new_self.box = box
        return new_self
    
    def set_color(self, color:str):
        new_self = copy.copy(self)
        new_self.color = color
        return new_self

    @property
    def t(self) -> 'TextTarget':
        return TextTarget(self)

    @property
    def i(self) -> 'ImageTarget':
        return ImageTarget(self)

    @property
    def b(self) -> 'BoxTarget':
        return BoxTarget(self.box)


def ui_str(s:str, box:Box=None, color:str=None):
    return UiEntry(text=s, box=box if box is not None else Box(0,0,1280,720), color=color)

def ui_point(box:Box=None, x:int=None, y:int=None):
    return UiEntry(
        box=box if box is not None else Box(x, y, 1, 1),
        px_py=(x, y) if x is not None and y is not None else None, 
    )

class Target(ABC):
    pass

class ImageTarget(Target):
    def __init__(self, ui: Union[str, UiEntry], confidence: float = 0.8):
        self.ui = ui
        self.confidence = confidence

    def get_source(self): 
        if isinstance(self.ui, UiEntry):
            return self.ui.img
        return self.ui

    def __repr__(self):
        name = self.ui.name if isinstance(self.ui, UiEntry) else self.ui
        return f"I({name})" \
            f"{'@['+str(self.ui.box)+']' if self.ui.box!=Box(0,0,1280,720) else ''}" \
            f"{'#' + self.ui.color if self.ui.color else ''}"

    def set_box(self, box:Box):
        return ImageTarget(self.ui.set_box(box))

    def set_color(self, color:str):
        return ImageTarget(self.ui.set_color(color))


class TextTarget(Target):
    def __init__(self, ui: Union[str, UiEntry], is_regex: bool = False):
        self.ui = ui
        self.is_regex = is_regex

    def __repr__(self): 
        return f"T('{self.ui.text}'{', regex=' + self.is_regex if self.is_regex else ''})" \
            f"{'@['+str(self.ui.box)+']' if self.ui.box!=Box(0,0,1280,720) else ''}" \
            f"{'#' + self.ui.color if self.ui.color else ''}"


    def get_source(self): 
        if isinstance(self.ui, UiEntry):
            return self.ui.text
        return self.ui

    def set_box(self, box:Box):
        return TextTarget(self.ui.set_box(box))

    def set_color(self, color:str):
        return TextTarget(self.ui.set_color(color))

class BoxTarget(Target):
    def __init__(self, box: Box, color: str = None):
        # 支持统一访问：boxtarget.ui.box，并记录颜色
        self.box = box
        self.color = color
        self.ui = self

    def __repr__(self):
        return f"B({self.box})"

def B(x, y=None, w=0, h=0, color=None):
    from AutoScriptor.utils.ui_map import ui
    # 支持通过 color 关键字指定颜色筛选
    if isinstance(x, Box):
        return BoxTarget(x, color)
    if isinstance(x, str):
        entry = ui[x]
        if color is not None:
            entry = entry.set_color(color)
        return entry.b
    box = Box(x, y, w, h)
    return BoxTarget(box, color)

def I(key,*,box=Box(0,0,1280,720),color=None):
    from AutoScriptor.utils.ui_map import ui
    return ui[key].set_box(box).set_color(color).i

def T(text=None, *, key=None,box=Box(0,0,1280,720),color=None):
    from AutoScriptor.utils.ui_map import ui
    if isinstance(key,str):
        return ui[key].set_box(box).set_color(color).t
    return ui_str(text).set_box(box).set_color(color).t
