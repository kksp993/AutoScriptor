from functools import partial
from numpy import sign
from AutoScriptor import *


HAS_SHIJIEDITU = ["村庄", "天庭", "极北", "极北村庄", "地狱", "洪荒遗境"]
SHIJIEDITU_CANTO_DICT = {
    "天庭": I("世界地图-天庭"),
    "极北": I("世界地图-极北"),
    "地狱": T("炼狱"),
    "极北村庄": T("极北村庄"),
    "村庄": T("村庄",box=Box(0,500,160,220)),
    "洪荒遗境": T("洪荒遗境"),
}
SHIJIEDITU_CANTO=list(SHIJIEDITU_CANTO_DICT.keys())
HAS_SHEZHI = ["村庄", "极北村庄"]
LOC_ENV = "__LOC_ENV__"



def swipe_up_down(from_idx:int, to_idx:int):
    for _ in range(abs(from_idx-to_idx)):
        swipe(B(10,350-sign(from_idx-to_idx)*250,0,0), B(10,350+sign(from_idx-to_idx)*250,0,0), duration_s=1)

def swipe_left_right(from_idx:int, to_idx:int):
    for _ in range(abs(from_idx-to_idx)):
        swipe(B(650-sign(from_idx-to_idx)*350,500,0,0), B(650+sign(from_idx-to_idx)*350,500,0,0), duration_s=1)


def LOC_INDEX_TRAV(env:str, fn:callable):
    from ZmxyOL.nav.map_manager import mm, path
    loc_arr = [(loc_name,int(loc_name.split("#")[1])) for loc_name in mm.locs.keys() if loc_name.startswith(env+"#")]
    loc_arr.append((LOC_ENV, 0))
    for from_loc, from_idx in loc_arr:
        for to_loc, to_idx in loc_arr:
            if from_loc == to_loc: continue
            path(from_loc, to_loc)(partial(lambda from_idx, to_idx:fn(from_idx, to_idx), from_idx=from_idx, to_idx=to_idx))



