---
name: knowledge-retrieval
description: Search, inspect, and retrieve information across personal notes, wiki concepts, chats, github, and web docs.
metadata:
  silos: [notes, wiki, github, chats, pdfs, web, twitter]
---

# Knowledge Retrieval Protocol

Use this skill when you need to answer questions or find facts from the personal knowledgebase.

## Instructions
1. **Choose the Right Silo**:
   - `notes`: Quick user notes, personal ideas, Simplenote / Keep archives.
   - `wiki`: Synthesized topic hubs, compiled conceptual summaries.
   - `github`: Code repos, commit histories, repo issues, READMEs.
   - `chats`: Past conversation transcripts with Claude and ChatGPT.
   - `pdfs`: Whitepapers, manuals, and parsed documents.
   - `web`: Ingested articles, YouTube transcripts, Reddit discussions.
   - `twitter`: Saved tweet threads and social discussions.
2. **Execute Fast Search**:
   - Use the `search` tool with a specific query and optional `silo`.
3. **Deep Inspection**:
   - Inspect top result paths using `get(file="corpus/...")` to read exact contexts.
4. **Citation Format**:
   - Always reference sources using `qmd://<relative-path>` URI links.
