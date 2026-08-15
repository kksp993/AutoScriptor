# Agent Rule Guide

This directory is the shared rule layer for all coding agents working on AutoScriptor.

## Rule Layout

| Area | Files |
|------|-------|
| Entry workflow | `project-rules.md` |
| Live emulator testing | `online-screenshot-test.md` |
| Feature rule references | `skill-references/architecture-lifecycle.md`, `skill-references/task-authoring-style.md`, `skill-references/webui-electron-news.md` |
| Migration record | `mdc-migration.md` |

## Tool Adapters

- `AGENTS.md`: Codex project entry.
- `CLAUDE.md`: Claude Code project entry.
- `.cursor/rules/00-shared-project-rules.mdc`: Cursor always-on entry.
- `.cursor/rules/online-screenshot-test.mdc`: Cursor screenshot-test trigger.

Project-local `.codex/` and `.claude/` skill/cache directories are intentionally git-ignored; keep durable shared rules in `docs/agents/`.

Keep durable rules here. Tool-specific files should be thin adapters. When code changes behavior, update `docs/AutoScriptor/` first, then update these shared rules only when the change affects future agent behavior.
