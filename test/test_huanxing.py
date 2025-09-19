from logzero import logger
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback
import re
from AutoScriptor import *

TEJI_NAMES=[
    "破魔","余力","欺凌","碾碎","重劲","反掌","穿石","武魂","连击"
]

HARD_OCR_NAMES=[
    "凝神","傲骨","穿石","连击","武魂","重劲","反掌","碾碎","欺凌","余力"
]








def extract_brackets_only(text: str):
    """只保留 [xxx] 格式的文字，智能修复缺失的右括号"""
    # 1. 修复缺失的右括号：在 [ 和 ， 之间如果没有 ]，则将首个非汉字字符替换为 ]
    def fix_missing_brackets(text):
        # 查找所有 [ 和 ， 的组合
        pattern = r'\[([^，\]]*)，'
        matches = re.finditer(pattern, text)
        # 从后往前替换，避免位置偏移问题
        positions_to_replace = []
        for match in matches:
            bracket_content = match.group(1)
            # 如果括号内容不为空且不包含 ]
            if bracket_content and ']' not in bracket_content:
                # 找到首个非汉字字符的位置
                for i, char in enumerate(bracket_content):
                    if not '\u4e00' <= char <= '\u9fff':  # 非汉字
                        # 记录需要替换的位置
                        positions_to_replace.append((match.start(1) + i, char))
                        break
        # 从后往前替换，避免位置偏移
        for pos, char in reversed(positions_to_replace):
            text = text[:pos] + ']' + text[pos+1:]
        return text
    
    # 2. 应用修复
    fixed_text = fix_missing_brackets(text)
    # 3. 提取所有 [xxx] 格式的内容
    matches = re.findall(r'\[[^\]]*\]', fixed_text)
    res = ' '.join(matches)
    for name in HARD_OCR_NAMES:
        if name not in res and name in text:
            res = res + f"[{name}]"
    return res


def get_teji():
    teji = extract_info(target=B(0,0,1280,720) ,post_process=extract_brackets_only)
    teji_expensive = any(x in teji for x in TEJI_NAMES) or teji.count("[")>1
    return teji, teji_expensive

def get_remains():
    energy = extract_info(B(1039,540,86,34), post_process=lambda x: int(x))
    xinhe = extract_info(B(558,585,123,45), post_process=lambda x: int(x.split("/")[0])//int(x.split("/")[1]))
    return min(energy, xinhe)


def get_teji_trans():
    old_tj = extract_info(B(371,281,63,26), post_process=lambda x: x.strip())
    new_tj = extract_info(B(697,281,63,26), post_process=lambda x: x.strip())
    return old_tj, new_tj

def get_xianqi(col, row):
    box = Box(422+col*112,142+row*112,99,99)
    shipin = (I("仙器-铃",box=box),I("仙器-盏",box=box),I("仙器-镜子",box=box))
    logger.info(f"({col},{row})装备具备特技: {shipin}")
    if ui_T(shipin):
        click(shipin)
        teji, teji_expensive = get_teji()
        click(B(1230,54,66,58))
        click(B(30,54,66,58))
        logger.info(f"({col},{row})装备具备特技: {teji}")
        logger.info(f"({col},{row})是否昂贵: {teji_expensive}")
        # 如果找到特技装备，设置ij值
        if teji_expensive:
            return (col, row)
    return None

def get_fw():
    # 初始化ij为None和计数器
    ij = None
    cnt = 0
    
    # 使用循环检查所有位置，找到后立即停止
    for cnt in range(16):
        # 计算当前的行列位置
        u = cnt % 4
        v = cnt // 4
        # 检查当前位置
        ij = get_xianqi(u, v)
        if ij is not None: break

    if ij is not None:
        click(B(422+ij[0]*112,142+ij[1]*112,99,99))
        click(T("选择"))
    else:
        logger.info("没有找到特技装备")



def choose_xianqi():
    click(B(192,316,112,116))
    while ui_F(ui["锻造-空格子"].i):
        swipe(Box(464+350,356,0,0), Box(464,356,0,0), 0.3)
    swipe(Box(464+50,356,0,0), Box(464,356,0,0), 0.3)
    get_fw()




if __name__ == "__main__":
    try:
        # if ui_idx((T('莫邪'),T("欧冶子")),30)==0:
        #     click(T('莫邪'),offset=(-230,100),resize=(80,120))
        # else:
        #     click(T('欧冶子'),offset=(-480,100),resize=(80,120))
        # click(T('锻造师'))
        # click(T('换形'))
        # if ui_F(T("装备",box=Box(194,321,104,106))):
        #     click(T("铸魂"))
        #     click(T('换形'))
        # click(T("装备",box=Box(194,321,104,106)))
        # wait_for_appear(T("选择装备"))
        # get_fw()

        teji = extract_info(target=B(0,0,1280,720) ,post_process=extract_brackets_only)
        logger.info(f"特技: {teji}")
        teji_expensive = any(x in teji for x in TEJI_NAMES) or teji.count("[")>1
        logger.info(f"是否昂贵: {teji_expensive}")


    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)