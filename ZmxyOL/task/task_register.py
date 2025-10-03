    
import inspect
import os
import traceback
from ZmxyOL import *
import enum
from AutoScriptor.utils.constant import cfg
from logzero import logger

# 在模块顶端添加全局计数器
registration_counter = 0

TRANSLATION_MAP = {
    # Directories:
    '一般任务': 'general_task',
    '日常任务': 'daily_task',
    '每周任务': 'weekly_task',
    '天庭': 'heavenly_court',
    '村庄': 'village',
    '极北': 'far_north',
    '极北地区': 'far_north_area',
    '极北村庄': 'far_north_village',
    '极寒深渊': 'frigid_abyss',
    '登录': 'login',  # Can be dir or file

    # Files:
    '梵天塔': 'brahma_pagoda',
    '返回开始': 'return_to_start',
    '地狱混沌': 'hell_chaos',
    '天庭混沌': 'heavenly_court_chaos',
    '组队任务': 'team_task',
    '仙宝挖掘': 'celestial_treasure_digging',
    '仙气消耗': 'celestial_qi_consumption',
    '仙盟建设': 'celestial_alliance_construction',
    '取经': 'scripture_seeking',
    '天选阁': 'pavilion_of_the_chosen',
    '妖兽': 'demon_beast',
    '宠物培养': 'pet_cultivation',
    '强化装备': 'equipment_enhancement',
    '战令领取': 'battle_pass_claim',
    '活跃券': 'activity_voucher',
    '竞技场': 'arena',
    '一键碾压': 'one_click_crush',
    '冰窟探险': 'ice_cave_exploration',
    '厄难副本': 'calamity_dungeon',
    '极北混沌': 'far_north_chaos',
    '混沌蛋': 'chaos_egg',
    '仙宝炼化': 'celestial_treasure_refining',
    '极光天诏': 'aurora_edict',
    '消费点券': 'coupon_spending',
    '极渊副本': 'abyssal_dungeon',
    '登录其他角色': 'login_other_characters',
    '冰窟商店': 'ice_cave_shop',
    '幽冥冰窟': 'nether_ice_cave',
    '荣耀之战': 'battle_of_glory',
}

TRANSLATION_MAP_REVERSE = {v: k for k, v in TRANSLATION_MAP.items()}

def translate_path_part(part):
    return TRANSLATION_MAP.get(part, None) or TRANSLATION_MAP_REVERSE.get(part, None)


def register_task(func):
    """
    A decorator that registers a function into the global 'menu' dictionary
    based on its file path relative to a 'task' directory.
    """
    global registration_counter  # 引入全局计数器
    registration_counter += 1
    reg_order = registration_counter  # 当前注册顺序
    try:
        # 1. Get the full path of the file where the function is defined
        #    e.g., 'C:\\Users\\...\\task\\日常任务\\天庭\\宠物培养.py'
        filepath = inspect.getfile(func)

        # 2. Normalize the path for cross-platform compatibility (e.g., handle \ vs /)
        #    and split it into components.
        #    e.g., ['C:', 'Users', ..., 'task', '日常任务', '天庭', '宠物培养.py']
        norm_path = os.path.normpath(filepath)
        path_parts = norm_path.split(os.sep)

        # 3. Find the index of the 'task' directory, which acts as our root.
        try:
            task_index = path_parts.index('task')
        except ValueError:
            print(f"Error: The 'task' directory was not found in the path for {func.__name__}. Registration failed.")
            return func

        # 4. Get all the parts after 'task' to use as keys.
        #    e.g., ['日常任务', '天庭', '宠物培养.py']
        keys = path_parts[task_index + 1:]

        # 5. The last key is the filename. Remove the '.py' extension.
        #    e.g., '宠物培养.py' -> '宠物培养'
        filename = keys[-1]
        task_name, _ = os.path.splitext(filename)
        keys[-1] = task_name

        # Store original keys for display before translating
        original_keys_for_display = keys[:]

        # New step: Translate keys from Chinese to English
        keys = [translate_path_part(key) for key in keys]

        # 6. Traverse the 'menu' dictionary, creating nested dictionaries if they don't exist.
        current_level = cfg["tasks"]
        for key in keys[:-1]: # Go up to the second-to-last key
            # setdefault is perfect here: it gets the value of the key if it exists,
            # otherwise it sets it to a new empty dict {} and returns that new dict.
            current_level = current_level.setdefault(key, {})

        # 7. At the final level, add the function and its status.
        last_key = keys[-1]
        if last_key in current_level:
            current_level[last_key]["fn"] = task_wrapper(func)
            current_level[last_key].setdefault('next_exec_time', 0)
            current_level[last_key]['order'] = reg_order  # 保存注册顺序
        else:
            current_level[last_key] = {'fn': func, 'on': True, 'next_exec_time': 0}
            current_level[last_key]['order'] = reg_order  # 保存注册顺序
        # 为任务添加参数配置
        sig = inspect.signature(func)
        defaults = {}
        param_meta = {}
        for name, param in sig.parameters.items():
            default = param.default if param.default is not inspect._empty else None
            # 枚举类型处理
            if isinstance(default, enum.Enum):
                # 单选枚举：存储枚举成员名称并记录类型元数据
                defaults[name] = default.name
                enum_path = default.__class__.__module__ + '.' + default.__class__.__qualname__
                param_meta[name] = enum_path
            # 多选枚举：列表中都是枚举成员
            elif isinstance(default, (list, tuple)) and default and all(isinstance(item, enum.Enum) for item in default):
                # 多选枚举（列表或元组中都是枚举成员），存储成员名称列表并记录类型元数据
                defaults[name] = [item.name for item in default]
                enum_path = default[0].__class__.__module__ + '.' + default[0].__class__.__qualname__
                param_meta[name] = enum_path
            else:
                # 其他类型或空列表
                defaults[name] = default
        task_cfg = current_level[last_key]
        existing_params = task_cfg.get('params', {})
        merged_params = defaults.copy()
        merged_params.update(existing_params)
        task_cfg['params'] = merged_params
        # 如果有枚举参数，保存类型元数据
        if param_meta:
            task_cfg['param_meta'] = param_meta
        a = {k:v for k,v in current_level[last_key].items() if k!= 'fn'}
        print(f"✅ 【{'/'.join(keys)}】 => {a}")
    except Exception as e:
        print(f"An error occurred during registration for {func.__name__}: {e}，{traceback.format_exc()}")

    # The decorator must return the original function
    return func


def task_wrapper(func):
    def wrapper(*args, **kwargs):
        from AutoScriptor.core.background import bg
        bg.clear(signals_clear=True)
        return func(*args, **kwargs)
    return wrapper
