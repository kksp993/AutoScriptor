from functools import partial
from numpy import sign
from AutoScriptor import *


HAS_SHIJIEDITU = ["村庄", "极北", "极北村庄", "地狱"]
HAS_SHEZHI = ["村庄", "极北村庄"]
LOC_ENV = "__LOC_ENV__"


def swipe_up_down(from_idx:int, to_idx:int):
    for _ in range(abs(from_idx-to_idx)):
        swipe(B(10,350-sign(from_idx-to_idx)*250,0,0), B(10,350+sign(from_idx-to_idx)*250,0,0))

def LOC_INDEX_TRAV(env:str, fn:callable):
    from ZmxyOL.nav.map_manager import mm, path
    loc_arr = [(loc_name,int(loc_name.split("#")[1])) for loc_name in mm.locs.keys() if loc_name.startswith(env+"#")]
    loc_arr.append((LOC_ENV, 0))
    for from_loc, from_idx in loc_arr:
        for to_loc, to_idx in loc_arr:
            if from_loc == to_loc: continue
            path(from_loc, to_loc)(partial(lambda from_idx, to_idx:fn(from_idx, to_idx), from_idx=from_idx, to_idx=to_idx))



