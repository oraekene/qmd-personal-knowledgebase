# 0012 — Multi-Client Autonomous Gateways & Visual Execution Trace Engine

## Context
Users interact with personal knowledgebases from diverse environments: mobile messaging (Telegram, Discord), native desktop/terminal, automated webhooks/REST clients, and browser dashboards. Furthermore, when an autonomous ReAct agent executes long-horizon tasks, textual terminal logs are difficult to parse, obscuring whether the agent is thinking, invoking tools, observing output, or answering.

## Decision
We implement a unified multi-client gateway layer coupled with a visual execution trace engine:

1. **Pluggable Client Gateways**:
   - `gateways/bot_gateway.py`: Background long-polling daemon for Telegram and Discord, forwarding user prompts directly to the Pi Agent JSON-RPC bridge or QMD semantic search.
   - `gateways/openapi_router.py`: Standard REST / OpenAPI endpoint layer for external integrations, scripting, and webhooks.
   - Web Control Plane (`control_plane/server.py`): Real-time SSE / WebSocket dashboard for system health, service supervision, configuration, and task orchestration.
2. **Visual ReAct Execution Trace**:
   - In the Web Control Plane Task Console, we render a live interactive vertical timeline graph alongside the raw JSON-RPC stream.
   - Distinct semantic step cards visually differentiate:
     - 🧠 **Thought**: Internal agent reasoning and planning.
     - 🔧 **Tool Call**: Action name and formatted input parameters.
     - 👁️ **Observation**: Output or return data from invoked tool.
     - 💬 **Answer**: Final user response or interim conclusion.
   - Cards are collapsible, highlight error states in red, and provide real-time step counter and execution duration metrics.

## Consequences
- Single-point agent integration: any client interface can invoke the same agent loop with identical capabilities.
- Clear observability into autonomous reasoning cycles without needing to inspect raw debug logs.
- Immediate mobile and desktop access to knowledgebase search and autonomous research workflows.
