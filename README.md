# AutoScriptor

# 项目介绍
AutoScriptor 是一个基于 Python 的自动化脚本与任务编排器，专注于安卓模拟器（优先支持 MuMu）操作自动化。项目集成了图像识别、OCR 文本识别、任务调度等功能，提供 CLI 命令行和 WebUI 可视化两种管理方式，支持灵活配置和二次开发。

本项目集成了模拟器控制、OCR 识别、自动任务调度、错误归档等核心功能，支持灵活配置，可通过 CLI 或 Web 界面实现任务分组管理、状态查看和配置编辑。无需深厚的编程基础即可灵活添加、启用、编辑或禁用自动化任务。

仓库作者：Kksp993  
仓库地址：https://github.com/kksp993/AutoScriptor

## 主要特性

- **双模式管理**：支持 CLI 命令行界面和 WebUI 可视化界面两种操作方式
- **模拟器控制**：支持 MuMu 模拟器的点击、长按、滑动、输入、按键事件等操作
- **启动诊断**：WebUI 可分层查看 MuMuManager、ADB、App、NemuIpc、OCR、UI Map 状态
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

如需完整的入门到进阶与 API 参考，请查阅: [docs/AutoScriptor/reference/API.md](docs/AutoScriptor/reference/API.md)

当前生命周期与接口规范:

- [运行生命周期](docs/AutoScriptor/runtime/lifecycle.md)
- [WebUI API 规范](docs/AutoScriptor/webui/api-contract.md)
- [任务脚本编写约定](docs/AutoScriptor/tasks/script-authoring.md)
- [WebUI 用户轨迹验收](docs/AutoScriptor/webui/user-trajectories.md)

**发行构建与日常运行**（`build_release.py` 参数、portable/NSIS、增量缓存、安装向导、`backend.zip` 与排错）：[docs/AutoScriptor/release/build-and-run.md](docs/AutoScriptor/release/build-and-run.md)

## 安装与首次运行

完整安装教程见根目录文档：[INSTALL.md](INSTALL.md)。

请先选择安装路线：

- **安装包安装**：面向普通用户。运行 `AutoScriptor_Zao_Install_*.exe`，不需要 Python、Node.js、Git 或源码仓库。
- **源码安装**：面向开发者和维护者。需要 Git、Python 3.10、Node.js，并从仓库启动或构建。

<details>
<summary>安装包安装快速步骤</summary>

1. 在 Windows 10/11 x64 上安装并启动 MuMu 或 MuMu12，建议分辨率为平板 `1280x720`。
2. 从可信来源获取 `AutoScriptor_Zao_Install_*.exe`，如发布者提供 SHA256，先用 `Get-FileHash -Algorithm SHA256` 校验。
3. 双击安装包，选择普通用户可写目录，例如 `D:\AutoScriptor` 或 `Documents\AutoScriptor`，不建议选择 `C:\Program Files`。
4. 在安装向导中先执行预检，再开始安装。首次解压 backend 可能需要数分钟。
5. 按向导配置或验证 MuMu/ADB 路径。若暂时无法配置，可先完成安装，之后在 WebUI 启动诊断中继续处理。
6. 双击安装目录中的 `造笔.exe` 启动，确认 `http://127.0.0.1:5000` 可访问。
7. 默认卸载会保留 `data`；需要删除账号、配置和自定义数据时运行 `彻底卸载造笔.bat`。

详细说明见 [INSTALL.md - 安装包安装](INSTALL.md#一安装包安装)。

</details>

<details>
<summary>源码安装快速步骤</summary>

1. 安装 Git、Python 3.10.x x64、Node.js LTS、MuMu 或 MuMu12。
2. 获取源码并进入仓库目录。
3. 先准备 Python 环境：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 install-only
   ```

4. 启动源码 WebUI：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 webui
   ```

5. 或启动 Electron 桌面端：

   ```powershell
   cd webapp
   npm install
   npm start
   ```

6. 维护者构建发行包：

   ```powershell
   .\.venv-nuitka\Scripts\python.exe -X utf8 scripts\build_release.py
   ```

详细说明见 [INSTALL.md - 源码安装](INSTALL.md#二源码安装)，发行构建细节见 [docs/AutoScriptor/release/build-and-run.md](docs/AutoScriptor/release/build-and-run.md)。

</details>

## 游戏内容配置

1. **设置账号密码**：在界面右上角下拉菜单中新建档案，输入账号密码+主角色信息，并设置安全密码作为加密。账号密码等始终密文保留在本地，当且仅当输入安全密码才会解密。

2. **技能键位设定**：按要求修改游戏内技能键位配置

   ![image-20250906210648638.png](https://cdn.nlark.com/yuque/0/2026/png/39311747/1781185484774-9f6e87f7-7084-4ef5-ae67-496e8c98d118.png?x-oss-process=image%2Fformat%2Cwebp)

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
- 在 WebUI 打开「启动诊断」，先看 ADB/App/NemuIpc 哪一层失败；默认诊断不触发截图，点击「截图探测」才检查 NemuIpc
- 尝试重启模拟器或重新连接 ADB

## 任务执行失败

- 源码模式查看 `logs/log/`；发行版通常在安装目录 `data/logs/log/`
- 错误归档位于 `get_logs_root()/errors/`，源码常见为 `logs/errors/`，发行版常见为 `data/logs/errors/`
- 点击/搜索调试截图位于 `get_logs_root()/debug_screenshot/`
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
├── data/                 # 账号、自定义任务、运行态职业脚本等可编辑数据
├── logs/                 # 源码模式日志和截图；发行版对应安装目录 data/logs
└── config.json           # 配置文件
```
