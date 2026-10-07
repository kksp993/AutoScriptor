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

启动脚本会挑一个空闲端口并把它打印出来（默认 `5000`），照那个地址访问即可。
想固定端口用 `.\webui.bat -Port 8080`，或设置环境变量 `AUTOSCRIPTOR_PORT`。

从远端 `main` 更新源码：

```powershell
.\scripts\update.bat
```

更新固定检查 `origin/main`，只在当前检出分支可快进时执行 `pull --ff-only`；本地领先时会显示远端没有可拉取提交和领先提交数。依赖变化后再运行 `.\scripts\install.bat`。

## 主线入口

| 场景　　　　　　　 | 命令　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| --------------------| -----------------------------------------------------------|
| 安装全部依赖　　　 | `.\scripts\install.bat`　　　　　　　　　　　　　　　　　 |
| 只装工具链　　　　 | `.\scripts\install.bat tools`　　　　　　　　　　　　　　 |
| 只装 Python 依赖　 | `.\scripts\install.bat python`　　　　　　　　　　　　　　|
| 只装 Electron 依赖 | `.\scripts\install.bat electron`　　　　　　　　　　　　　|
| 源码 Electron　　　| `.\scripts\run.bat electron` 或 `.\start.bat`　　　　　　 |
| 源码 WebUI　　　　 | `.\scripts\run.bat webui` 或 `.\webui.bat`　　　　　　　　|
| 直接跑后端　　　　 | `.\.venv\Scripts\python.exe -X utf8 backend\webui\gui.py` |
| 源码更新　　　　　 | `.\scripts\update.bat`　　　　　　　　　　　　　　　　　　|

安装脚本会按需准备 Git、Node.js LTS、uv、Python 3.10.15 `.venv`、`requirements.txt` 和 `frontend\electron\node_modules`。直接进入 `frontend\electron` 执行 `npm start` 前，必须先运行 `.\scripts\install.bat electron` 或手动 `npm install`。

## 目录

```text
AutoScriptor/          自动化核心：设备控制、识别/OCR、配置、路径、日志
ZmxyOL/                游戏业务：账号、角色、导航、战斗流程
tasks/                 任务脚本：@register_task 实现与任务运行时状态
orchestrator/          编排：定时、排序、跨角色派发、执行闸门、重试
backend/               后端：core/ 运维 + webui/ FastAPI 服务与静态页面
frontend/electron/     Electron 桌面壳
data/                  可编辑运行数据
logs/                  日志、错误归档、截图和运行缓存
scripts/               安装、运行、更新脚本
docs/                  项目文档
```

关键数据位置：

```text
data/config.json              全局配置
data/config.template.json     配置模板
data/accounts/                账号、角色、任务配置和状态
data/custom_task/             用户自定义任务
data/character/        用户职业脚本
logs/                         日志、错误归档、截图和礼包码缓存
```

首次启动不需要手动建 `data\config.json`：缺少它时会用 `data\config.template.json` 的默认值，
在界面里改设置会按需生成。完整的新手步骤见 [从零开始](docs/AutoScriptor/GETTING-STARTED.md)。

## 文档

- [架构基线](docs/AutoScriptor/architecture.md)
- [从零开始](docs/AutoScriptor/GETTING-STARTED.md)
- [安装与运行](docs/AutoScriptor/INSTALL.md)
- [文档索引](docs/AutoScriptor/README.md)
- [WebUI API 契约](docs/AutoScriptor/webui/api-contract.md)
- [任务编写约定](docs/AutoScriptor/tasks/script-authoring.md)
- [OpenAI 多智能体示例](docs/AutoScriptor/reference/openai-multi-agents.md)

## 常见问题

Electron 找不到 `electron.exe`：运行 `.\scripts\install.bat electron`，它会在 `frontend\electron` 执行 `npm install`。

WebUI 无法访问：确认 `webui.bat`、`scripts\run.bat webui` 或 Electron 后端正在运行，并查看 `logs/`。
端口被别的软件占用时会自动顺延并在窗口里说明，所以**认命令行打印的那个地址**；
如果双击后提示「已经在运行」，说明上一次的实例还开着。

MuMu 连接失败：检查 `data/config.json` 中的 `emulator.adb_addr`、`emulator.emu_path`、`emulator.adb_path`，再通过 WebUI 启动诊断分层排查 Manager、ADB、App、NemuIpc、OCR、UI Map。

任务执行失败：优先看 `logs/log/`、`logs/errors/` 和 `logs/debug_screenshot/`。

## 免责声明

本项目仅供学习交流。使用本项目产生的风险由使用者自行承担。
