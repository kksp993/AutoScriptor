# 实验室安全教育手工脚本

这里放需要真实账号、真实 MuMu 和人工确认页面状态的安全教育脚本。
它们不是 `unittest` 用例，不参加 `python -m unittest discover -s test`。

## 文件

- `lab_security.py`：固定坐标版学习时长脚本。
- `run_lab_security.py`：固定坐标脚本的受控 runner。
- `run_lab_security_table.py`：OCR 表格版 runner，带登录页、危险区、返回页和翻页护栏。
- `manual_anquan_2025.py`：旧版手工答题实验，只有明确需要时才运行。

## 安全边界

- runner 通过 `ensure_app_running(..., launch_app=False)` 建立设备会话，不启动配置中的游戏 App。
- runner 显式切换到 ADB 输入；脚本只在确认目标页面后点击，不盲点考试区或未知页面。
- 必须先用 `--probe` 或 `--max-items 1 --minutes 1` 做短验证，再安排长时间运行。
- 长时间运行必须设置硬超时；不要直接运行没有 runner 护栏的旧实验脚本。

示例：

```powershell
.venv\Scripts\python.exe -X utf8 test\manual\security_education\run_lab_security.py --probe
.venv\Scripts\python.exe -X utf8 test\manual\security_education\run_lab_security_table.py --dry-run --max-items 1 --minutes 1
```
