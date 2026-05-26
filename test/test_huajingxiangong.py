from AutoScriptor import *
from ZmxyOL.nav import *
import traceback
index_list = ["零","一","二","三","四","五","六","七","八","九","十"]

# 化境相关 UI 格子：2 行 × 4 列，列起点统一 x=284，HUAJING_GRID_2x4[row][col]
_HJX_COL0 = 284
_HJX_DX, _HJX_DY = 210, 253
_HJX_W, _HJX_H = 195, 55
_HJX_ROW_Y0 = (164, 417)
HUAJING_GRID_2x4 = [
    [Box(_HJX_COL0 + c * _HJX_DX, _HJX_ROW_Y0[r], _HJX_W, _HJX_H) for c in range(4)]
    for r in range(2)
]

BASE_BOX=Box(494,164,195,55) # 基于这个计算其他格子
grid_offset={
    "price":Box(518,358,133,40)-BASE_BOX,
    "remains":Box(518,324,133,38)-BASE_BOX,
}





def init_HuaJing():
    click(T("化境", box=Box(1024,62,125,73).margin()))
    click(B(734,240,81,79))
    click((
        T("界·太初剑圣", box=Box(654,0,102,720).margin()),
        T("西王母", box=Box(654,0,102,720).margin())
    ))
    click(T("确认上阵", box=Box(561,547,163,66).margin()))
    diff_info = extract_info(B(975,422,117,49), post_process=lambda s: s.strip(), ensure_not_empty=True)
    assert diff_info, "化身上阵失败"
    click(T("前往挑战", box=Box(1051,632,219,73).margin()))
    click(T("确认", box=Box(669,411,182,85).margin()))



def shop(level:int):
    click(T("仙宫游商", box=Box(132,618,119,102).margin()))
    if level>1:
        click(T(f"{index_list[level]}境解锁", box=Box(120,75,102,498).margin()))
    click(T("秘宝", box=Box(556,106,123,49).margin()))
    def buy(item:str,max_limit:int=9999):
        row, cell, item_box = box_cell_in_grid(locate(T(item), timeout=10), HUAJING_GRID_2x4)
        assert item_box is not None, f"未找到物品: {item}"
        budget = extract_info(B(966,104,139,54), post_process=lambda s: int(s.strip()), ensure_not_empty=True)
        remains = extract_info(item_box+grid_offset["remains"], post_process=lambda s: int(s.strip()[-3]), ensure_not_empty=True)
        price = extract_info(item_box+grid_offset["price"], post_process=lambda s: int(s.strip()), ensure_not_empty=True)
        for _ in range(min(budget//price,remains,max_limit)):
            click(T("400", box=Box(711,352,175,57).margin()))
            click(B(585,286,107,108))
            click(T("确认", box=Box(667,437,211,79).margin()))
    buy("原初·化技秘宝")
    buy("原初·元级秘宝")
    wait_for_appear(T("装备", box=Box(284,106,136,47).margin()))
    click(B(1207,18,49,48))


def challenge_x(index:int):
    
    pass



if __name__ == "__main__":
    try:
        init()
        shop(1)

    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)