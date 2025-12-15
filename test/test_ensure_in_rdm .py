import getpass
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback
import random

if __name__ == "__main__":
    cfg.load_config(getpass.getpass("请输入安全密码: "))
    locs = list(mm.locs.keys())
    
    # 记录已访问的地点，用于生成复现代码
    visited_locs = []
    
    try:
        # 获取当前位置作为起点（如果能获取到的话）
        start_env, start_loc = mm.get_region()
        if start_loc: visited_locs.append(start_loc)
        elif start_env: visited_locs.append(start_env)
        for i in range(10):
            loc = random.choice(locs)
            print(f"Target: {loc}")
            ensure_in(loc)
            visited_locs.append(loc)

    except Exception as e:
        traceback.print_exc()
        print("\n" + "="*20 + " 复现代码 " + "="*20)
        for loc in visited_locs:
            print(f'        ensure_in("{loc}")')
        print("="*50)
    finally:
        bg.stop()
        exit(0)
