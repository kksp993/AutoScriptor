# OpenAI Multi-Agent Example

This repository includes an optional OpenAI Agents SDK example at
`examples/openai_multi_agents.py`. It is not part of AutoScriptor startup,
WebUI, scheduler, task registration, or source install.

## What It Creates

The example contains two multi-agent patterns:

- `tools` mode: an `AutoScriptor Coordinator` calls three specialist agents as
  tools: task planner, safety reviewer, and docs reviewer. The coordinator keeps
  control and synthesizes the final answer.
- `handoff` mode: an `AutoScriptor Triage` agent transfers control to one
  specialist: task authoring, WebUI/backend, or documentation.

This follows the OpenAI Agents SDK guidance that multi-agent systems can use
`agent.as_tool(...)` when the main agent should keep control, or `handoffs=[...]`
when a specialist should take over.

## Setup

The dependencies are intentionally optional. Install them only when you want to
run the example:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade openai openai-agents
```

Set an API key in the current shell. Do not commit API keys or account files:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

Optionally choose a model:

```powershell
$env:OPENAI_AGENT_MODEL = "gpt-5"
```

## Run

Default `tools` mode:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples\openai_multi_agents.py
```

Custom prompt:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples\openai_multi_agents.py "Plan a safe AutoScriptor reward-collection task"
```

Handoff mode:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples\openai_multi_agents.py --mode handoff "How should I update WebUI docs after adding a route?"
```

## Boundaries

- This example must stay outside the main source runtime unless a future task
  explicitly asks to integrate OpenAI API calls into AutoScriptor.
- Do not add `openai` or `openai-agents` to `requirements.txt` for this optional
  example alone.
- The script does not read private account JSON, emulator screenshots, logs, or
  WebUI state unless a future change explicitly adds such tools.
