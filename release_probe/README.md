# 框架层发布验收（release_probe）

这个目录回答一个问题：**把 `AutoScriptor/` 打成 wheel 之后，它能不能独立发布、独立使用。**

它只用一个 wheel：`dist/autoscriptor-<版本>-py3-none-any.whl`。不 import 仓库里的任何模块
（没有 `ZmxyOL`、没有 `tasks`、没有 `orchestrator`），运行数据也落在自己的目录里。

## 跑法

```powershell
.\release_probe\run_probe.ps1              # 建 venv、装 wheel、跑全部探针
.\release_probe\run_probe.ps1 -SkipBuild   # 复用 dist/ 里已有的 wheel
.\release_probe\run_probe.ps1 -OnlyDesktop # 只跑主机通道（不连模拟器）
```

脚本会：

1. 重新构建 wheel（`scripts/build_wheels.py`）；
2. 在 `release_probe\.venv` 建一个干净 venv，装这个 wheel + `requirements.txt` 里的 CPU Paddle；
3. 跑 `probe_framework.py` 与 `probe_desktop.py`，输出 `PROBE_OK / PROBE_FAIL` 行和最后的
   `PROBE_RESULT`。

脚本会在结束时**还原** `AUTOSCRIPTOR_DATA_DIR` / `PROBE_EVIDENCE_DIR`。这两个变量是进程级
的，不还原的话你当前这个 PowerShell 窗口会一直带着探针的数据根，接着跑仓库测试就会去
`release_probe\.runtime` 找账号与职业脚本，报出看着像代码坏了的导入错误（2026-10-12 踩到）。

## 判据

| 段 | 判据 | 说明 |
| --- | --- | --- |
| 安装位 | 导入来源在探针 venv 内、仓库根不在 `sys.path` | 证明没有偷偷用源码 |
| 公共 API | `__all__` 每个名字都能解析 | 星号导入会逐个解析，缺一个就报错 |
| 随包文档 | 安装树里有 `README.md`、`requirements.txt` | 发布体自带说明与依赖 |
| 配置自举 | 空数据根下自动发现 MuMu 路径、认出已连接实例、配置落盘 | 新机器上第一步就能走通 |
| 离线对象 | 帧尺寸合同、`Box`、`T("文字")`、网格工具 | 不需要设备的那部分 |
| 缺资产行为 | 按 key 的目标（`B("键名")`）报「缺游戏层资产」而不是裸 `KeyError` | 框架层不含 `ui_map.csv`，这是正常状态 |
| 真机基础 | 截图 720x1280、区域截图、`key_event`、`sleep` | 设备会话与输入通道 |
| 4399 部分操作 | 进游戏盒 → 认出首页 → 点「我的」→ 认出我的页 | **走到这里为止，不领券** |
| 主机通道 | DPI 感知、虚拟桌面、截屏尺寸、光标、窗口枚举 | 只读；不做桌面点击 |

资源说明：`4399 部分操作` 只做导航与识别，**不打开券列表、不点「领取」**。领券消耗当天次数，
属于用户资源，需要完整流程请直接跑仓库里的任务脚本。

## 产物

```text
release_probe\.venv\          探针专用 venv（gitignore）
release_probe\.runtime\       探针的数据根：config.json、logs（gitignore）
release_probe\.runtime\evidence\   探针存下的帧（gitignore）
```

`.runtime/config.json` 是探针自己的配置，与仓库的 `data/config.json` 无关；两者互不影响。

## 与 `test/framework/test_wheel_packaging.py` 的分工

- `test/framework/test_wheel_packaging.py` 进全量测试：把 wheel 摊成安装树、用 `PYTHONPATH` 起子进程导入，
  钉打包内容与 `RECORD` 哈希，**不碰设备**，秒级完成。
- `release_probe/` 是**手动**验收：真 venv、真安装、真设备，验证「发布出去别人能用」。
  它不参与 `unittest discover`，因为要模拟器、要装 Paddle，跑一次几分钟。
