# AutoScriptor 文档索引

Source Electron/WebUI is the baseline; research is not implementation.

- 入门：[操作](GETTING-STARTED.md)、[安装/更新](INSTALL.md)、[架构](architecture.md)、[排错](debug-lessons.md)。
- 运行：[API](reference/API.md)、[ascli](reference/ascli.md)、[生命周期](runtime/lifecycle.md)、[后台](runtime/background.md)、[调度](schedule/scheduler.md)、[策略](schedule/README.md)、[性能](schedule/perf.md)。
- 任务：[编写](tasks/script-authoring.md)、[安全](tasks/script-authoring-safety.md)、[依赖计算图](tasks/task-ordering-graph-plan.md)、[战斗](tasks/battle-flows.md)。
- WebUI：[契约](webui/api-contract.md)、[验收](webui/user-trajectories.md)。
- 运维：[wheel](operations/library-packages.md)、[归档](operations/log-archiver.md)、[QQ](operations/qq-notifications.md)、[跨机QQ](../../scripts/qq-robot-standalone/README.md)。
- 识别：[OCR实验](reference/ocr-model-experiment.md)、[实时路径](reference/fast-path.md)、[MuMu调研](reference/mumu-realtime-control-research.md)、[适配器](3rdparties/MumuAdaptor_README.md)。
- 参考：[Cocos](reference/cocos-runtime-inspection.md)、[战斗可行性](reference/auto-battle-bot-feasibility.md)、[可选OpenAI](reference/openai-multi-agents.md)。
- 维护：[共享规则](../agents/project-rules.md)、[在线检查](../agents/online-screenshot-test.md)、[Agent索引](../agents/README.md)。

Signatures/examples: source/tests. Personal workflows and their supporting files stay local and are not distributed. Shared rules govern budgets; check `scripts/check_docs_budget.py --details`.
