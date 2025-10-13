# AutoScriptor

## 项目介绍
AutoScriptor 是一个基于 Python 和 Vue 的自动化脚本与任务管理器，设计用于管理和自动执行特定设备上的日常操作任务。

本项目集成了模拟器操作、OCR 识别、自动任务调度等功能，支持灵活配置，可通过 Web 界面实现任务分组管理、状态查看和配置编辑。无需深厚的编程基础即可灵活添加、启用、编辑或禁用自动化任务。

主要特性：

- 支持Mumu模拟器上的多种任务自动任务执行
- 集成 PaddleOCR/图像匹配 识别，可用于游戏界面、截图等自动判定
- 提供可视化 Web 管理界面（基于 Vue3），操作便捷
- 支持任务分组（每日、每周、一般任务等）、状态统计与实时日志查看
- 配置文件灵活易懂，便于自定义扩展至其他应用

适用于手游自动日常、批量重复操作等自动化场景，极大解放双手。

## 项目截图
![主界面](https://cdn.nlark.com/yuque/0/2025/png/39311747/1760066454746-f20015f1-a979-41f9-a6b5-74d29878e26b.png?x-oss-process=image%2Fformat%2Cwebp)
![设置配置](https://cdn.nlark.com/yuque/0/2025/png/39311747/1760066548224-6fda07f3-c176-4d6f-a36d-437ec793ca24.png?x-oss-process=image%2Fformat%2Cwebp)

## 参考项目
本项目参考并借鉴了以下优秀的开源项目，特此致谢：
- [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)
- [mumu-python-api](https://github.com/u-wlkjyy/mumu-python-api)

## 使用说明与配置指南

如需完整的入门到进阶与 API 参考，请查阅: [AutoScriptor/core/API.md](AutoScriptor/core/API.md)

0. 请确保使用 Windows 系统，并优先选择 Mumu 模拟器或 Mumu 12 版本（暂不支持其他模拟器）。

1. 建议将模拟器设置为平板 1280x720 分辨率，同时适当提高内存和 CPU 分配，以获得更好的运行性能。

2. 安装 Anaconda 或 Miniconda，并创建独立虚拟环境：

   ```
   conda create -n zmxy python==3.10.15
   ```

3. 配置国内源以提升 Python 和 Conda 的下载速度，以及相关依赖项：

   ```text
   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/linux-64/
   conda config --set show_channel_urls yes
   ```

4. 配置 `config.json` 文件

   - 首先复制 `config template.json` 为 `config.json`。
   - 根据你的模拟器实际情况调整如下字段：

   ```
   "emulator": {
       "index": 1,                        # 你的模拟器索引
       "adb_addr": "127.0.0.1:16416",     # 你的 adb 地址，可在 MuMu 模拟器设置中查找
       "emu_path": "C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe",
       "adb_path": "C:/Program Files/Netease/MuMu/nx_main/adb.exe",
       "mumu_folder": "C:/Program Files/Netease/MuMu"
   },
   ```

5. 按需修改技能键位设定

   ![image-20250906210648638.png](https://cdn.nlark.com/yuque/0/2025/png/39311747/1757165540832-c46387e3-c580-4705-ba97-7d3c1bd63104.png?x-oss-process=image%2Fformat%2Cwebp)

6. 优化性能：建议关闭游戏内“飘字”功能

   - 进入【九重天】-【设置】，找到“飘字”并关闭，可有效提升自动化处理性能。

7. 其他前期准备建议

   - 各关卡可设置为 5 倍出怪速度和 3 倍加速。
   - 建议先手动进入每个场景以跳过首次过场动画，确保脚本执行更流畅。

8. 当前内置任务数量有限，欢迎有兴趣的开发者参与适配与功能拓展！
