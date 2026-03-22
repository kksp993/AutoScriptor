# RuntimeContext 运行时生命周期管理

## 概述

`RuntimeContext` 是一个线程安全的单例类，集中管理 AutoScriptor 运行时的四个核心对象：

| 对象 | 类型 | 职责 |
|------|------|------|
| `mixctrl` | `MixControl` | 模拟器操控（点击/滑动/截图） |
| `mumu` | `Mumu` | 模拟器实例管理（启动/关闭/选择） |
| `bg` | `BackgroundProxy` | 后台 UI 监控线程 |
| `vlm_client` | `VLMAgent` | VLM 视觉语言模型客户端 |

**解决的问题**：替代 `scheduler.py` 中通过 `import AutoScriptor.core.api as core_api` + `core_api.mixctrl = new_mixctrl` 的散乱全局变量修补模式，将生命周期管理收拢到单一入口。

## 快速上手

```python
from services.core.runtime_context import runtime_ctx

# 查询当前状态
print(runtime_ctx.status_dict())
# {'initialized': True, 'has_mixctrl': True, 'has_mumu': True, 'has_bg': True, 'has_vlm': False}

# 判断是否已初始化
if runtime_ctx.is_initialized:
    print("运行时就绪")
```

## API 参考

### 获取实例

```python
# 推荐：使用模块级单例
from services.core.runtime_context import runtime_ctx

# 等价于
ctx = RuntimeContext.instance()
```

### 初始化方法

#### `init(mixctrl, mumu)`

初始化核心运行时对象，并同步到模块级全局变量。

```python
from AutoScriptor.core.api import mixctrl, mumu
runtime_ctx.init(mixctrl, mumu)
```

调用后：
- `runtime_ctx.mixctrl` / `runtime_ctx.mumu` 被赋值
- `AutoScriptor.mixctrl` 和 `AutoScriptor.core.api.mixctrl` 自动同步
- `is_initialized` 变为 `True`

#### `init_bg()`

绑定后台监控单例。幂等——重复调用无副作用。

```python
runtime_ctx.init_bg()
```

#### `init_vlm()`

惰性初始化 VLM 客户端。仅在 `config.json` 中 `llm.use_agent = true` 时生效。

```python
runtime_ctx.init_vlm()
```

### 刷新方法

#### `refresh() -> (mixctrl, mumu)`

模拟器重启后调用。释放旧的 NemuIpc 连接，重新创建 mixctrl/mumu，并同步全局变量。

```python
# 在 scheduler 中（替代原来的 _refresh_runtime_controls）
runtime_ctx.refresh()
```

**内部流程**：
1. `_release_nemu_ipc()` — 释放旧的 NemuIpc 原生连接
2. `ensure_app_running()` — 重新启动模拟器和应用
3. 更新 `self.mixctrl` / `self.mumu`
4. `_sync_globals()` — 同步到 `AutoScriptor` 和 `core.api` 模块

### 关闭方法

#### `shutdown()`

释放所有运行时资源。

```python
runtime_ctx.shutdown()
# 之后: mixctrl=None, mumu=None, vlm_client=None, is_initialized=False
```

### 状态查询

#### `is_initialized -> bool`

只读属性，判断是否已调用 `init()`。

#### `status_dict() -> dict`

返回当前状态摘要：

```python
{
    "initialized": True,
    "has_mixctrl": True,
    "has_mumu": True,
    "has_bg": True,
    "has_vlm": False,
}
```

## 生命周期时序

```
run.py 启动
    │
    ├── api.init()              # 创建 mixctrl, mumu
    ├── runtime_ctx.init()      # 注册到 RuntimeContext + 同步全局变量
    ├── runtime_ctx.init_bg()   # 绑定后台监控
    ├── runtime_ctx.init_vlm()  # 惰性初始化 VLM（如果启用）
    │
    ├── ... 正常运行 ...
    │
    ├── scheduler: 每日重启      # runtime_ctx.refresh()
    │   └── 释放旧 IPC → 重建 mixctrl/mumu → 同步全局变量
    │
    └── 程序退出
        └── runtime_ctx.shutdown()  # 清理所有资源
```

## 与 Scheduler 的集成

`scheduler.py` 中以下方法已委托给 RuntimeContext：

| 原方法 | 现在的实现 |
|--------|-----------|
| `Scheduler._release_nemu_ipc()` | `runtime_ctx._release_nemu_ipc()` |
| `Scheduler._refresh_runtime_controls(cfg)` | `runtime_ctx.refresh()` |
| `_maybe_daily_restart` 中的全局修补 | `runtime_ctx.refresh()` |
| `_post_execution_action` 中的 `from AutoScriptor import mixctrl` | `runtime_ctx.mixctrl` |

## 向后兼容

`_sync_globals()` 确保现有代码中通过 `from AutoScriptor import mixctrl` 获取的引用始终指向最新对象。无需修改任何任务脚本或业务代码。

## 相关文件

| 文件 | 变更内容 |
|------|----------|
| `services/core/runtime_context.py` | 新增 RuntimeContext 类 |
| `services/core/scheduler.py` | 委托生命周期操作给 runtime_ctx |
| `services/main_cli/run.py` | 启动时注册 + 退出时清理 |
| `test/test_refactor_v3v4/test_runtime_context.py` | 单元测试 |
