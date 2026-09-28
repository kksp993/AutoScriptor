# scripts 目录约定

本目录只保留当前源码主线需要的脚本。一次性实验脚本不要长期放在这里。

## 核心入口

| 脚本 | 作用 |
| --- | --- |
| `install.ps1` / `install.bat` | 安装依赖。默认 `all`，也支持 `tools`、`python`、`electron`、`qq`；`-WithQQ` 明确选装本机机器人 |
| `run.ps1` / `run.bat` | 运行源码。支持 `webui`、`electron` 和本机 QQ 机器人 `qq` |
| `update.ps1` / `update.bat` | `fetch origin main`，并把当前检出分支快进到 `origin/main` |

## 辅助脚本

- `qq-robot-standalone/`：另一台 Windows 电脑专用的独立 QQ 机器人安装/启动脚本。
  整个文件夹可单独复制，不依赖本仓库或 Python/npm；按指定 LAN/VPN IP 配置消息接口和来源防火墙，
  管理页仍只监听回环。见 [独立部署步骤](qq-robot-standalone/README.md)。
- `launcher.ps1` / `launcher.bat`：兼容旧入口，只转发到运行脚本。
- `bootstrap-python310.ps1`：通过 uv 确保 Python 3.10.15 可用于 `.venv`。
- `collect_zmxy_redeem_2026.py`：4399 官方公告礼包码增量采集器，默认写入 `logs/zmxy_redeem_codes.json`。
- `run_safety_education.ps1` / `run_safety_education.bat`：手动运行历史安全教育脚本；只初始化 AutoScriptor 核心和模拟器控制，不启动 WebUI/Electron。

## 边界

- 安装脚本负责依赖，不启动应用。
- `install.bat qq` 安装校验后的官方 NapCat 独立包，生成本机 HTTP 配置；`run.bat qq` 单独启动，
  首次登录需人工扫码。在 WebUI 的 QQ 通知页点击“使用本机配置”完成地址和令牌交接。
  详细边界见 [QQ 通知](../docs/AutoScriptor/operations/qq-notifications.md)。
- 运行脚本负责启动，不安装依赖。
- 更新脚本负责 Git 快进，不 stash/reset、不安装依赖、不启动应用。
- 发布器、安装器、CLI 菜单、Nuitka、Canvas、Socket.IO、打包验收脚本不属于当前主线。
