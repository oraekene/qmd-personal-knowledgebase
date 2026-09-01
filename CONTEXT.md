# CONTEXT.md

Personal search engine and knowledgebase: every digital source (GitHub, AI
chats, X bookmarks, notes, PDFs, fetched pages) normalizes into one markdown
corpus, indexed and served by QMD across four query faces.

## Language

**Corpus**:
The single markdown tree QMD indexes — the system's whole memory. Silos are its top-level subtrees.
_Avoid_: database, library, knowledge store

**Silo**:
A top-level corpus subtree equal to one source family; maps 1:1 to a QMD collection and is the unit of scoped search.
_Avoid_: category, bucket, source type

**Unit**:
One markdown file representing one logical item (tweet, chat session, note, PDF, fetched page, repo doc). Carries Frontmatter and opens with a Summary Line.
_Avoid_: record, document, entry

**Frontmatter**:
The YAML header on every unit: source, silo, source_id, url, created_at, ingested_at, tags, author, content_hash.
_Avoid_: metadata, properties

**Summary Line**:
The one-sentence blockquote immediately after frontmatter describing the unit; becomes a high-signal chunk for vector search.
_Avoid_: abstract, description field

**Connector**:
A Python script extending the SourcePlugin pattern that pulls from one source and writes units into its silo.
_Avoid_: crawler, scraper, integration

**SourcePlugin**:
The connector base class: forward scan, lookback scan, CrawlState cursor persistence, per-source config.
_Avoid_: adapter, provider

**Inbox**:
The watched folder where manual export drops (chat exports, X bootstrap export, Keep Takeouts) land for the normalizer to unpack.
_Avoid_: upload, staging, dropbox

**Orchestrator**:
The external cron script that runs connectors on independent schedules, tolerates individual failures, then runs `qmd update && qmd embed` once.
_Avoid_: scheduler, pipeline, update-cmd

**Query Face**:
One of four presentations of the corpus: QMD CLI, QMD MCP (tunneled), QMD HTTP, or the Static Mirror.
_Avoid_: plugin, integration, frontend

**Tunnel**:
The Cloudflare Tunnel exposing QMD's HTTP MCP daemon so Claude.ai web can attach it as a custom connector.
_Avoid_: proxy, bridge

**Auth Proxy**:
The middleware between tunnel and QMD checking a shared-secret token in the Authorization header.
_Avoid_: gateway, firewall

**Static Mirror**:
The full corpus deployed on Cloudflare Pages with llms.txt and a Mirror Token — the query face every web chat's fetch tool can reach.
_Avoid_: website, public site, backup

**Mirror Token**:
The secret in the static mirror's URL path prefix; the only auth fetch tools can carry. Revocable by rotation and redeploy.
_Avoid_: API key, password

**Wiki Page**:
A synthesis page under corpus/wiki/, compiled from raw Units, interlinked
with other Wiki Pages and citing the Units it was derived from. Derived
knowledge, never ground truth.
_Avoid_: article, node, graph node

**Synthesis Pass**:
The orchestrator step after qmd embed that runs the Wiki Compiler over new
Units and produces or refreshes Wiki Pages.
_Avoid_: enrichment, post-processing, indexing

**Wiki Compiler**:
The tool (llm-wiki-compiler or successor) that performs the Synthesis Pass.
The only LLM-calling component in the ingestion pipeline.
_Avoid_: knowledge graph engine, memory platform