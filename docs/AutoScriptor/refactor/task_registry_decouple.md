# TaskRegistry — cfg 与任务注册解耦

## 背景

在重构前，`@register_task` 将所有数据（函数引用 `fn`、注册顺序 `order`、枚举元数据 `param_meta`、用户开关 `on`、调度时间 `next_exec_time` 等）统一写入 `cfg["tasks"]` 的嵌套字典。`cfg.save_config()` 需要在序列化前递归删除不可序列化的 `fn` 和 `order`，加载时也需要重新注入，导致 **配置层与运行时耦合**。

## 设计原则

| 数据 | 存储位置 | 是否持久化 | 说明 |
|------|----------|-----------|------|
| `on` `next_exec_time` `params` `next_exec_offset_hours` `sched_window_hours` `allowed_weekdays` | `cfg["tasks"]` | 是（JSON） | 用户可编辑配置 |
| `fn` `order` `param_meta` `param_keys` `beta` `custom` `doc_flow` `description` `debug_mode` | `TaskRegistry` | 否（内存） | 代码定义的运行时数据 |

**两者通过 slash 分隔的任务路径关联**，例如 `"每日任务/村庄/宠物培养"`。

## 模块位置

```
AutoScriptor/utils/task_registry.py   ← TaskRegistry 单例
```

## API

### TaskRegistry 类

```python
from AutoScriptor.utils.task_registry import task_registry
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `(path: str, fn, order: int, param_meta: dict \| None = None, *, param_keys=None, beta=False, custom=False, doc_flow="", description="", debug_mode=False)` | 注册/覆盖一个任务 |
| `get_fn` | `(path: str) → callable \| None` | 获取任务函数，未注册返回 `None` |
| `get_order` | `(path: str) → int \| float` | 获取注册顺序，未注册返回 `inf` |
| `get_param_meta` | `(path: str) → dict` | 获取枚举参数元数据，未注册返回 `{}` |
| `get_param_keys` | `(path: str) → list[str]` | 获取当前函数签名参数名，用于清理迁移后的旧参数 |
| `get_beta` / `get_custom` / `get_debug_mode` | `(path: str) → bool` | WebUI 展示与执行模式标记 |
| `get_doc_flow` / `get_description` | `(path: str) → str` | WebUI 任务说明 |
| `set_fn` | `(path: str, fn)` | 替换已注册任务的函数（不存在则忽略） |
| `has_task` | `(path: str) → bool` | 判断路径是否已注册 |
| `all_paths` | `() → list[str]` | 返回所有已注册路径 |
| `items` | `() → ItemsView` | 迭代 `(path, {"fn", "order", "param_meta"})` |
| `clear` | `()` | 清空注册表（reload 时使用） |

### 路径格式

- 与 `cfg["tasks"]` 的嵌套键用 `/` 拼接一致
- 例：`cfg["tasks"]["每日任务"]["村庄"]["宠物培养"]` → `"每日任务/村庄/宠物培养"`
- 路径片段已归一为中文（通过 `normalize_to_cn`）

## 数据流

```
@register_task
    ├── cfg["tasks"] ← { on, next_exec_time, params, next_exec_offset_hours, sched_window_hours, allowed_weekdays }
    └── TaskRegistry ← { fn, order, param_meta, param_keys, beta, custom, doc_flow, description, debug_mode }

TaskManager._prepare_task(path)
    ├── cfg["tasks"][path] → 读取 params
    └── task_registry.get_fn(path) → 获取可执行函数

Scheduler._collect_due(tree)
    ├── cfg["tasks"] → 遍历 on / next_exec_time
    └── task_registry.has_task(path) → 过滤未注册的残留配置

sort_tasks(tree)
    └── task_registry.get_order(path) → 按注册顺序排序

TaskTreeService.inject_public_task_fields()
    ├── task_registry.has_task(path) → 隐藏未注册残留叶子
    ├── task_registry.get_param_meta/get_param_keys(path) → WebUI 参数编辑
    └── task_registry.get_beta/get_custom/get_debug_mode/get_doc_flow/get_description(path) → 展示字段
```

## 受影响模块

| 模块 | 改动要点 |
|------|----------|
| `ZmxyOL/task/task_register.py` | `@register_task` 分写 cfg 和 TaskRegistry |
| `ZmxyOL/task/__init__.py` | `force_reload_tasks()` 先 `task_registry.clear()` |
| `ZmxyOL/task/pkg_utils.py` | `get_min_order` / `sort_tasks` 读 TaskRegistry |
| `services/core/task_manager.py` | `_prepare_task` / `_resolve_params` 用 TaskRegistry |
| `services/core/scheduler.py` | `_collect_due` / `_collect_active_times` 用 TaskRegistry 过滤 |
| `services/core/task_tree.py` | `is_leaf` 简化为 `'on' in node` |
| `services/webui/task_tree_service.py` | 注入公开运行时字段，保存前剥离运行时字段 |
| `AutoScriptor/utils/app_config.py` | `Character.clean_tasks_inplace()` 防御性清理运行时字段 |

## 叶子节点判断

重构前后对比：

```python
# 重构前 — 依赖 fn 在 cfg 中
TaskTree.is_leaf(node) → 'fn' in node and 'on' in node

# 重构后 — fn 已移至 TaskRegistry
TaskTree.is_leaf(node) → 'on' in node
```

Scheduler 的 `_collect_due` / `_collect_active_times` 额外调用 `task_registry.has_task(path)` 确保只收集已注册的任务，避免配置残留导致空跑。

## 测试

```powershell
# 在项目虚拟环境中运行
.venv\Scripts\python.exe -X utf8 -m unittest discover -s test/test_task_registry -v
```

| 测试文件 | 覆盖内容 | 用例数 |
|----------|----------|--------|
| `test_registry_core.py` | 单例、注册/查询/覆盖、set_fn、clear、集合操作 | 17 |
| `test_decouple_cfg.py` | cfg 节点无 fn/order、JSON 保存干净、TaskTree 判断、scheduler 过滤、task_manager 取 fn | 19 |

## 注意事项

- **reload 场景**：`force_reload_tasks()` 会先 `task_registry.clear()` 再重新注册，确保无残留
- **测试 mock**：测试中替换 fn 应使用 `task_registry.set_fn(path, new_fn)` 而非修改 cfg 节点
- **向后兼容**：`Character.clean_tasks_inplace()` 和 `TaskTreeService.strip_runtime_fields()` 仍防御性清理 `fn/order/param_meta/param_keys/beta/custom/debug_mode/task_description/task_doc_flow/_due/progress_display` 等运行时字段，避免账号 JSON 被污染
