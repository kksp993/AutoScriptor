# 两个可安装 wheel

仓库除了源码运行，还能构建两个纯 Python wheel。装完之后不拿源码也能写脚本：
`from AutoScriptor import *` 拿框架，`from ZmxyOL import *` 拿游戏层。

```text
dist/autoscriptor-<版本>-py3-none-any.whl   框架层，只含 AutoScriptor/
dist/zmxyol-<版本>-py3-none-any.whl         游戏层，含 ZmxyOL/ 与 tasks/，依赖前者
```

框架层的 `readme` 指向 `AutoScriptor/README.md`（包自己的 README，随 wheel 一起发布，
构建时写成 METADATA 的正文）；框架的运行时依赖同时写在 `pyproject.toml` 的
`[project].dependencies`（打包唯一出处）和 `AutoScriptor/requirements.txt`（给从源码装的人），
`test/framework/test_framework_public_api.py` 校验两者与 `__all__` 都不漂移。

## 构建

```powershell
.venv\Scripts\python.exe -X utf8 scripts\build_wheels.py
```

`dist/` 在 `.gitignore` 里，不提交。版本号只有 `pyproject.toml` 的 `[project] version`
一个来源，`zmxyol` 的 `Requires-Dist` 钉同一版本，防止两个包错位。

## 发布验收（release_probe）

打包之后、对外发布之前，用 `release_probe/` 验一遍「这个 wheel 别人拿到能不能用」：

```powershell
.\release_probe\run_probe.ps1
```

它建一个只装这一个 wheel 的独立 venv（数据根也在探针自己的目录里），跑：
安装位判据（导入落在 venv 内、仓库根不在 `sys.path`）、公共 API 全部可解析、
空数据根下的配置自举（自动发现 MuMu 并认出已连接实例）、真机截图/识别/点击、
以及「4399 优惠券」的部分操作（只导航识别，不领券）。判据与产物见
[release_probe/README.md](../../../release_probe/README.md)。

`test/framework/test_wheel_packaging.py` 的安装树导入探针进全量测试（秒级、不碰设备），盯的是打包内容
与 `RECORD` 哈希；`release_probe/` 是手动、真设备、真 venv 的发布验收，两者不重复。

## 安装

```powershell
uv pip install --python .venv\Scripts\python.exe dist\autoscriptor-<版本>-py3-none-any.whl
uv pip install --python .venv\Scripts\python.exe dist\zmxyol-<版本>-py3-none-any.whl
```

换一台机器或别人的环境时，把两个 whl 放进同一个目录一次装完，让解析器就地找到依赖：

```powershell
uv pip install --find-links dist zmxyol
```

## 写脚本

装完这两个包，下面这份文件放哪都能跑（不依赖仓库）：

```python
import os
from pathlib import Path

# 配置、账号、职业脚本、日志都落在这里。不设的话会落到 site-packages 边上。
os.environ.setdefault(
    "AUTOSCRIPTOR_DATA_DIR", str(Path(__file__).resolve().parent / "runtime")
)

from AutoScriptor import *
from ZmxyOL import *

init()                                     # 连模拟器、起 OCR、进入游戏
print("分辨率:", getFrameSize())

click(T("确定"), if_exist=True)
swipe(B(600, 500, 100, 100), B(600, 200, 100, 100))
sleep(0.5)
```

要在安装位上继续用 `@register_task` 写正式任务，把文件放到名为 `custom_task/` 的目录下即可，
显示路径规则与源码位一致（见 [任务脚本编写](../tasks/script-authoring.md#注册位置)）。

## 什么在里面，什么不在

| 发行体 | 内容 | 依赖 |
| --- | --- | --- |
| `autoscriptor` | `AutoScriptor/`。框架层不 import 游戏层，所以里面没有 `ZmxyOL/` | `pyproject.toml` 里那 13 条运行时依赖 |
| `zmxyol` | `ZmxyOL/`（含 `assets/` 的 `ui_map.csv` 与 335 张参考图）、`tasks/`、`ZmxyOL/character/_default_impl/hero.py` | `autoscriptor==<同一版本>` |

编排层、后端和前端（`orchestrator/`、`backend/`、`frontend/`）不进 wheel，它们仍然只从源码树运行。
这两个包给的是「写脚本」的能力，不是「跑整套 WebUI」的能力。

### 为什么 `tasks/` 跟 `ZmxyOL/` 同一个发行体

两者互相依赖：`ZmxyOL/__init__.py` 惰性重导出 `tasks.register_task`，而
`tasks/task_register.py` 又跑 `from ZmxyOL import *`。拆成两个发行体会得到一对循环依赖，
而且单独装任何一个，`from ZmxyOL import *` 都会在解析 `register_task` 时导入失败。

### 战斗实现为什么随包一份

`ZmxyOL/character/hero.py` 是导入入口，真正的 Hero 与战斗流程代码在
`data/character/hero.py`，源码位靠它保持「只有一份可编辑实现」。安装位没有这棵数据树，
所以构建时把该文件原样放进 `ZmxyOL/character/_default_impl/hero.py`。运行时优先用可编辑副本，
它的 `_resolve_impl_path()` 与 `ZmxyOL/character/pros/` 的内置职业扫描共同保证：

- 源码位：永远读 `data/character/hero.py`，随包副本不被使用。
- 安装位：读随包副本，`ZmxyOL/character/pros/liuli.py` 这类内置职业同样可用。
- 装完之后用户想改战斗逻辑，在 `AUTOSCRIPTOR_DATA_DIR/character/hero.py` 放一份即可覆盖。

顺带一条约束：`data/character/` 与 `ZmxyOL/character/pros/` 里同名的职业脚本，后者先加载、
前者覆盖，所以用户脚本始终可以盖掉内置职业。

## 这块的验收

`test/framework/test_wheel_packaging.py` 覆盖构建、内容、`RECORD` 哈希、两次构建字节一致，并且真的把
wheel 摊成一个安装树、在仓库外用子进程导入一遍。不想跑这一步时设
`AUTOSCRIPTOR_SKIP_WHEEL_PROBE=1`。
