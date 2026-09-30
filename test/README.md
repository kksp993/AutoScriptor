# 测试目录

统一用 unittest（没有 pytest 依赖）：

```powershell
# 全量
.venv\Scripts\python.exe -X utf8 -m unittest discover -s test

# 单个文件
.venv\Scripts\python.exe -X utf8 -m unittest test.test_webui.test_overview_projection

# 单个用例
.venv\Scripts\python.exe -X utf8 -m unittest test.test_webui.test_server_smoke.WebUIServerSmokeTest.test_local_projection_endpoints_answer_cleanly
```

## 结构

根目录的 `test_*.py` 按功能域平铺；同一功能域用例变多时收进同名包（带 `__init__.py`）：

| 位置 | 覆盖内容 |
| --- | --- |
| `test_webui_contracts.py` | WebUI 契约总表：API 路由存在性、前端源码断言、配置模板契约 |
| `test_webui/` | WebUI 域细分用例：`test_overview_projection.py`、`test_deploy_settings.py`、`test_server_smoke.py` |
| `test_accounts/` | 账号域：`test_dispatch_queue_defaults.py` |
| `test_task_register/` | 任务注册、reload 保留清单、cfg 解耦 |
| `test_tasks/` | 任务脚本约定（路径、注册顺序） |
| `fixtures/` | 测试用的静态数据（如识别基线清单） |

## 两类需要真环境的测试

- `test_webui/test_server_smoke.py` 会**真的起一个 WebUI 子进程**（临时数据目录 +
  随机空闲端口），把全部无参 GET 端点打一遍，用来抓「只在运行期暴露」的缺陷。
  默认参与全量测试，约 5 秒；不想跑时设 `AUTOSCRIPTOR_SKIP_SERVER_SMOKE=1`。
- 需要模拟器/OCR 的测试（`test_nemu_ipc_*.py`、`test_ocr_*.py` 等）只做离线断言，
  真机验证走 `docs/agents/online-screenshot-test.md` 的流程。

## 写新测试时

- 用例只依赖被测模块的公开契约；需要替身时替换**模块引用**，别改全局单例的方法
  （内建类型的属性不可 patch，而且会污染同进程的其他测试）。
- 文件头写清楚「这个文件钉住什么」；抓过真实事故的用例把事故写进 docstring。
- 端点清单类测试（如冒烟测试的分类集合）要求新增端点显式归类，别用通配跳过。
