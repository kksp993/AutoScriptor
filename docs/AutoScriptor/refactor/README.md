# 重构技术文档

本目录包含 AutoScriptor 全量整改各阶段的技术文档，涵盖性能优化、新增接口、部署配置和架构变更。

## 文档索引

### 阶段一：解耦与基础修复

| 文档 | 内容 | 对应模块 |
|------|------|----------|
| [TaskRegistry — cfg 与任务注册解耦](task_registry_decouple.md) | 独立 TaskRegistry 单例，cfg 只存用户配置 | `task_registry.py` `task_register.py` `task_manager.py` `scheduler.py` |

### 阶段二：性能优化

| 文档 | 内容 | 对应模块 |
|------|------|----------|
| [OCR 识别优化](ocr_optimize.md) | 去除 scale fallback、帧级缓存机制 | `ocr_rec.py` |
| [后台监控改革](bg_monitor_reform.md) | 共享截图、批量检测、间隔调整 | `background.py` `api.py` |

### 阶段三 & 四：VLM 接入 + RuntimeContext

| 文档 | 内容 | 对应模块 |
|------|------|----------|
| [VLMTarget 视觉定位接口](vlm_target_api.md) | VLMTarget 类、V() 工厂函数、vlm_locate 识别函数 | `targets.py` `rec.py` `api.py` |
| [RuntimeContext 运行时生命周期](runtime_context_api.md) | 运行时对象集中管理、初始化/刷新/关闭流程 | `runtime_context.py` `scheduler.py` |
| [Ollama 本机 VLM 部署指南](ollama_deploy.md) | Ollama 安装、模型拉取、配置接入 | `config.json` `vlm/config.py` |

## 测试

| 测试目录 | 覆盖阶段 | 运行命令 |
|----------|----------|----------|
| `test/test_task_registry/` | 阶段一（cfg 与任务注册解耦） | `python -m unittest discover -s test/test_task_registry -v` |
| `test/test_perf_optimize/` | 阶段二（OCR 缓存 + 后台监控） | `python -m unittest discover -s test/test_perf_optimize -v` |
| `test/test_refactor_v3v4/` | 阶段三、四（VLM + RuntimeContext） | `python -m unittest discover -s test/test_refactor_v3v4 -v` |
