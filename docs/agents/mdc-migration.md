# Cursor MDC Migration

Old Cursor-only `.mdc` files were reviewed and either migrated into shared skill references or replaced by thin adapters.

| Old rule | Disposition |
| --- | --- |
| `00-shared-project-rules.mdc` | Kept as Cursor adapter to `docs/agents/project-rules.md`. |
| `online-screenshot-test.mdc` | Kept as Cursor trigger adapter to `docs/agents/online-screenshot-test.md`. |
| `task-registry.mdc` | Migrated to `docs/agents/skill-references/architecture-lifecycle.md`. |
| `refactor-docs.mdc` | Migrated to `docs/agents/skill-references/architecture-lifecycle.md`. |
| `perf_optimize.mdc` | Migrated to `docs/agents/skill-references/architecture-lifecycle.md`. |
| `webui.mdc` | Migrated to `docs/agents/skill-references/webui-electron-news.md`. |
| `sourcemap-publish-security.mdc` | WebUI/news maintenance guidance migrated to `webui-electron-news.md`; unrelated command-agent design memo dropped. |
| `news-4399.mdc` | Migrated to `webui-electron-news.md`. |
| `register.mdc` | Migrated as a conditional pattern in `task-authoring-style.md`. |
| `autoschedule.mdc` | Migrated as style guidance in `task-authoring-style.md`, softened from absolute rule to judgment-based guidance. |
| `web-search-fallback.mdc` | Not migrated as project skill content; superseded by agent-level browsing/search policy and `docs/agents/project-rules.md` local-evidence guidance. |

Keep future durable rules in `docs/agents/` or the project skill references. Avoid creating new Cursor-only rule copies.

