---
name: media-ingestion
description: Ingest YouTube transcripts, Twitter/X threads, Reddit discussions, GitHub repos, and web articles via Agent-Reach.
metadata:
  channels: [youtube, twitter, reddit, github, web]
---

# Agent-Reach Media Ingestion Protocol

Use this skill when the user provides an external URL to be saved into the knowledgebase.

## Supported Channels
- **YouTube**: Ingests video title, channel, description, and Whisper audio transcription into `corpus/web/`.
- **Twitter / X**: Ingests tweets and thread chains into `corpus/twitter/`.
- **Reddit**: Ingests post body and top community discussions into `corpus/web/`.
- **GitHub**: Ingests repository README and file outlines into `corpus/github/`.
- **Web**: Ingests clean Markdown via Jina Reader into `corpus/web/`.

## Execution
Call `tool_call(tool_name="ingest_url", arguments={"url": "...", "type": "auto", "transcribe": false})` or trigger through the Control Plane `/api/connectors/reach` endpoint.
All files are saved with the locked 9-field YAML frontmatter, mandatory summary blockquote, and `# Title`.
