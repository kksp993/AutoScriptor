"""自定义任务调试探针。

data/custom_task 下必须在 @register_task 中传入 path_cn（cfg 中的中文路径，斜杠分隔）。
"""

from typing import Sequence

from ZmxyOL.nav.envs import login
from ZmxyOL.nav.api import ensure_in
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *
from AutoScriptor.utils.box_grid import indexof, make_box_grid


ROLE_SEPARATORS = ("：", ":", "/", "|")


def _available_roles() -> list[str]:
    roles: list[str] = []
    for server, characters in cfg.list_characters().items():
        if isinstance(characters, dict):
            roles.extend(f"{server}:{name}" for name in characters)
    return roles


def _split_role_name(user: str) -> tuple[str | None, str]:
    text = str(user).strip()
    for sep in ROLE_SEPARATORS:
        if sep in text:
            server, character = text.split(sep, 1)
            return server.strip(), character.strip()
    return None, text


def resolve_role(user: str) -> tuple[str, str]:
    """Resolve ``角色名`` or ``服务器:角色名`` against current account config."""

    server, character = _split_role_name(user)
    if not character:
        raise ValueError("角色名不能为空")

    characters = cfg.list_characters()
    if server:
        if server not in characters or character not in characters[server]:
            available = ", ".join(_available_roles()) or "无"
            raise KeyError(f"角色 '{server}:{character}' 不存在。当前账号可用角色: {available}")
        return server, character

    matches = [
        (srv, character)
        for srv, cmap in characters.items()
        if isinstance(cmap, dict) and character in cmap
    ]
    if not matches:
        available = ", ".join(_available_roles()) or "无"
        raise KeyError(f"角色 '{character}' 不存在。当前账号可用角色: {available}")
    if len(matches) > 1:
        options = ", ".join(f"{srv}:{name}" for srv, name in matches)
        raise ValueError(f"角色名 '{character}' 不唯一，请写成 服务器:角色名。候选: {options}")
    return matches[0]


def login_role(user: str) -> tuple[str, str]:
    """Switch config to the target role and enter the game."""

    server, character = resolve_role(user)
    active = cfg.active_character()
    if active.get("server") != server or active.get("name") != character:
        cfg.switch_character(server, character)
    ensure_in("登录")
    login()
    return server, character


def restore_role(server: str | None, character: str | None) -> None:
    """Restore the configured active role after a multi-role debug probe."""

    if not server or not character:
        return
    active = cfg.active_character()
    if active.get("server") == server and active.get("name") == character:
        return
    cfg.switch_character(server, character)
    ensure_in("登录")
    login()


def check_mail_reward():
    ensure_in("村庄")
    click(T("邮件", box=Box(33,45,868,74).margin()))
    click(T("键领取", box=Box(532,551,214,90).margin()))
    sleep(3)
    click(B(981,73,1,1))

def get_exchange_reward():
    ensure_in("村庄")
    click(T("好友", box=Box(832,90,53,26).margin()))
    click(T("交换记录", box=Box(574,116,157,52).margin()))
    sleep(1)
    click(B(356,255,1,1))
    sleep(2)
    while ui_T(T("交换中", box=Box(821,290,80,30).margin())):
        click(T("交换中", box=Box(821,290,80,30).margin()))
        # TODO: 这里未考虑不够时无法交换。
        click(T("确认交换", box=Box(529,407,181,68).margin()))
        sleep(1)
    sleep(1)
    click(B(979,67,1,1))

def check_inventory():
    """检查当前库存，返回一个列表，包含八戒、敖玥、嫦娥符咒的数量。"""
    ensure_in("村庄")
    click(T("好友", box=Box(832,90,53,26).margin()))
    sleep(1)
    click(B(853,282,1,1))
    click(T("交换", box=Box(737,613,101,50).margin()))
    click(B(592,276,79,79))
    targetid = ["八戒之符", "敖玥之符", "嫦娥之符"]
    grid = make_box_grid(Box(422,142,98,98), Box(422,142,436,211), row=2, col=4)
    res = locate([I(name, box=Box(422,142,436,211)) for name in targetid], timeout=3, assure_stable=False)
    res_idxs = indexof(grid, res)
    counts = extract_info(grid, digit_only=True)
    out = []
    for idx in res_idxs:
        if idx is None:
            out.append(0)
            continue
        r, c = idx
        out.append(counts[r][c] if counts[r][c] is not None else 1)
    click(B(927,77,1,1));sleep(1)
    click(B(955,183,1,1));sleep(1)
    click(B(981,66,1,1))
    return out

def peek(user: str) -> Sequence[int]:
    """Real Peek interface: login/switch to user and return [0, 1, 2] counts."""
    # 登录用户
    login_role(user)
    # 回收交换奖励
    get_exchange_reward()
    # 领取邮件奖励
    check_mail_reward()
    # 识别当前库存
    return check_inventory()

def exchange(from_user: str, to_user: str, give_id: str | int, take_id: str | int) -> None:
    # assert from_user==current_user
    active = cfg.active_character()
    current_user = f"{active.get('server')}:{active.get('name')}"
    assert current_user == from_user, f"当前角色 {current_user} 与交换发起者 {from_user} 不匹配"
    # 寻找正确的交换好友（假定全连接）
    ensure_in("村庄")
    click(T("好友", box=Box(832,90,53,26).margin()))
    sleep(1)
    friend_name = _split_role_name(to_user)[1]
    friend_box = Box(450,202,462,360).margin()
    friend_target = T(friend_name, box=friend_box)
    res = None
    for _ in range(30):
        res = locate(friend_target, timeout=0.5, assure_stable=False)
        if res is not None:
            break
        swipe(B(517,515,1,1), B(517,200,1,1))
        sleep(0.5)
    else:
        raise TimeoutError(f"好友 {to_user} 不在可交换列表中")
    box_grid = make_box_grid(Box(324,199,587,178), Box(335,202,587,361), row=2, col=1)
    res_idx = indexof(box_grid, res)
    assert res_idx is not None, f"好友 {to_user} 不在可交换列表中"
    click(T("战斗力", box=box_grid[res_idx[0]][0]), offset=(348,-2))
    click(T("交换",color="红色"))
    # 寻找交换物品
    click(B(592,276,79,79))
    click(I(str(give_id)))
    click(T("选择"))
    sleep(1)
    click(B(467,315,1,1))
    click(I(str(take_id)))
    click(T("选择"))
    sleep(1)
    click(T("确认交换", box=Box(549,405,182,70).margin()))
    sleep(1)
    click(B(981,66,1,1))

def merge(user: str) -> Sequence[int]:
    """一个示例性的 Merge 实现，先 Peek 再 Exchange。"""
    # assert from_user==current_user
    active = cfg.active_character()
    current_user = f"{active.get('server')}:{active.get('name')}"
    assert current_user == user, f"当前角色 {current_user} 与交换发起者 {user} 不匹配"
    
    click(T("活动", box=Box(267,141,62,96).margin()))
    sleep(1)
    swipe(B(927,171,1,1), B(394,171,1,1))
    click(T("典藏纹章", box=Box(755,179,114,32).margin()))
    swipe(B(753,539,1,1), B(753,360,1,1), duration_s=0.5)
    swipe(B(753,539,1,1), B(753,360,1,1), duration_s=0.5)
    click(T("幸运分享", box=Box(493,427,216,54).margin()))
    swipe(B(753,539,1,1), B(753,360,1,1), duration_s=0.5)
    swipe(B(753,539,1,1), B(753,360,1,1), duration_s=0.5)

    click(T("兑换", box=Box(463,343,581,312).margin()))
    click(T("确定", box=Box(569,513,140,78).margin()))
    click(B(1093,30,43,41))

@register_task(
    path_cn="自定义任务/调试/测试2",
    description="不操作游戏，用于验证自定义任务加载、参数注入和 debug 直跑链路。",
    task_doc=(
        "这是一个安全的自定义任务调试探针。默认只写日志，不点击、不截图、不改变游戏状态；"
        "打开 fail 可主动抛错，用来验证 debug_mode 下失败不会关闭或重启游戏。"
    ),
    debug_mode=True,
)
def test_task():
    original = cfg.active_character()
    tb={}
    try:
        users =[
            "兽神峰:可莉不知道哦",
            "兽神峰:青颖飞帆"
        ]
        # exchange(users[0], users[1], "八戒之符", "敖玥之符")
        peek(users[1])

    finally:
        restore_role(original.get("server"), original.get("name"))
    # fail = True
