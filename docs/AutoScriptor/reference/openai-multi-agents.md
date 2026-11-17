# OpenAI可选方案

Historical design, not battle execution or integrated startup. Intended `examples/openai_multi_agents.py` is absent in this checkout; do not claim runnable support.

`agent.as_tool` lets coordinator retain control (planner/safety/docs); `handoffs` transfers control to a specialist. Any future example stays outside startup/WebUI/scheduler/tasks. Opt-in environment only: install openai/openai-agents, set OPENAI_API_KEY and optional OPENAI_AGENT_MODEL; never add them to main requirements for an example. No private account files/screenshots/logs/runtime access without explicit new tools and authorization; never commit keys.
