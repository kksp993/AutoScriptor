# 测试目录

统一用 unittest（没有 pytest 依赖）：

```powershell
# 全量
.venv\Scripts\python.exe -X utf8 -m unittest discover -s test

# 单个文件
.venv\Scripts\python.exe -X utf8 -m unittest test.webui.test_overview_projection

# 单个用例
.venv\Scripts\python.exe -X utf8 -m unittest test.integration.test_server_smoke.WebUIServerSmokeTest.test_local_projection_endpoints_answer_cleanly
```

## 结构

测试按被测边界分域；每个自动测试域都是带 `__init__.py` 的 Python 包，
手工实验和运行器单独放在 `manual/`，不混入自动测试发现路径。

| 位置 | 覆盖内容 |
| --- | --- |
| `accounts/` | 账号、角色和跨角色调度队列 |
| `device/` | MuMu、ADB、Nemu IPC、桌面控制、分辨率和输入通道 |
| `framework/` | 公共 API、安装兼容性、wheel、日志和配置写入防线 |
| `integration/` | 真启动 WebUI 子进程的接口冒烟测试及其辅助进程 |
| `notifications/` | QQ/OneBot 通知、机器人安装和安全密码后的自动启动 |
| `orchestration/` | 调度器、任务执行生命周期、重试、持久化竞态和日志可观测性 |
| `performance/` | 后台监控和战斗性能相关契约 |
| `recognition/` | OCR、识别缓存、识别追踪、UI 资产和系统弹窗护栏 |
| `runtime/` | 核心 API、设备生命周期、回放和安全边界 |
| `task_domain/` | 任务注册/参数、任务脚本、战斗业务和任务级回归 |
| `webui/` | WebUI 路由、投影、设置、编辑器和资讯接口 |
| `manual/security_education/` | 实验室安全教育脚本与受控运行器；需要真实账号/设备，不进 unittest |
| `manual/qq/` | 远程 QQ 机器人离线脚本，不进 unittest |
| `fixtures/` | 测试用的静态数据（如识别基线清单） |

## 两类需要真环境的测试

- `integration/test_server_smoke.py` 会**真的起一个 WebUI 子进程**（临时数据目录 +
  随机空闲端口），把全部无参 GET 端点打一遍，用来抓「只在运行期暴露」的缺陷。
  默认参与全量测试，约 5 秒；不想跑时设 `AUTOSCRIPTOR_SKIP_SERVER_SMOKE=1`。
- `framework/test_wheel_packaging.py` 会**真的构建两个 wheel 并把它们摊成安装树**，再起一个子进程
  从仓库外导入。默认参与全量测试，约 8 秒；不想跑时设 `AUTOSCRIPTOR_SKIP_WHEEL_PROBE=1`。
- 需要模拟器/OCR 的测试（`device/test_nemu_ipc_*.py`、`recognition/test_ocr_*.py` 等）只做离线断言，
  真机验证走 `docs/agents/online-screenshot-test.md` 的流程。
- `recognition/test_system_dialog_guard.py` 的误报用例会读 `logs/**/debug_screenshots/*.png` 归档截图跑真 OCR。
  `logs/` 随真实运行累积（单机已见过 1 万张以上），用例只取**最近 24 张**并逐张解码：
  整批读进内存约 28GB，会把测试进程压成 OOM，整个套件拿不到汇总。
- 真设备、真 venv 的**发布验收**不在这个目录：它在 `release_probe/`（只装
  `dist/autoscriptor-*.whl`，跑点击/识别/4399 部分操作），手动执行，跑一次几分钟。

## 写新测试时

- 用例只依赖被测模块的公开契约；需要替身时替换**模块引用**，别改全局单例的方法
  （内建类型的属性不可 patch，而且会污染同进程的其他测试）。
- 文件头写清楚「这个文件钉住什么」；抓过真实事故的用例把事故写进 docstring。
- 端点清单类测试（如冒烟测试的分类集合）要求新增端点显式归类，别用通配跳过。
