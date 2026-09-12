from __future__ import annotations

import sys
from pathlib import Path




PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from AutoScriptor import *
from ZmxyOL import *
from test.scripts.开号脚本.创号脚本 import longgong1
from test.scripts.开号脚本.创号战斗脚本1 import register_account_battle_flow


if __name__ == "__main__":
    register_account_battle_flow()
    init()
    longgong1(91, ensure_drug=False, flow_name="速刷1")




