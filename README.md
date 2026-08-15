# AutoScriptor

AutoScriptor 是面向安卓模拟器的 Python 自动化任务编排项目。当前 `src` 分支只保留源码运行：源码 Electron 和源码 WebUI。

仓库作者：Kksp993  
仓库地址：https://github.com/kksp993/AutoScriptor

## 快速开始

```powershell
git clone https://github.com/kksp993/AutoScriptor.git
cd AutoScriptor
.\scripts\install.bat
.\scripts\run.bat electron
```

只启动浏览器 WebUI：

```powershell
.\webui.bat
```

访问：

```text
http://127.0.0.1:5000
```

从远端 `main` 更新源码：

```powershell
.\scripts\update.bat
```

更新固定检查 `origin/main`，只在当前检出分支可快进时执行 `pull --ff-only`；本地领先时会显示远端没有可拉取提交和领先提交数。依赖变化后再运行 `.\scripts\install.bat`。

## 主线入口

| 场景 | 命令 |
| --- | --- |
| 安装全部依赖 | `.\scripts\install.bat` |
| 只装工具链 | `.\scripts\install.bat tools` |
| 只装 Python 依赖 | `.\scripts\install.bat python` |
| 只装 Electron 依赖 | `.\scripts\install.bat electron` |
| 源码 Electron | `.\scripts\run.bat electron` 或 `.\start.bat` |
| 源码 WebUI | `.\scripts\run.bat webui` 或 `.\webui.bat` |
| 直接跑后端 | `.\.venv\Scripts\python.exe -X utf8 services\webui\gui.py` |
| 源码更新 | `.\scripts\update.bat` |

安装脚本会按需准备 Git、Node.js LTS、uv、Python 3.10.15 `.venv`、`requirements.txt` 和 `webapp\node_modules`。直接进入 `webapp` 执行 `npm start` 前，必须先运行 `.\scripts\install.bat electron` 或手动 `npm install`。

## 目录

```text
AutoScriptor/          核心 API、识别、控制、路径、配置和日志
ZmxyOL/                游戏任务、导航、战斗流程和任务注册
services/core/         调度器、任务管理、运行上下文、源码更新
  services/webui/        FastAPI 后端、API 路由、静态 WebUI
  webapp/                源码 Electron 壳
  examples/              可选示例，不参与源码主运行链
  data/                  可编辑运行数据
logs/                  日志、错误归档、截图和运行缓存
scripts/               安装、运行、更新脚本
docs/AutoScriptor/     当前源码主线文档
```

关键数据位置：

```text
data/config.json              全局配置
data/config.template.json     配置模板
data/accounts/                账号、角色、任务配置和状态
data/custom_task/             用户自定义任务
data/battle_character/        用户职业脚本
logs/                         日志、错误归档、截图和礼包码缓存
```

首次缺少配置时：

```powershell
Copy-Item "data\config.template.json" "data\config.json"
```

## 文档

- [架构基线](docs/AutoScriptor/architecture.md)
- [安装与运行](docs/AutoScriptor/INSTALL.md)
- [文档索引](docs/AutoScriptor/README.md)
- [WebUI API 契约](docs/AutoScriptor/webui/api-contract.md)
- [任务编写约定](docs/AutoScriptor/tasks/script-authoring.md)
- [OpenAI 多智能体示例](docs/AutoScriptor/reference/openai-multi-agents.md)

## 常见问题

Electron 找不到 `electron.exe`：运行 `.\scripts\install.bat electron`，它会在 `webapp` 执行 `npm install`。

WebUI 无法访问：确认 `webui.bat`、`scripts\run.bat webui` 或 Electron 后端正在运行，端口 `5000` 未被占用，并查看 `logs/`。

MuMu 连接失败：检查 `data/config.json` 中的 `emulator.adb_addr`、`emulator.emu_path`、`emulator.adb_path`，再通过 WebUI 启动诊断分层排查 Manager、ADB、App、NemuIpc、OCR、UI Map。

任务执行失败：优先看 `logs/log/`、`logs/errors/` 和 `logs/debug_screenshot/`。

## 免责声明

本项目仅供学习交流。使用本项目产生的风险由使用者自行承担。
