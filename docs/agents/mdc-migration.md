# MDC migration map

Only `00-shared-project-rules.mdc` and `online-screenshot-test.mdc` remain adapters to their shared documents.

- `task-registry`, `refactor-docs`, `perf_optimize` -> [architecture/lifecycle](skill-references/architecture-lifecycle.md).
- `webui`, `news-4399`, applicable `sourcemap-publish-security` guidance -> [WebUI/news](skill-references/webui-electron-news.md); unrelated command-agent memo dropped.
- `register`, `autoschedule` -> [authoring/style](skill-references/task-authoring-style.md); conditional design guidance, not mechanical absolute rules.
- `web-search-fallback` -> agent-level browsing policy and [local-evidence workflow](project-rules.md), not a project skill.

New durable guidance belongs here, not in tool-private duplicates.
