# AutoScriptor

## 项目介绍
AutoScriptor 是一个基于 Python 的自动化脚本与任务编排器，专注于安卓模拟器（优先支持 MuMu）操作自动化。项目集成了图像识别、OCR 文本识别、任务调度等功能，提供 CLI 命令行和 WebUI 可视化两种管理方式，支持灵活配置和二次开发。

本项目集成了模拟器控制、OCR 识别、自动任务调度、错误归档等核心功能，支持灵活配置，可通过 CLI 或 Web 界面实现任务分组管理、状态查看和配置编辑。无需深厚的编程基础即可灵活添加、启用、编辑或禁用自动化任务。

主要特性：

- **双模式管理**：支持 CLI 命令行界面和 WebUI 可视化界面两种操作方式
- **模拟器控制**：支持 MuMu 模拟器的点击、长按、滑动、输入、按键事件等操作
- **智能识别**：集成 PaddleOCR 文本识别和图像匹配，支持颜色采样、稳定性检测
- **任务编排**：按「每日 / 每周 / 一般 / 活动」分类管理任务，支持参数配置、执行后冷却与状态持久化
- **实时监控**：WebUI 通过 WebSocket 推送日志；CLI 提供交互式任务导航
- **错误处理**：自动归档错误日志和截图，便于问题排查
- **账号管理**：支持加密存储账号密码，安全可靠
- **扩展性强**：配置文件灵活易懂，便于自定义扩展至其他应用场景

适用于手游自动日常、批量重复操作等自动化场景，极大解放双手。

## 项目截图
![主界面](https://cdn.nlark.com/yuque/0/2025/png/39311747/1760066454746-f20015f1-a979-41f9-a6b5-74d29878e26b.png?x-oss-process=image%2Fformat%2Cwebp)
![设置配置](https://cdn.nlark.com/yuque/0/2025/png/39311747/1760066548224-6fda07f3-c176-4d6f-a36d-437ec793ca24.png?x-oss-process=image%2Fformat%2Cwebp)

## 参考项目
本项目参考并借鉴了以下优秀的开源项目，特此致谢：
- [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)
- [mumu-python-api](https://github.com/u-wlkjyy/mumu-python-api)
- [ZenlessZoneZero-OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)

## 免责声明
- 📌 本项目仅供学习交流，开发者团队保留最终解释权
- ⚖️ 使用本工具产生的一切风险需自行承担
- 🚫 本项目未授权任何个人、商家、自媒体账号等进行售卖
- 🚫 若您遇到商家使用本软件进行代练并收费，产生的任何问题及后果与本软件无关
- 🚫 开发者团队不会为您提供任何"售后"服务

## 使用说明与配置指南

如需完整的入门到进阶与 API 参考，请查阅: [docs/core/API.md](docs/core/API.md)

### 环境配置

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

### 安装与首次运行

推荐使用仓库根目录的启动器，一键完成虚拟环境创建与依赖安装：

| 方式 | 说明 |
|------|------|
| **`launcher.bat`** | 双击或在 CMD 中运行；内部调用 `launcher.ps1`，**默认启动 WebUI** 并完成安装 |
| **`launcher.ps1`** | PowerShell：`.\launcher.ps1` 默认 WebUI；参数见下 |

**`launcher.ps1` 第一个参数（运行目标）**：

- 省略或 **`webui`**：安装依赖后启动 Web 界面
- **`cli`**：安装依赖后启动 CLI
- **`install-only`**：仅创建/更新 `.venv` 并安装依赖，不启动界面

**跳过 Git 同步（离线或不想拉代码时）**：在参数中加入 **`-l`**（或 `--no-git-update`），例如 `.\launcher.ps1 -l`、`.\launcher.ps1 cli -l`。

**便捷批处理**：
- **`launcher-l.bat`**：等价于带 `-l` 的启动（不执行仓库更新逻辑）
- **`launcher-cli -l.bat`**：以 **`cli -l`** 方式启动 CLI；若进程异常退出会提示按键后再次尝试

**可选环境变量（一般不必设置）**：
- `AUTOSCRIPTOR_PIP_INDEX`：指定 pip 镜像，例如清华源
- `AUTOSCRIPTOR_PYTHON_URL`：自定义 Python 安装包下载地址（配合无本机 3.10 时引导安装）
- `AUTOSCRIPTOR_UPSTREAM_REF`：覆盖启动时 Git 同步的上游分支（默认由安装器配置）

### 启动方式（已手动装好 `.venv` 时）

在项目根目录激活虚拟环境后，可用模块方式启动（推荐，与启动器一致）：

```bash
# CLI
python -m services.main_cli.run

# WebUI
python -m services.webui.server
```

浏览器访问 WebUI：**`http://127.0.0.1:5000`**

未激活 venv 时也可使用 `.venv\Scripts\python.exe -m ...` 指定解释器。

#### 桌面客户端（Electron，可选）

若要用 **带窗口的桌面壳**（而非自己开浏览器），在项目里还有 **`webapp/`** 下的 Electron 应用：它会自动拉起后端的 **`gui.py`**（内部仍走 `services.webui.server` / uvicorn，与上面命令同一套界面）。

1. 安装 [Node.js](https://nodejs.org/)（LTS 即可）。
2. 先按上文装好 Python 依赖与 **`.venv`**（Electron 会优先用项目根目录的 `.venv\Scripts\python.exe`）。
3. 在仓库根目录执行：

```bash
cd webapp
npm install
npm start
```

`npm start` 等价于 `electron .`，会启动桌面窗口并加载 `http://127.0.0.1:5000`；**不要**在已用 `python -m services.webui.server` 占用 5000 端口时再开一份，避免端口冲突。

### 游戏内容配置

1. **设置账号密码**：在账号管理【A】->更新账号信息【U】中输入账号密码+主角色信息，并设置安全密码作为加密
   账号密码等始终密文保留在本地，当且仅当输入安全密码才会解密。


2. **技能键位设定**：按要求修改游戏内技能键位配置

![image-20250906210648638.png](https://cdn.nlark.com/yuque/0/2025/png/39311747/1757165540832-c46387e3-c580-4705-ba97-7d3c1bd63104.png?x-oss-process=image%2Fformat%2Cwebp)

3. **性能优化**：建议关闭游戏内"飘字"功能
   - 进入【九重天】-【设置】，找到"飘字"并关闭，可有效提升自动化处理性能

4. **其他建议**：
   - 各关卡可设置为 5 倍出怪速度和 3 倍加速
   - 建议先手动进入每个场景以跳过首次过场动画，确保脚本执行更流畅

### 任务管理

- **任务分类**：每日任务、每周任务、一般任务、活动任务
- **任务状态**：支持开启/关闭、执行时间记录、完成状态追踪
- **任务参数**：支持枚举、多选枚举、布尔、列表等多种参数类型
- **任务执行**：自动按配置顺序执行，支持重试机制和错误处理

### 扩展开发

当前内置任务数量有限，欢迎有兴趣的开发者参与适配与功能拓展！任务定义位于 `ZmxyOL/task/` 目录下，支持自动注册机制。
可以使用AutoScriptor\utils\edit_img.py文件辅助定位提取元素，方便定位。


## 常见问题 (FAQ)

### 1. 配置文件设置错误

1. **复制配置模板**：
   - 复制 `config template.json` 为 `config.json`

2. **配置模拟器信息**：
   根据你的模拟器实际情况调整如下字段：

   ```json
   "emulator": {
       "index": 1,                        # 你的模拟器索引
       "adb_addr": "127.0.0.1:16416",     # 你的 adb 地址，可在 MuMu 模拟器设置中查找
       "emu_path": "C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe",
       "adb_path": "C:/Program Files/Netease/MuMu/nx_main/adb.exe",
       "mumu_folder": "C:/Program Files/Netease/MuMu"
   }
   ```

### 2. 模拟器连接失败

- 确认 MuMu 模拟器已启动
- 检查 `config.json` 中的 `adb_addr` 是否正确
- 确认 ADB 路径配置正确
- 尝试重启模拟器或重新连接 ADB

### 3. 任务执行失败

- 查看 `logs/log/` 目录下的日志文件
- 查看 `logs/errors/` 目录下的错误归档
- 检查 `logs/click_screenshots/` 目录下的点击截图
- 确认游戏界面状态正常，未出现异常弹窗，可反馈

### 4. WebUI 无法访问

- 确认端口 5000 未被占用
- 检查防火墙设置
- 尝试使用 `http://127.0.0.1:5000` 访问

## 技术栈

- **后端**：Python 3.10.x, FastAPI, uvicorn（WebSocket）
- **Web 前端**：Vue 3, Element Plus, Tailwind CSS（`services/webui/static/`）
- **桌面壳（可选）**：Electron（`webapp/`，`npm start`）
- **OCR**：PaddleOCR 2.7.0, PaddlePaddle 3.0.0
- **模拟器控制**：ADB, uiautomator2
- **其他**：loguru / questionary（CLI）, cryptography（加密）

## 项目结构

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
├── gui.py                # Electron 调用的 WebUI 入口（等同启动 uvicorn）
├── ZmxyOL/               # 游戏任务定义
│   ├── task/             # 任务实现
│   ├── nav/              # 导航和环境管理
│   └── battle/           # 战斗相关
├── docs/                 # 文档
├── logs/                 # 日志和截图
└── config.json           # 配置文件
```
