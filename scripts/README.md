# scripts 目录约定

本目录只保留当前源码主线需要的脚本。一次性实验脚本不要长期放在这里。

## 核心入口

| 脚本 | 作用 |
| --- | --- |
| `install.ps1` / `install.bat` | 安装依赖。默认 `all`，也支持 `tools`、`python`、`electron` |
| `run.ps1` / `run.bat` | 运行源码。支持 `webui` 和 `electron` |
| `update.ps1` / `update.bat` | `fetch origin main`，并把当前检出分支快进到 `origin/main` |

## 辅助脚本

- `launcher.ps1` / `launcher.bat`：兼容旧入口，只转发到运行脚本。
- `bootstrap-python310.ps1`：通过 uv 确保 Python 3.10.15 可用于 `.venv`。
- `collect_zmxy_redeem_2026.py`：4399 官方公告礼包码增量采集器，默认写入 `logs/zmxy_redeem_codes.json`。
- `run_safety_education.ps1` / `run_safety_education.bat`：手动运行历史安全教育脚本；只初始化 AutoScriptor 核心和模拟器控制，不启动 WebUI/Electron。

## 边界

- 安装脚本负责依赖，不启动应用。
- 运行脚本负责启动，不安装依赖。
- 更新脚本负责 Git 快进，不 stash/reset、不安装依赖、不启动应用。
- 发布器、安装器、CLI 菜单、Nuitka、Canvas、Socket.IO、打包验收脚本不属于当前主线。
