# Complete Implementation Plan: Autonomous Knowledgebase & Multi-Client Execution Engine

This document specifies the end-to-end technical architecture, system design, and implementation plan for transforming the **QMD Personal Knowledgebase** into a full-fledged **Autonomous Intelligence and Multi-Client Execution Platform**.

---

## 1. System Overview & Architecture

The platform operates across three interconnected layers:
1. **Core Data & Knowledge Storage**: QMD SQLite database (FTS5 BM25 + Vector embeddings) with siloed markdown repositories under `corpus/` (`notes`, `wiki`, `github`, `chats`, `pdfs`, `web`, `twitter`).
2. **Autonomous Execution Gateway & Control Plane**: A unified Python backend running the Web Control Plane (`:3333`), Auth Proxy & OAuth Shim (`:3210`), MCP Server Gateway (`:8181`), Hermes-inspired bot gateway, background scheduler, and sandbox runner.
3. **Multi-Client Access Surfaces**: Seven distinct clients ranging from desktop executables to thin mobile chat bots and coding IDEs.

```mermaid
flowchart TD
    subgraph Clients["Multi-Client Access Surfaces"]
        D1["1. Full Desktop App (Knowledgebase.exe)"]
        D2["2. Web Control Plane (localhost:3333)"]
        D3["3. Claude.ai (MCP Connector)"]
        D4["4. ChatGPT / Custom GPTs (OpenAPI)"]
        D5["5. Telegram / WhatsApp / Discord Bots"]
        D6["6. Mobile PWA / Static Mirror"]
        D7["7. Coding IDEs (Cursor, Claude Code, Antigravity)"]
    end

    subgraph Gateway["Autonomous Execution Gateway & Control Plane"]
        GW1["Control Plane Web UI (:3333)"]
        GW2["Auth Proxy & OAuth Shim (:3210)"]
        GW3["Hermes Bot Gateway (Telegram/Discord)"]
        GW4["Progressive Tool & Skill Engine"]
        GW5["Cron Scheduler & DAG Runner"]
        GW6["Sandbox Manager (Local / Cloud E2B)"]
    end

    subgraph Ingestion["Connectors & Ingestion Layer"]
        C1["Notes & Keep (connectors/notes.py)"]
        C2["Chats (connectors/chats.py)"]
        C3["PDFs & OCR (connectors/pdfs.py + LiteParse)"]
        C4["GitHub (connectors/github.py)"]
        C5["Agent-Reach (YouTube, Twitter, Reddit, Web)"]
        C6["Monid / Exa / Firecrawl"]
    end

    subgraph Core["QMD Storage & Search Engine"]
        Q1["QMD Engine (:8181)"]
        Q2["SQLite FTS5 (BM25)"]
        Q3["Vector Store (sqlite-vec)"]
        Q4["Corpus Silos (corpus/*)"]
    end

    Clients --> Gateway
    Gateway --> Ingestion
    Ingestion --> Core
    Gateway --> Core
```

---

## User Review Required

> [!IMPORTANT]
> **Key Architecture Decisions for Review:**
> 1. **Desktop App Technology**: Packaging the existing Control Plane frontend using **Tauri / Electron** into a standalone `.exe` so the desktop app and web dashboard share 100% of their UI and styling without design drift.
> 2. **Execution Engine Base**: Using the **Python-native Hermes architecture** embedded directly into the Control Plane for thin clients (Claude.ai, Telegram, WhatsApp) to eliminate Node/Python runtime impedance.
> 3. **Connector Integration**: Directly integrating [`Agent-Reach-main`](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/Agent-Reach-main) into `connectors/` for YouTube transcripts, Twitter/X, Reddit, and authenticated browser scraping.
> 4. **Cloud Sandbox Provider**: Supporting **E2B microVMs** or **Modal** as the optional cloud fallback when long-running jobs are triggered while the local PC is shut down.

---

## Open Questions

> [!NOTE]
> 1. For cloud sandboxing (when running tasks while the local computer is shut down), do you prefer an **E2B API key** (ephemeral Linux microVMs in the cloud) or an **always-on VPS/server**?
> 2. For the Telegram bot token, would you like the bot setup wizard integrated directly into the Control Plane Settings tab?

---

## Proposed Changes by Feature Area

---

### Feature 1: Engine Retrieval Mode Toggle (`CPU-only` vs. `Full`)

Allow users to switch between lightning-fast BM25 retrieval (<2s on CPU) and full semantic reranking with vector batching (intended for GPU/high-spec machines).

#### [MODIFY] [server.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/auth_proxy/server.py)
* Read `RETRIEVAL_MODE` from environment (`cpu-only` vs `full`).
* In `cpu-only` mode: intercept `tools/call` for `query` and force `rerank: false`.
* In `full` mode: pass `rerank: true` (or client argument) without override.

#### [MODIFY] [store.ts](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/qmd-main/src/store.ts)
* Add `QMD_RETRIEVAL_MODE` environment variable check.
* When set to `cpu-only`: enable automatic `OR` BM25 fallback on 0-hit `AND` queries; skip `expandQuery` and vector batching when `skipRerank: true`.
* When set to `full`: enforce strict `AND` queries and run full LLM expansion and dense vector embeddings.

#### [MODIFY] [server.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/server.py)
* Add `RETRIEVAL_MODE` status to `/api/status` and `/api/config`.
* Add an endpoint `POST /api/engine/mode` to toggle modes, update `.env`, and trigger daemon restarts.

#### [MODIFY] [index.html](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/static/index.html)
* Add a visual **Engine Retrieval Mode** toggle card on the dashboard:
  - `[ ○ CPU-Only (Fast BM25 <2s) ]`
  - `[ ● Full (Dense Vectors + GPU Reranker) ]`

---

### Feature 2: Silo-Specific Scoped Search

Enable precise keyword and semantic querying scoped to individual corpus partitions.

#### [MODIFY] [server.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/server.py)
* Update `/api/search` handler to parse `silo` query parameter (`all`, `notes`, `wiki`, `github`, `chats`, `pdfs`, `web`, `twitter`).
* Pass `-c <silo>` / `--collection <silo>` to the QMD search command.
* Format JSON output to return the matching silo name and relative file path.

#### [MODIFY] [index.html](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/static/index.html)
* Add a Silo Scoped Filter selector adjacent to the search input:
  `[ 🔍 Search... ] [ All Silos ▾ | Notes | Wiki | Chats | GitHub | PDFs | Web ] [ Search ]`.
* Display silo badges on search result cards with direct link to document contents.

---

### Feature 3: System Prompt & User Customization Engine (Thin-Client Support)

Give thin clients (Claude.ai, ChatGPT, Telegram) full access to personal rules, personas, tone guidelines, and directory-specific constraints without needing an IDE.

#### [NEW] [SYSTEM_PROMPT.md](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/SYSTEM_PROMPT.md)
* Base system persona, citation rules, and response formatting guidelines.

#### [NEW] [prompt_engine.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/auth_proxy/prompt_engine.py)
* Dynamic system prompt synthesizer:
  - Combines `SOUL.md` (Persona), `SYSTEM_PROMPT.md` (Operational Guidelines), and active silo `AGENTS.md`.
  - Injects dynamic prompt into MCP `initialize` instructions.
  - Implements MCP Prompts specification (`prompts/list` and `prompts/get`) exposing templates: `knowledge-search`, `wiki-synthesis`, `deep-investigation`.

#### [MODIFY] [index.html](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/static/index.html)
* Add a **"Persona & System Prompts"** tab in the Control Plane to edit instructions, adjust tone, and save changes without touching files.

---

### Feature 4: Comprehensive Connectors Ecosystem

Unify all ingestion sources into a standardized, one-click or automated pipeline.

```
connectors/
├── notes.py          # Simplenote & Keep ZIPs (Existing)
├── chats.py          # Claude.ai & ChatGPT exports (Existing)
├── pdfs.py           # PDFs & OCR extraction (Existing)
├── github.py         # Git repository cloning & tracking (Existing)
├── web.py            # URL scraping & clean Markdown (Existing)
└── reach.py          # Agent-Reach bridge: YouTube transcripts, Twitter, Reddit (NEW)
```

#### [NEW] [reach.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/connectors/reach.py)
* Import and wrap channels from [`Agent-Reach-main/agent_reach/channels/`](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/Agent-Reach-main/agent_reach/channels):
  - YouTube video URL -> audio transcription (`transcribe.py`) -> formatted summary in `corpus/web/`.
  - Twitter / X thread URL -> tweet chain extraction -> `corpus/twitter/`.
  - Reddit post/thread -> discussion extraction -> `corpus/web/`.
  - Authenticated web scraping using browser cookies (`cookie_extract.py`).

#### [MODIFY] [server.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/server.py)
* Expose API endpoints for triggering connector actions:
  - `POST /api/connectors/youtube`
  - `POST /api/connectors/github`
  - `POST /api/connectors/web`

---

### Feature 5: Progressive Tool Calling & Skill Disclosure (Hermes Pattern)

Eliminate token bloat and tool confusion in thin clients like Claude.ai and Telegram.

#### [NEW] [progressive_tools.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/auth_proxy/progressive_tools.py)
* Implements the 3-tier disclosure model researched from Hermes:
  - **Tier 1 (Catalog)**: `skills_list` returns only names and short descriptions (<200 tokens total).
  - **Tier 2 (Activation)**: `skill_view(skill_name)` returns full `SKILL.md` instructions when needed.
  - **Tier 3 (Bridge Execution)**:
    - `tool_search(query)`: Finds relevant tools by keyword.
    - `tool_describe(tool_name)`: Returns exact input schema on demand.
    - `tool_call(tool_name, arguments)`: Dynamically executes the target tool on the server.

---

### Feature 6: Server-Side Crons, Automations & Sandboxes

Allow users to set up recurring knowledge syncs and long-running autonomous tasks that continue even when their personal computer is shut down.

#### [NEW] [scheduler.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/scheduler.py)
* Background daemon thread inside Control Plane.
* Evaluates cron expressions or interval timers against `automations.json`.
* Executes tasks locally or routes to sandboxes.
* Emits progress and execution logs into `SystemLogger`.

#### [NEW] [sandbox.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/sandbox.py)
* Dual-tier execution sandbox:
  - **Local Sandbox**: Docker / local isolated subprocess with timeouts and restricted disk access.
  - **Cloud Sandbox Handoff**: Connects to **E2B** or **Modal** cloud microVMs for long-running batch jobs initiated remotely (e.g. via Telegram when PC is asleep).
  - Synchronizes resulting markdown back to `corpus/` and pushes git/mirror updates.

#### [MODIFY] [index.html](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/static/index.html)
* Add an **"Automations & Crons"** tab:
  - Button-based schedule builder (no CLI typing).
  - Dropdown for Action: `[ Ingest Inbox | GitHub Sync | Re-index Embeddings | Deploy Mirror | YouTube Transcribe ]`.
  - Dropdown for Schedule: `[ Every 30 mins | Hourly | Daily at 02:00 | Custom ]`.
  - Dropdown for Execution: `[ Local Daemon | Cloud Sandbox (Off-PC) ]`.
  - Table of active schedules with toggle switch (ON/OFF), last run status, and next scheduled run.

---

### Feature 7: GUI Button-Based DAG / Decision Tree Workflow Engine

A visual pipeline builder to chain multiple tools and decision branches together.

#### [NEW] [workflow_engine.py](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/workflow_engine.py)
* Executes declarative directed acyclic graphs (DAGs) defined in `workflows/*.json`.
* Supports conditional evaluation (e.g. `if step.detect.is_scanned == true then step.ocr else step.text`).
* Exposes an MCP tool: `run_workflow(workflow_id, params)` for Claude.ai and Telegram bots.

#### [MODIFY] [index.html](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/control_plane/static/index.html)
* Add a **"Visual Workflows"** tab:
  - Visual block canvas to build pipelines:
    - **Trigger Block**: File upload, Cron, or Webhook.
    - **Condition Block**: Check file type, size, or content keywords.
    - **Action Blocks**: Run OCR, Scrape URL, Summarize with LLM, Index into QMD, Send Telegram alert.
  - Visual run tracker showing live progress through the decision tree.

---

### Feature 8: Standalone Desktop Executable (`Knowledgebase.exe`)

The primary windowed desktop application.

#### [NEW] [desktop/](file:///c:/Users/rotim/Documents/QMD%20powered%20Personal%20Knowledgebase%20and%20Search%20Engine/desktop)
* Tauri / Electron packaging configuration.
* Embeds the Control Plane UI directly into a native Windows window.
* Automatically launches and supervises the local Python backend and QMD daemon on startup.
* System tray integration: keeps running in background with quick access to search and sync.

---

## Verification Plan

### Automated Tests
1. **Engine Mode Verification**:
   - Test toggle between `cpu-only` and `full`.
   - Verify `auth_proxy` parameter interception (`rerank: false` vs `rerank: true`).
2. **Silo Search Verification**:
   - Run scoped searches against `notes`, `chats`, and `wiki` collections and assert no bleed-through across silos.
3. **Connectors Verification**:
   - Test `Agent-Reach` integration on YouTube transcript extraction and Twitter thread fetching.
4. **Progressive Disclosure Verification**:
   - Verify `skills_list` payload is <500 bytes.
   - Verify `tool_search` finds deferred tools on demand.
5. **Scheduler & Workflow Tests**:
   - Validate cron execution, conditional DAG branching, and failure recovery.
6. **Full Suite Regression**:
   - Run `uv run --with pytest python -m pytest tests/` and assert 100% pass rate.

### Manual & End-to-End Verification
1. **Claude.ai Live Verification**:
   - Query `https://kb.parmeterai.space/mcp` from Claude.ai and verify sub-second response, silo filtering, and progressive tool invocation.
2. **Control Plane UI Verification**:
   - Test the visual schedule builder and verify a scheduled job runs without errors.
   - Test the visual DAG workflow runner with a test PDF.
3. **Desktop Executable Verification**:
   - Launch `Knowledgebase.exe` and confirm seamless UI rendering, status monitoring, and search.
