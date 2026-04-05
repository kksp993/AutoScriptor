from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

def ensure_server(server_name:str):
    switch_base("mumu")
    cur_server = extract_info(B(1007,49,232,30), post_process=lambda s: s.strip().replace("（","(").split("(")[0], ensure_not_empty=True)
    if cur_server != server_name:
        click(T("服务器", box=Box(1110,663,132,34).margin()))
        wait_for_appear(T("更换服务器", box=Box(532,110,217,38).margin()))
        while ui_F(T(server_name)):
            swipe(B(482,494), B(482,224))
        click(T(server_name))
        if server_name != extract_info(B(1007,49,232,30), post_process=lambda s: s.strip().replace("（","(").split("(")[0], ensure_not_empty=True):
            raise Exception(f"当前服务器不是{server_name},当前服务器是{cur_server},请检查服务器是否正确")

def ensure_character(character_name:str):
    click(B(104,16,60,26))
    if ui_F(T(character_name, box=Box(17,54,254,433).margin())):
        click(B(104,516,63,26))
    if ui_F(T(character_name, box=Box(17,54,254,433).margin())):
        raise Exception(f"角色{character_name}不存在,请检查账户服务器是否正确")
    click(T(character_name, box=Box(17,54,254,433).margin()))

if __name__ == "__main__":
    try:
        # swipe(I("法宝-戮仙剑"),I("炼丹炉-进阶-添加装备"),duration_s=2)
        init()
        ensure_server("兽神峰")
        ensure_character("可莉不知道哦")

    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)