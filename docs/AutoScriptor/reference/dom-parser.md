# 独立 DOM 读取与交互接口

实现位于 [`test/manual/dom_parser.py`](../../../test/manual/dom_parser.py)。这是独立的实验接口，不是 `AutoScriptor` 公共导出。快照读取只读；元素交互与媒体控制由调用方显式发起，不内置刷课、切视频或重试策略。

## 依赖与连接

使用 Python 3.10 和同步 Playwright。模块导入不启动 OCR、不读写 `cfg`、不连接设备。可选安装：

```powershell
uv pip install --python .venv/Scripts/python.exe "playwright>=1.64"
```

连接已有 Chrome/WebView **不需要**下载 Playwright 浏览器。WebView 必须已经开启调试；工具不会替你开启调试、启动 App 或重连设备。

```python
from test.manual.dom_parser import connect_android_dom

with connect_android_dom(
    adb_path=r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
    serial="127.0.0.1:16448",  # 已确认的 2 号设备地址，不由工具猜测实例
    url_pattern="*/fzdx/play*",
    socket_name="chrome_devtools_remote",
) as dom:
    snapshot = dom.read_list(".vlist", ".vitem", selected_selector=".active")
    print(snapshot.current_item.text)
    following = snapshot.next_item
    if following is not None:
        print(following.text, following.fully_visible, following.receives_pointer)
    print(snapshot.container.scroll.can_scroll_down)
```

选择器只在调用端出现；实现不依赖这个网站、中文序号、颜色或固定行高。

- `connect_android_dom(...)`：用指定 ADB 串号读取调试 socket、创建临时端口转发并接入现有页面。多个 socket 必须显式选择，不能静默挑第一个。
- `connect_dom(endpoint, url_pattern="*", timeout_ms=10000)`：接入已有 Chromium CDP 地址，URL 使用 glob 匹配；匹配到零个或多个标签页都会报错。
- `DomParser(page_or_frame)`：复用调用方已有的同步 Playwright `Page/Frame`，解析层不持有连接生命周期。所有调用应在所属 Playwright 线程执行；已有同步会话时直接注入，不要嵌套启动第二个同步事件循环。

上下文退出只断开自己的 Playwright 连接并移除自己创建的 ADB 转发，不关闭用户浏览器或标签页。接入使用 `no_defaults=True`，不应用 Playwright 默认的焦点/媒体等覆盖。CDP 本身具备浏览器控制权限，只在可信本机使用。

## 读取接口

```python
# 通用元素查询；属性和 computed CSS 按需读取，避免全量输出敏感内容。
elements = dom.query(
    ".vitem",
    attributes=("id", "data-id"),
    styles=("color", "background-color", "border-left-color"),
)

# 同一次 evaluate 读取容器、所有已挂载行以及选中关系。
snapshot = dom.read_list(
    ".vlist", ".vitem", selected_selector=".active",
    attributes=("data-id",),
)
```

`DomElement` 返回 `text`、`tag`、`classes`、请求的 `attributes/styles`、`bounds`、`visible_bounds`、`rendered`、`fully_visible`、`receives_pointer` 和 `scroll`。

- `bounds` 为当前文档视口中的 CSS 像素矩形，不是 Android/Nemu 截图坐标，不能直接传给 `B(...)`。
- `visible_bounds` 包含视口及祖先滚动/裁切区域的交集；没有可见区域时为 `None`。
- `fully_visible` 只表示几何上未被裁切，不保证没有弹窗遮罩。
- `receives_pointer` 检查可见区域中心的 hit test 是否落在目标或其后代上；无可见区域时为 `None`。它不是点击成功保证，也不检查业务禁用状态。
- `scroll.can_scroll_down` 只说明该容器还有向下滚动空间，不说明有新数据或下一节。

`DomList.items` 包含当前 DOM 中的匹配行，包括滚动区域外的行。`current_item` 要求恰好一个选中项；缺失/多个选中项时抛 `DomSelectionError`。`next_item` 返回 DOM 顺序中的下一项；返回 `None` **只代表当前已挂载节点中没有下一项**，不能推断虚拟列表、无限加载列表或课程已经结束。

## 元素交互

在连接上下文内使用 `dom.element(selector)`，返回原生 Playwright `Locator`，不额外包装一套点击/输入 API：

```python
dom.element("#confirm").click(timeout=3000)
dom.element("input[name='keyword']").fill("example", timeout=3000)
dom.element("input[name='keyword']").press("Enter", timeout=3000)
dom.element("#next-item").scroll_into_view_if_needed(timeout=3000)
```

- `click()` 自带等待、可操作性检查和滚入视野；不需要换算模拟器坐标。遮罩不消失会超时，不会默认强点或用 JS 点击绕过。
- 每次动作重新定位节点，能处理原节点被替换；但选择器本身必须对应预期业务目标。单元素动作匹配多个节点会报 strict-mode 错误，不默选第一个。
- `element()` 使用 Playwright 选择器语义（包括其 Shadow DOM 支持），`query/read_list` 仍是标准 CSS DOM 查询。iframe 由调用方显式注入。
- 调用方按需设置动作 `timeout`；默认沿用 Playwright 的超时设置。输入完成不等于业务成功，动作后仍应检查页面状态。

## 媒体进度与控制

```python
state = dom.read_media("video", timeout_ms=3000)
print(state.current_time, state.duration, state.paused, state.ended)
dom.pause_media("video", timeout_ms=3000)
dom.play_media("video", timeout_ms=3000)
```

直接读取原生 `<video>/<audio>` 属性，不依赖控制条是否显示，不需要 hover 或 OCR。默认选择器为 `video`，多个播放器必须由调用方缩小选择范围。

- `MediaState` 包含 `current_time/duration`（秒）、`paused/ended/seeking`、`ready_state/network_state/error_code` 和 `source`。总长未加载或无限时为 `None`；`source` 可能含令牌，不应直接记日志。
- `read_media` 等待元素挂载，不等待元数据加载；媒体错误通过 `error_code` 返回。无元素、非媒体节点、多个匹配均报错，不返回假进度。
- `play_media` 只正常播放，不跳时间、不修改倍速、不调用 `load()`、不刷新页面；`ended=True` 时不重播。播放 Promise 被拒绝或超时会明确报错，并暂停以取消可能迟到的播放。寻找节点和等待播放 Promise 分别受 `timeout_ms` 限制。
- `play_media` 返回只表示请求成功，不保证后续持续推进；`ended` 也不表示服务端记录完成。严重网络/解码问题不保证能通过暂停后续播恢复。

## shuake：当前课程目录的观看流程

[`test/manual/shuake.py`](../../../test/manual/shuake.py) 复用上述接口，把站点专属逻辑留在任务内。`task(1)` 检查当前目录全部条目，`task(3)` 只处理第 3 项及以后；序号从 1 起算，非法范围报错。仍连接 2 号实例，不自动报名或打开其他课程。

1. **读取状态**：`read_lessons()` 一次读取 `.vlist` 内的标题、父链接、`.active` 选中状态和 `.chapter-icon-green` 完成标记。蓝色选中不代表完成，已完成项可以不连续。每次决策重新读取，不再使用 `current_index + 1` 的静态切片。
2. **自动选课**：`watch_course()` 优先看完范围内当前未完成项，否则选目录顺序的第一个未完成项。`select_lesson()` 按唯一链接而非标题/坐标点击，Playwright 自动滚入视野；等待导航结束，再核实选中项。空目录、多选、重复链接、跨课程链接或目录变化均报错，不能冒充已完成。
3. **正常观看**：`watch_lesson()` 已在播放就不重复点击；暂停且媒体就绪时请求正常播放。`progress(dom)` 返回秒数；循环约每 2 秒检查一次，约每 30 秒记录进度，实际间隔包含页面操作耗时。
4. **自动继续**：`handle_player_dialog()` 仅处理已核实的站点弹窗。断点提示 `该视频已播放至 ...` 点击 `继续播放`，不选 `从头播放`；周期暂停提示点击 `继续`。未知弹窗停止报错，不对所有“确定”盲点。
5. **确认完成再切换**：网站成功上报后显示 `当前视频播放完毕！`，确认按钮会刷新页面。脚本等刷新后读取绿色标记；仅有 `video.ended` 或成功提示还不算完成。结束后最长等待约 30 秒，仍无标记就报错、不重播、不切下一项；最后一项也走同一流程。

`PlaybackMonitor.check()` 保留连续 30 秒无进展时暂停后续播、连续最多两次的恢复策略；进度变化或换源重置预算，媒体错误及播放请求失败直接上抛。所有观看、续播、选课均用 DOM，不再使用 hover/OCR/固定坐标。不直接请求完成接口、不修改页面标记、不跳时间、不改倍速；只有正常点击站点完成确认会触发页面自带刷新。

连接覆盖完整循环，异常或取消退出仍移除自身转发，不关闭用户页面。等待沿用 `AutoScriptor.sleep()` 的取消语义。最终日志只声明**当前页面目录、指定范围**的前端完成标记全部确认，不声称其他课程或整个学习项目完成。

## 范围与错误

- 快照使用标准 CSS 查询；`item_selector` 相对容器，支持 `:scope`。`selected_selector` 匹配条目自身，不是它的任意子元素。
- 快照不自动穿透 Shadow DOM 或切换 iframe。iframe 可通过 `DomParser(frame)` 显式解析，但其几何和 hit test 仅覆盖该 frame，不能检测外层遮罩。
- DOM 顺序不一定等于 CSS 重排后的视觉顺序。复杂旋转、clip-path、动画及跨帧遮挡仍需要调用方验证。
- 快照不是可重用的元素句柄；页面变化后重新读取，动作使用原生 Playwright locator，不用旧 index 当长期身份。
- `query` 无匹配返回空 tuple；列表容器缺失/重复抛 `DomSelectionError`。非法 CSS、文档关闭等保留 Playwright 异常；ADB/CDP/页面选择失败抛 `DomConnectionError`，底层错误通过异常链保留。
- `query/read_list` 不自动等待页面就绪。调用方按实际页面使用 locator 等待，再读取；不要把临时空列表当成业务完成。
- 文本、显式请求的链接或属性可能含个人数据和令牌，不应将整个快照直接写入共享日志。

## 验证

`test/framework/test_dom_parser.py` 使用本地 HTML、内存生成的 WAV 和无头 Chromium，覆盖列表、遮罩、元素交互、原生媒体播放、拒绝/超时及连接清理。`test/framework/test_shuake_progress.py` 用假时钟验证恢复上限及连接生命周期；`test/framework/test_shuake_course.py` 通过本地页面覆盖非连续完成项、重复标题、当前项和最后一项观看、续播、完成后刷新、迟到的完成提示、缺失完成标记、目录变化与未知弹窗。自动测试不接触真实课程。运行前安装测试用 Chromium，或将 `DOM_PARSER_TEST_BROWSER` 指向已有 Chromium 可执行文件：

```powershell
.venv/Scripts/python.exe -m playwright install chromium
.venv/Scripts/python.exe -B -X utf8 -m unittest test.framework.test_dom_parser test.framework.test_shuake_progress test.framework.test_shuake_course -v
```
