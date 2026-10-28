# Cocos 游戏组件读取结论

历史检查日期：2026-10-27。对象：MuMu-1 上的 `org.yjmobile.zmxy`，游戏版本 `16.8.0`，ABI 为 `arm64-v8a`。以下仅保留当时结论，不代表当前设备状态；临时检查脚本和采集产物已按要求删除。

## 实际可见范围

- **没有取得内部 Cocos 场景节点或组件；实际总数未知。** 未获得背包物品、按钮的节点名称、层级、属性或业务数据。
- Android 宿主层可见 `Cocos2dxGLSurfaceView` 和 `Cocos2dxEditText`，分别是绘图和输入宿主，不是游戏内部的 `Node`、`Sprite`、`Label` 或 `Component`。
- 背包页面的辅助功能树只有 6 个系统节点，文本和内容描述均为空；唯一资源 ID 为 `android:id/content`，唯一可点击节点是通用 `EditText`，不能据此认定为背包搜索框。此前 4399 弹窗有 19 个系统节点、2 个带文本按钮，两种页面的节点数都不能算作 Cocos 组件数。
- 安装包标志中没有 `DEBUGGABLE`。当时可读取的 Unix socket 名称中未发现 `devtools_remote` 或 Cocos/JSB/Inspector 命名的候选入口；未检查 TCP 端口、验证接口归属或连接调试协议，因此不能断言所有诊断接口都不存在。

## 对后续工作的结论

- **现有 DOM / Android 控件树路径不能直接读取该游戏的背包内部对象。** 缺少的是内部节点导出通道，不是多写几个检查脚本；不再维护这批游戏专用探测逻辑。
- 网页 DOM 接口继续用于真正的网页；游戏可见内容使用截图、OCR 或模板识别，但识别结果不是引擎组件。
- 若确需真实场景图，应使用厂商授权的测试构建或受支持的诊断导出接口。更换 UI 检查工具不会自动恢复 Cocos 场景树。
- 只读不等于不可检测或无封禁风险；进程和前台窗口未变化也不是安全证明。检查没有附加调试器、注入、读取内存或提取 APK。
- 未确认 Cocos 引擎版本，也没有 iOS 实测；不能把游戏版本或 Android 结果套用于引擎版本及 IPA。

## 机制依据

- [Cocos 场景图](https://docs.cocos2d-x.org/cocos2d-x/v4/en/basic_concepts/scene.html)：解释引擎节点树，不代表目标使用 v4。
- [Android 虚拟辅助功能节点](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/view/accessibility/AccessibilityNodeProvider.java)：应用需主动暴露节点，不会自动拆解绘图画面。
- [Android Layout Inspector](https://developer.android.google.cn/studio/views/layout-inspector-views?hl=en)：平台视图检查不是 Cocos 场景图导出，属性检查还可能引起 Activity 重启。
