# AutoScriptor 文档索引

当前 `src` 分支只维护源码 Electron 和源码 WebUI。先看架构基线，再进入对应功能域。

## 必读

| 文档 | 用途 |
| --- | --- |
| [architecture.md](architecture.md) | 当前主线、代码分层、数据边界、已移除产品面 |
| [INSTALL.md](INSTALL.md) | 源码安装、运行、更新、排错 |
| [reference/API.md](reference/API.md) | 运行入口和核心 API 约定 |
| [runtime/lifecycle.md](runtime/lifecycle.md) | 启动、配置、账号、设备和任务生命周期 |
| [webui/api-contract.md](webui/api-contract.md) | WebUI API、日志通道、更新通道 |

## 功能域

| 功能域 | 文档 |
| --- | --- |
| WebUI 验收 | [webui/user-trajectories.md](webui/user-trajectories.md) |
| 调度器 | [schedule/scheduler.md](schedule/scheduler.md) |
| 主机性能策略 | [schedule/README.md](schedule/README.md)、[schedule/perf.md](schedule/perf.md) |
| 任务编写 | [tasks/script-authoring.md](tasks/script-authoring.md) |
| 任务安全 | [tasks/script-authoring-safety.md](tasks/script-authoring-safety.md) |
| 战斗流程 | [tasks/battle-flows.md](tasks/battle-flows.md) |
| 后台监控 | [runtime/background.md](runtime/background.md) |
| 错误归档 | [operations/log-archiver.md](operations/log-archiver.md) |
| OpenAI 多智能体示例 | [reference/openai-multi-agents.md](reference/openai-multi-agents.md) |
| 第三方资料 | [3rdparties/MumuAdaptor_README.md](3rdparties/MumuAdaptor_README.md) |

## 维护规则

- 行为、生命周期、API、状态语义或源码启动方式变化时，同步更新本索引里的对应文档。
- 移动、合并或删除文档后，用 `rg` 复扫 README、`docs/agents`、脚本和测试中的旧路径。
- 文档只描述当前事实。已删除的发布器、CLI、Canvas、Socket.IO、Nuitka、VLM 等历史产品面不要写成可用路径。
