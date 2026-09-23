# 0010 — Pi Agent Monorepo Promotion & JSON-RPC Bridge

## Context
A personal knowledgebase requires autonomous goal execution (multi-turn tool execution, skill invocation, deep research, and automated synthesis). Early experiments considered cherry-picking individual scripts or relying on external proprietary CLI agents. However, partial ports created fragile boundaries, missing dependencies, and inconsistent tool loop behaviors.

## Decision
We promote the full upstream `earendil-works/pi` monorepo into `engine/pi/` and wrap it with an asynchronous, process-isolated JSON-RPC bridge (`engine/pi_bridge.py`).

1. **Full Monorepo Promotion**: Rather than maintaining a fragmented fork or selective subsets, the entire Pi Agent engine lives within the repository under `engine/pi`, providing complete access to its session tree, tool registry, prompt assemblies, and ReAct loop.
2. **JSON-RPC 2.0 Subprocess Protocol**: All external callers (Web Control Plane, Telegram bot, Discord bot, REST endpoints) communicate with the agent via standard stdin/stdout JSON-RPC (`task.start`, `task.input`, `task.cancel`, streaming events `thought`, `tool_call`, `observation`, `answer`).
3. **Decoupled Architecture**: The agent runs in an isolated Python process, preventing memory leaks, GIL contention, or native crashes from taking down the core QMD search server or Web Control Plane.

## Consequences
- Guarantees 100% fidelity to upstream Pi Agent behavior without code drifting.
- Uniform headless interface allows any client interface to trigger, stream, and interact with agent tasks in real time.
- Standardizes ReAct event schemas across the entire ecosystem.
