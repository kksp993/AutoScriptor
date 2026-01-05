### AutoScriptor 使用指南与 API 参考

面向第一次接触本项目的用户：本指南将带你从 0 到 1 完成环境搭建、配置、运行，并快速掌握核心 API、任务系统与二次开发方式。

---

## 一、项目概览

- **定位**: 基于 Python 的自动化脚本与任务编排器，聚焦安卓模拟器（优先支持 MuMu）操作自动化，集成图像识别与 OCR，支持 CLI 和 WebUI 管理。
- **核心能力**:
  - **模拟器控制**：点击、长按、滑动、输入、按键事件、前后台切换等
  - **识别定位**：图片匹配、OCR 文本识别、颜色采样、稳定性检测
  - **任务编排**：按“每日/每周/一般/活动”分类，支持参数、执行后冷却与状态持久化
  - **可视化管理**：WebUI 配置与运行、SSE 实时日志
- **主要入口**：
  - CLI: `python services/main_cli/run.py`
  - WebUI: `python services/webui/server.py` 后访问 `http://127.0.0.1:5000`

项目结构（节选）：

```text
AutoScriptor/
  core/
    api.py           # 控制与识别的统一 API（本章重点）
    background.py    # 后台监控（UI 事件监听）
    targets.py       # 目标建模（图片/文本/区域）
  utils/constant.py  # 配置加载/保存（含加密字段处理）
services/
  main_cli/run.py    # 命令行导航与任务执行
  webui/server.py    # Web 服务（配置/任务/日志）
ZmxyOL/task/         # 任务定义与自动注册
config.json          # 运行配置（从模板复制而来）
```

---

## 二、快速开始（5-15 分钟）

- **系统要求**：Windows 10/11；MuMu 或 MuMu12 模拟器；Python 3.10（建议用 Conda）
- **显卡/加速**：PaddleOCR 可选 GPU（默认 CPU）

1) 创建环境与安装依赖（PowerShell）

```powershell
conda create -n zmxy python==3.10.15 -y
conda activate zmxy
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r requirements.txt
```

2) 复制并填写配置

```powershell
copy "config template.json" config.json
```

打开 `config.json`，按你的 MuMu 环境填写：

```json
{
  "app": {
    "name": "ZmxyOL",
    "app_to_start": "org.yjmobile.zmxy",
    "restart_on_error": true,
    "run_in_background": true,
    "auto_start": true
  },
  "ocr": { "use_gpu": false },
  "emulator": {
    "index": 1,
    "adb_addr": "127.0.0.1:16416",
    "mumu_folder": "C:/Program Files/Netease/MuMu",
    "emu_path": "C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe",
    "adb_path": "C:/Program Files/Netease/MuMu/nx_main/adb.exe"
  },
  "encryption": {},
  "tasks": {}
}
```

3) 运行方式

- CLI 导航：

```powershell
python services/main_cli/run.py
```

  - 选择/勾选任务、编辑参数、保存配置、开始执行
  - 支持拼音搜索；支持账号验证/更新；支持“标注目标”工具

- WebUI：

```powershell
python services/webui/server.py
```

  - 打开浏览器访问 `http://127.0.0.1:5000`
  - 编辑配置与任务、提交运行、实时查看日志（SSE）

4) 日志与排错

- 运行日志：`logs/log/[timestamp].log`
- 错误快照：`logs/errors/[timestamp].log`
- WebUI SSE：`logs/webui_sse.log`

---

## 三、核心概念与数据模型

- **MixControl（控制层）**：封装模拟器操作（点击/滑动/输入/按键/截图/窗口控制/应用启动关闭等）。
- **Target（识别层）**：统一描述“要找的 UI 目标”。三类：
  - `I(...)` 图片目标（ImageTarget），可设置信心阈值或颜色过滤
  - `T(...)` 文本目标（TextTarget），可选正则匹配
  - `B(...)` 区域目标（BoxTarget），直接使用坐标盒
- **Box**：矩形区域，内置偏移/缩放操作与颜色采样。
- **稳定性检测**：`locate()` 支持两次检测一致性，以减少误判。
- **后台监控**：`BackgroundMonitor` 定期探测某些目标出现并触发回调。

---

## 四、核心 API 速查与示例（来自 `AutoScriptor/core/api.py`）

以下示例默认你已 `from AutoScriptor.core.api import *` 且已正确配置并连接到 MuMu。

### 4.1 目标构造（`targets.py`）

```python
from AutoScriptor.core.targets import I, T, B

# 按 UI 字典键使用图片目标（配合 assets/config/ui_map.csv）
img_ok = I('确认按钮')

# 直接文本匹配（默认全屏搜索，可传 box 限定范围）
txt_title = T(text='主界面标题')

# 以坐标盒作为目标（x, y, w, h）
region = B(100, 200, 300, 150)
```

### 4.2 定位与判断

```python
from AutoScriptor.core.api import locate, ui_T, ui_F, wait_for_appear, wait_for_disappear

# 返回第一个匹配的 Box 或 None（列表需全部满足、元组任一满足）
box = locate(img_ok, timeout=5)

# 判断是否存在/不存在（不强制稳定）
exists = ui_T((img_ok, txt_title), timeout=2)
not_exists = ui_F(img_ok, timeout=2)

# 等待出现/消失
wait_for_appear(img_ok, timeout=20)
wait_for_disappear(txt_title, timeout=10)
```

### 4.3 基本操作

```python
from AutoScriptor.core.api import click, swipe, input, key_event, sleep

# 点击目标（支持长按/重复/偏移/缩放/直到条件满足）
click(img_ok, timeout=10)
click(img_ok, long_click_duration_s=1)
click([I('A'), I('B')])              # 列表代表全部目标都需要定位
click((I('A'), I('B')))              # 元组代表任意一个目标定位成功即可

# 滑动（起止都可为目标或区域）
swipe(B(600, 600, 1, 1), B(600, 200, 1, 1), duration_s=1)

# 输入文本（可先聚焦到输入框目标）
input('hello', T(text='请输入'))

# 发送按键事件（模拟器 KeyCode）
key_event(4)  # 退格/返回键

sleep(1.5)
```

### 4.4 识别辅助

```python
from AutoScriptor.core.api import extract_info, get_colors
from AutoScriptor.core.targets import B

# 从区域 OCR 提取文本，可自定义后处理函数
text = extract_info(B(100,100,300,80), post_process=lambda s: s.strip())

# 批量采样多个目标的颜色（支持偏移/缩放）
colors = get_colors((I('按钮1'), I('按钮2')), offset=(5,5), resize=(20,20))
```

### 4.5 实用工具

```python
from AutoScriptor.core.api import edit_img

# 标注/截屏辅助工具（开发期定位 UI 区域）
edit_img()
```

---

## 五、后台监控与装饰器（`core/background.py`）

- **后台监控线程**：`bg = BackgroundMonitor()` 启动后循环检测已注册的目标。
- **添加/移除监控**：

```python
from AutoScriptor.core.background import bg
from AutoScriptor.core.targets import I

bg.add('掉线弹窗', I('重新连接').t, callback=lambda: click(I('重新连接')), once=True)
# ...
bg.remove('掉线弹窗')
```

- **装饰器用法**：`@monitor([...])` 在函数进入时批量注册，退出时自动移除。

---

## 六、任务系统（`ZmxyOL/task` 与 `services/core/task_manager.py`）

- **自动注册**：在 `ZmxyOL/task/` 下新增脚本，并使用 `@register_task` 装饰器，系统会按路径生成层级菜单并注入到 `cfg["tasks"]`。
- **参数与枚举**：默认值会写入 `params`；若默认值是枚举或枚举列表，会写入 `param_meta` 以便前端/运行期还原。
- **执行与冷却**：按“每日/每周/一般/活动”规则更新 `next_exec_time` 或自动关闭开关。
- **运行路径**：
  - CLI：`services/main_cli/run.py` 的交互式导航与执行
  - WebUI：`/run` 后台线程按映射顺序执行（见 `server.py` 的 `ORDER_MAP`）

### 6.1 新增任务示例

```python
# 文件: ZmxyOL/task/每日任务/村庄/示例任务.py
from ZmxyOL.task.task_register import register_task
from AutoScriptor.core.api import I, T, click, wait_for_appear, sleep

@register_task
def 示例任务(难度: str = '普通'):
    wait_for_appear(I('主界面'), timeout=15)
    click(I('开始按钮'))
    wait_for_appear(T(text='胜利'), timeout=60)
    sleep(1)
```

保存后重载：

- CLI 执行时会动态加载
- WebUI 可通过 `POST /refresh` 或在页面刷新后触发重载

---

## 七、配置与加密（`utils/constant.py` 与 `crypto`）

- `cfg` 为全局单例配置：`cfg["app"] / cfg["emulator"] / cfg["ocr"] / cfg["tasks"]`。
- `cfg.load_config(pwd)` 会尝试用安全密钥解密 `encryption` 区块，将账号等敏感信息映射到内存中的 `cfg["game"]`。
- `cfg.save_config()` 写盘时会清理运行时键（如 `game/year/month/...` 与任务中的 `fn/order`）。
- WebUI 提供 `/verify`、`/account` 来录入与校验账号，并通过 `ConfigManager` 进行加密落盘。

---

## 八、Web 服务（`services/webui/server.py`）

- 主要 API：
  - `GET /`：返回管理页
  - `GET /logs`：SSE 实时日志
  - `POST /enum-options`：批量查询枚举可选项
  - `POST /config`：保存 `app/emulator/ocr`
  - `POST /tasks`：保存任务配置并重载
  - `GET /refresh`：刷新并返回“可公开配置”
  - `POST /run`：后台线程执行任务列表
  - `POST /stop`：尝试终止后台执行
  - `POST /verify` / `POST /account`：账号验证与加密写入

---

## 九、最佳实践与排错建议

- **匹配稳定性**：对易抖动的 UI，使用 `locate(..., assure_stable=True)`，或缩小 `box`、结合 `color`。
- **性能建议**：在游戏设置中关闭“飘字”；模拟器分辨率设为 1280x720；合理分配 CPU/内存。
- **ADB 连接**：确认 `adb_addr` 与 MuMu 设置一致，`adb.exe` 路径正确。
- **窗口与前后台**：`run_in_background=true` 时会隐藏窗口；调试期可设为 false。
- **日志定位**：错误日志固定写入 `logs/errors`，便于溯源；WebUI 实时查看方便现场问题定位。

---

## 十、常见问答（FAQ）

- **Q: 首次运行报找不到模拟器？**
  - A: 检查 `emulator.mumu_folder/emu_path/adb_path`，确保 MuMu 已安装且路径正确；`index` 指向正确实例。

- **Q: OCR 慢或识别不准？**
  - A: 限定识别区域（传 `box`），避免全屏；必要时开启 GPU（需正确安装 PaddleOCR GPU 版）。

- **Q: 任务已勾选但不执行？**
  - A: 查看该任务的 `next_exec_time` 是否在冷却中；或在 CLI/WebUI 中重新启用、保存并刷新。

---

## 十一、二次开发速记

- 在 `ZmxyOL/task/...` 新建脚本 + `@register_task`
- 使用 `core/api.py` 的高阶 API 实现稳健的点击/等待/OCR
- 借助 `edit_img()` 辅助标注目标区域，维护 `ui_map`
- 提交前本地回归：CLI 跑一遍主要任务，确认无异常日志

---

如需更深入的函数签名与实现细节，请直接阅读：

- `AutoScriptor/core/api.py`
- `AutoScriptor/core/targets.py`
- `AutoScriptor/core/background.py`
- `services/core/task_manager.py`
- `services/webui/server.py`


