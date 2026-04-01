# AutoScriptor

# 项目介绍
AutoScriptor 是一个基于 Python 的自动化脚本与任务编排器，专注于安卓模拟器（优先支持 MuMu）操作自动化。项目集成了图像识别、OCR 文本识别、任务调度等功能，提供 CLI 命令行和 WebUI 可视化两种管理方式，支持灵活配置和二次开发。

本项目集成了模拟器控制、OCR 识别、自动任务调度、错误归档等核心功能，支持灵活配置，可通过 CLI 或 Web 界面实现任务分组管理、状态查看和配置编辑。无需深厚的编程基础即可灵活添加、启用、编辑或禁用自动化任务。

## 主要特性

- **双模式管理**：支持 CLI 命令行界面和 WebUI 可视化界面两种操作方式
- **模拟器控制**：支持 MuMu 模拟器的点击、长按、滑动、输入、按键事件等操作
- **智能识别**：集成 PaddleOCR 文本识别和图像匹配，支持颜色采样、稳定性检测
- **任务编排**：按「每日 / 每周 / 一般 / 活动」分类管理任务，支持参数配置、执行后冷却与状态持久化
- **实时监控**：WebUI 通过 WebSocket 推送日志；CLI 提供交互式任务导航
- **错误处理**：自动归档错误日志和截图，便于问题排查
- **账号管理**：支持加密存储账号密码，安全可靠
- **扩展性强**：配置文件灵活易懂，便于自定义扩展至其他应用场景

适用于手游自动日常、批量重复操作等自动化场景，极大解放双手。

# 项目截图
![自动调度](https://cdn.nlark.com/yuque/0/2026/png/39311747/1774288723768-72c58996-e804-4f34-ba5d-c39836417ed2.png?x-oss-process=image%2Fformat%2Cwebp)
![图片编辑器](https://cdn.nlark.com/yuque/0/2026/png/39311747/1774288874655-3ee62550-c3a9-45ea-b85e-5aeefad54ce4.png?x-oss-process=image%2Fformat%2Cwebp)

# 参考项目
本项目参考并借鉴了以下优秀的开源项目，特此致谢：
- [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)
- [mumu-python-api](https://github.com/u-wlkjyy/mumu-python-api)
- [ZenlessZoneZero-OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)

# 免责声明
- 📌 本项目仅供学习交流，开发者团队保留最终解释权
- ⚖️ 使用本工具产生的一切风险需自行承担
- 🚫 本项目未授权任何个人、商家、自媒体账号等进行售卖
- 🚫 若您遇到商家使用本软件进行代练并收费，产生的任何问题及后果与本软件无关
- 🚫 开发者团队不会为您提供任何"售后"服务，作者及贡献者对任何人因使用本代码导致的任何损失、账号封禁或法律纠纷不承担任何直接或间接的责任。一切后果由使用者自行承担。

# 使用说明与配置指南

如需完整的入门到进阶与 API 参考，请查阅: [docs/AutoScriptor/API.md](docs/AutoScriptor/API.md)

**发行构建与日常运行**（`build_release.py` 参数、portable/NSIS、增量缓存、安装向导、`backend.zip` 与排错）：[docs/AutoScriptor/release-build-and-run.md](docs/AutoScriptor/release-build-and-run.md)

## 环境配置

**系统要求**：
- Windows 10/11
- MuMu 或 MuMu12 模拟器（暂不支持其他模拟器）
- **Python 3.10.x**（项目依赖与安装脚本均按 3.10 设计）

**虚拟环境与依赖**：
- 首次通过下方启动器会在项目根目录创建 **`.venv`**，并按 `requirements.txt` 安装依赖（首次较慢，之后会跳过已安装步骤）。
- 若本机没有 Python 3.10，`launcher.ps1` 可将官方 **3.10.11** 安装到仓库内的 **`.python310`**（无需管理员权限），再创建 `.venv`。

**模拟器设置建议**：
- 分辨率：平板 1280x720
- 适当提高内存和 CPU 分配，以获得更好的运行性能

## 安装与首次运行

### 桌面客户端（Electron）安装

1. 安装 [Node.js](https://nodejs.org/)（建议选用 LTS 版本）。

   - **推荐方式（适用于已启用 [winget](https://learn.microsoft.com/windows/package-manager/winget/) 的 Windows）**：
     打开 **PowerShell（管理员或普通模式均可）**，执行：
     ```powershell
     winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
     ```
   - **手动下载安装包**：
     也可以从官网下载 **`.msi` 安装包**，安装时勾选 **Add to PATH**（一般默认已勾选）。

2. 验证安装

   - 安装完成后，一定要**关闭所有已有终端**，新开一个终端窗口（如 PowerShell 或命令提示符）。
   - 执行 `node -v` 和 `npm -v`，可见版本号即表示安装成功。

3. 常见问题与解决办法

   - **npm 识别失败/未生效（如在编辑器终端）**：一般是因为旧终端窗口未刷新环境变量。
     按照下列方法顺序尝试，直至解决：
     - 关闭当前 IDE 或终端窗口，重新打开项目再试；
     - 或直接在 Windows 自带终端（PowerShell/命令提示符）输入 `npm -v` 验证；
     - 或在 PowerShell 内暂时刷新 PATH 后再进入 `webapp` 目录，示例代码如下：
       ```powershell
       $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
       node -v
       npm -v
       ```
     - 如果仍无法识别：
       1. 检查并确认 `C:\Program Files\nodejs\npm.cmd` 文件存在。
       2. 若不存在请重新运行安装包或 `winget` 命令安装。
       3. 如文件存在但环境变量无效，请进入「设置 → 系统 → 关于 → 高级系统设置 → 环境变量」，确认 `Path` 中包含 `C:\Program Files\nodejs`，调整后保存并新开终端再试。

4. 直接运行在仓库根目录执行：

   ```bash
   cd webapp
   npm install
   npm start
   ```

5. 按照安装器要求一步步安装依赖到 venv，若发生错误，请删除 .venv 重试。

6. **从源码打发行包（维护者）**：在仓库根目录用 **`.venv-nuitka`** 执行 `python scripts/build_release.py`（可加 `-j 16` 等），默认产物为 **`dist_electron/AutoScriptor_Zao_Install.exe`**（单文件；首次运行即 HTML 安装向导，解压引擎并配置 MuMu/ADB）。完整说明见上文 **release-build-and-run** 文档。

## 游戏内容配置

1. **设置账号密码**：在界面右上角下拉菜单中新建档案，输入账号密码+主角色信息，并设置安全密码作为加密。账号密码等始终密文保留在本地，当且仅当输入安全密码才会解密。

2. **技能键位设定**：按要求修改游戏内技能键位配置

   ![image-20250906210648638.png](https://cdn.nlark.com/yuque/0/2025/png/39311747/1757165540832-c46387e3-c580-4705-ba97-7d3c1bd63104.png?x-oss-process=image%2Fformat%2Cwebp)

3. **性能优化**：建议关闭游戏内"飘字"功能
   - 进入【九重天】-【设置】，找到"飘字"并关闭，可有效提升自动化处理性能

4. **其他建议**：
   - 各关卡可设置为 5 倍出怪速度和 3 倍加速
   - 建议先手动进入每个场景以跳过首次过场动画，确保脚本执行更流畅

## 任务管理

- **任务分类**：每日任务、每周任务、一般任务、活动任务
- **任务状态**：支持开启/关闭、执行时间记录、完成状态追踪
- **任务参数**：支持枚举、多选枚举、布尔、列表等多种参数类型
- **任务执行**：自动按配置顺序执行，支持重试机制和错误处理

## 扩展开发

当前内置任务数量有限，欢迎有兴趣的开发者参与适配与功能拓展！任务定义位于 `ZmxyOL/task/` 目录下，支持自动注册机制。
可以使用 AutoScriptor\utils\edit_img.py 文件辅助定位提取元素，方便定位。

# 常见问题 (FAQ)

## 配置文件设置错误

1. **复制配置模板**：
   - 复制 `config template.json` 为 `config.json`，修改其中例如模拟器设置等信息

2. **配置模拟器信息**：
   根据你的模拟器实际情况调整如下字段：
   index = 0 的话，对应 adb_addr 是 "127.0.0.1:16384"

   ```json
   "emulator": {
       "index": 1,                        # 你的模拟器索引
       "adb_addr": "127.0.0.1:16416",     # 你的 adb 地址，可在 MuMu 模拟器设置中查找
       "emu_path": "C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe",
       "adb_path": "C:/Program Files/Netease/MuMu/nx_main/adb.exe",
       "mumu_folder": "C:/Program Files/Netease/MuMu"
   }
   ```

## 模拟器连接失败

- 确认 MuMu 模拟器已启动
- 检查 `config.json` 中的 `adb_addr` 是否正确
- 确认 ADB 路径配置正确
- 尝试重启模拟器或重新连接 ADB

## 任务执行失败

- 查看 `logs/log/` 目录下的日志文件
- 查看 `logs/errors/` 目录下的错误归档
- 检查 `logs/click_screenshots/` 目录下的点击截图
- 确认游戏界面状态正常，未出现异常弹窗，可反馈

## WebUI 无法访问

- 确认端口 5000 未被占用
- 检查防火墙设置
- 尝试使用 `http://127.0.0.1:5000` 访问

# 技术栈

- **后端**：Python 3.10.x, FastAPI, uvicorn（WebSocket）
- **Web 前端**：Vue 3, Element Plus, Tailwind CSS（`services/webui/static/`）
- **桌面壳（可选）**：Electron（`webapp/`，`npm start`）
- **OCR**：PaddleOCR 2.7.0, PaddlePaddle 3.0.0
- **模拟器控制**：ADB, uiautomator2
- **其他**：loguru / questionary（CLI）, cryptography（加密）

# 项目结构

```
AutoScriptor/
├── AutoScriptor/          # 核心框架代码
│   ├── core/             # 核心 API 和控制逻辑
│   ├── control/          # 模拟器控制适配器
│   ├── recognition/      # OCR 和图像识别
│   ├── utils/            # 工具函数
│   ├── crypto/           # 配置加密管理
│   └── vlm/              # 视觉语言模型支持
├── services/             # 服务入口
│   ├── main_cli/         # CLI 命令行界面
│   ├── webui/            # Web 可视化界面（FastAPI + 静态前端）
│   └── core/             # 核心服务（任务管理等）
├── webapp/               # Electron 桌面客户端（npm start）
├── gui.py                # 后端 WebUI 入口（**日常使用请走 webapp：`npm start`**）
├── ZmxyOL/               # 游戏任务定义
│   ├── task/             # 任务实现
│   ├── nav/              # 导航和环境管理
│   └── battle/           # 战斗相关
├── docs/                 # 文档
├── logs/                 # 日志和截图
└── config.json           # 配置文件
```
