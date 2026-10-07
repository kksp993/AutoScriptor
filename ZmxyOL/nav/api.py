"""
导航服务
提供ensure_in、try_get_region、way_to_region等核心导航功能

新版本特点：
- 使用函数式调用替代TaskBuilder模式
- 直接使用AutoScriptor核心API
- 简化参数传递，移除ctx上下文依赖
- 保持核心功能不变，提高代码可读性
"""

from AutoScriptor import *
import AutoScriptor.core.api as _core_api
from AutoScriptor.core.api import ui_idx
from ZmxyOL.nav.envs.decorators import LOC_ENV
from .map_manager import mm
from AutoScriptor.logging.logger import logger
from typing import Any, Callable

def _flatten_identifiers(idfs: list[Any]) -> tuple[list[Any], list[list[Any]]]:
    """将混合单个或序列的 identifier 展平，并记录分组"""
    groups: list[list[Any]] = []
    flat: list[Any] = []
    for idf in idfs:
        items = list(idf) if isinstance(idf, (list, tuple)) else [idf]
        groups.append(items)
        flat.extend(items)
    return flat, groups

def _restore_flat_idx(flat_idx: int, groups: list[list[Any]]) -> int:
    """将展平索引映射回原始列表索引"""
    cum = 0
    for idx, group in enumerate(groups):
        if flat_idx < cum + len(group):
            return idx
        cum += len(group)
    return -1

def _check_idx(get_identifier: Callable[[str], Any], names: list[str]) -> int:
    """通用索引查找：展平 identifiers，定位，再还原原始索引"""
    idfs = [get_identifier(name) for name in names]
    flat, groups = _flatten_identifiers(idfs)
    flat_idx = ui_idx(tuple(flat))
    if flat_idx < 0: return -1
    res = _restore_flat_idx(flat_idx, groups)
    return res

def check_loc_idx(loc_list: list[str]) -> int:
    """检查多个位置：扁平化 identifier 并映射原始位置索引"""
    return _check_idx(lambda name: mm.locs.get(name).identifier, loc_list)

def check_env_idx(env_list: list[str]) -> int:
    """检查多个环境：扁平化 identifier 并映射原始环境索引"""
    return _check_idx(lambda name: mm.envs.get(name).identifier, env_list)


def locate_region(cnt = 0, check_only = False) -> tuple[str, str]:
    if cnt == 0:
        _core_api.mixctrl.app.launch(cfg["app"]["app_to_start"])
        sleep(2)
    """
        按优先级检查当前位置
    """
    cur_env, cur_loc = mm.get_region()
    logger.debug("# 1.1 检查当前ctx中的loc")
    if cur_loc and check_loc_idx([cur_loc]) >= 0:
        return mm.set_region(cur_env, cur_loc)
    
    logger.debug("# 1.2 检查当前ctx中的env")
    if cur_env and check_env_idx([cur_env]) >= 0:
        return mm.set_region(cur_env)
    
    logger.debug("# 1.3 检查所有env")
    idx = check_env_idx(list(mm.envs.keys()))
    if idx >= 0:
        return mm.set_region(list(mm.envs.keys())[idx])
    
    logger.debug("# 1.4 检查所有loc")
    loc_names = list(mm.locs.keys())
    idx = check_loc_idx(loc_names)

    if idx >= 0:
        loc_name = loc_names[idx]
        logger.debug("定位命中位置: %s", loc_name)
        loc = mm.locs[loc_name]
        return mm.set_region(loc.envs[0].name, loc.name)
    # 「未知」必须放在判定之后：否则第 1.4 步明明认出来了也报未知，
    # 错误归档会拿到一条假阴性。
    if check_only: return "当前位置未知"
    if cnt % 2 == 0:
        try_close_via_x()
    if cnt > 10:
        raise ValueError("无法找到当前位置，请检查环境是否正确")
    return locate_region(cnt + 1)

def ensure_in(tar_loc: str|list[str], idx:int|None|list[int]=None):
    """
    根据当前的env.loc，和目标位置的env.loc
    利用导航工具组装path，到达目的地
    """
    if tar_loc == LOC_ENV:
        tar_loc = mm.get_region()[0]
    elif idx is not None: 
        if isinstance(idx, list):
            assert len(idx) == len(tar_loc), "idx和tar_loc长度不一致"
            tar_loc = [tar_loc[i] + "#" + str(idx[i])  if idx[i] else tar_loc[i] for i in range(len(tar_loc))]
        else:
            tar_loc = tar_loc + "#" + str(idx) if idx else tar_loc
    cur_env, cur_loc = locate_region()
    tar_loc = mm.get_nearest_env(tar_loc)
    assert cur_env and cur_loc, "当前位置未设置，无法导航"
    tar_env = mm.locs[tar_loc].env().name
    mm.navigate_to(cur_env,cur_loc,tar_env,tar_loc)



# 会吞掉所有触控的系统模态框。锚点必须是弹窗独有的字串——不要用通用「确定」：
# 游戏里到处都是它，拿它当锚点会去点正常的确认弹窗。
_SYSTEM_DIALOG_ANCHORS = ("App启动超时", "App启动失败")
# MuMu 的系统框居中弹出，按钮在最后一行文字正下方、和窗口同一条中轴线上。
# 这两个数值是 2026-10-02 在 1280x720 实机上量出来的。
_SYSTEM_DIALOG_BUTTON_GAP = 35
_SYSTEM_DIALOG_BUTTON_SIZE = (80, 45)


def dismiss_system_dialogs() -> bool:
    """点掉会吞掉点击的系统模态框，返回是否点掉了一个。

    MuMu 在应用启动失败时弹的「App 启动失败 / 启动超时」是**模态**的：不点掉它，
    屏幕上任何点击都到不了游戏，任务表现为「页面一直不变」然后超时。2026-10-02
    有一轮 52 个任务因为这个弹窗连续失败，报错还都指向各自的第一步。

    只搜屏幕中央区域：这类框由模拟器居中弹出，而全帧 OCR 每次要多花好几秒，
    这段代码跑在「已经卡住」的恢复路径上，不值得为边缘位置付这个代价。
    """
    frame_width, frame_height = getFrameSize()
    center_region = Box(
        int(frame_width * 0.15), int(frame_height * 0.15),
        int(frame_width * 0.7), int(frame_height * 0.7),
    )
    # 所有锚点共用同一个搜索区，所以只做一次 locate：OCR 只跑一遍。分开查的话每个锚点
    # 都要单独 OCR 一次，实测 2 个锚点 6.6s，合成一次后减半。
    found_boxes = locate(
        tuple(T(anchor_text, box=center_region) for anchor_text in _SYSTEM_DIALOG_ANCHORS),
        assure_stable=False,
        is_simplify=False,
    ) or []
    # is_simplify=False 时每个锚点给的是「该锚点的全部命中」（list[Box] 或 None），
    # 默认的 is_simplify=True 只返回第一个命中的锚点，拿不到其余几个的位置。
    hits = [
        (box.top + box.height, anchor_text, box)
        for anchor_text, boxes_of_anchor in zip(_SYSTEM_DIALOG_ANCHORS, found_boxes)
        for box in (boxes_of_anchor or ())
    ]
    if not hits:
        return False

    # 取最靠下的那一行：它离按钮最近，标题行点不到按钮。
    _, anchor_text, anchor_box = max(hits, key=lambda hit: hit[0])
    logger.warning("检测到系统弹窗「%s」，点掉它：%s", anchor_text, anchor_box)
    button_width, button_height = _SYSTEM_DIALOG_BUTTON_SIZE
    click(B(
        frame_width // 2 - button_width // 2,
        anchor_box.top + anchor_box.height + _SYSTEM_DIALOG_BUTTON_GAP,
        button_width,
        button_height,
    ))
    sleep(0.5)
    return True


def try_close_via_x():
    """
    尝试关闭各种弹窗和等待加载完成
    """

    # 关闭目标列表
    close_targets = [
        (I("极北之地-取消"), I("极北之地-取消")),
        (T("我的队伍",box=Box(434,15,439,119)), B(1060,30,30,30)),
        (I("x"), I("x")),
        (I("x-in"), B(1061,178,39,47)),
        (I("菜单-宠物"), B(10,10)),
        # (T("回家", box=Box(29,656,77,54).margin()), T("回家", box=Box(29,656,77,54).margin())),
        (T("确认"), T("确认")),
        (T("返回地图"), T("返回地图")),
        (T("返回大厅"), T("返回大厅")),
        (T("副本奖励"), B(1061,172,47,50)),
    ]
    
    # 等待消失目标列表
    wait_for_disappear_targets = [
        I("加载中"),
        I("极北-加载中"),
        I("进入游戏中")
    ]
    
    click(B(0,0,))
    found = True
    while found:
        found = False
        # 模态框优先：它挡着底下所有东西，不先点掉，后面的关闭目标一个都点不动。
        if dismiss_system_dialogs():
            found = True
        tgts = tuple(target for target, _ in close_targets)
        idx = ui_idx(tgts)
        if idx >= 0:
            click(close_targets[idx][1], if_exist=True)
            found = True
            sleep(0.5)
        for target in wait_for_disappear_targets:
            while(ui_T(target)): 
                sleep(0.5)
                found = True
    
    return True 
