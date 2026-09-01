# Spec: QMD-Powered Personal Knowledgebase and Search Engine

## Problem Statement

My knowledge is scattered across a dozen surfaces — X bookmarks, AI chat
sessions on six platforms (Claude, ChatGPT, Gemini, Qwen, Z.ai, DeepSeek),
Simplenote and Google Keep notes, two GitHub accounts' worth of forked and
starred repos, PDFs, and the web pages all of these link to. No tool can
search them together. Every brainstorming session starts from zero because
I can't find the decisions I already made ("which OCR tool did I pick, and
why?") without manually re-deriving them. The goal is a single knowledgebase
that automatically ingests all of these sources, is searchable as a whole or
per source, and is reachable from every chat frontend I actually use — so it
becomes the default starting point for all my thinking.

## Solution

Every source normalizes into one markdown Corpus — a single directory tree
whose top-level subtrees (Silos) map one-to-one to QMD collections. One file
per logical item (Unit), each carrying structured Frontmatter and a Summary
Line. Python Connectors extending the existing SourcePlugin pattern pull from
each source on independent schedules; an external Orchestrator runs them,
tolerates individual failures, then re-indexes. QMD provides all search
through its native CLI, MCP, and HTTP interfaces. The corpus is reachable
from anywhere via four Query Faces: local CLI/MCP, a Cloudflare-Tunneled MCP
endpoint (for Claude.ai web custom connectors) behind a token auth proxy, and
a full Static Mirror on Cloudflare Pages with llms.txt and a URL-embedded
token that any web chat's fetch tool can read. A standing agent rule makes
MCP-capable agents search the knowledgebase before answering open questions.

## User Stories

1. As the owner, I want to search every source I own through one query, so that no knowledge stays siloed.
2. As the owner, I want to scope a search to one silo, so that results reflect only that source family.
3. As the owner, I want to scope a search to a single chat platform, so that I can retrace one conversation thread.
4. As the owner, I want searches to surface my past decisions with their surrounding context, so that I never re-derive a conclusion I already reached.
5. As the owner, I want search results to identify which source they came from, so that I can judge their provenance.
6. As the owner, I want to jump from a search hit back to the original item, so that I can verify or continue the thread at its origin.
7. As the owner, I want to browse the corpus as plain directories, so that I can inspect and hand-edit anything the machine indexed.
8. As the owner, I want my GitHub owned/forked/starred repos from both accounts ingested on a six-hour schedule, so that the corpus tracks what I collect without manual runs.
9. As the owner, I want no repository duplicated across my two GitHub accounts, so that search results aren't doubled.
10. As the owner, I want new X bookmarks ingested daily without a paid API, so that my bookmark backlog is searchable as it grows.
11. As the owner, I want the Twitter silo bootstrapped from a manual export, so that the corpus is useful on day one before scraping ever succeeds.
12. As the owner, I want to drop a chat export archive into an Inbox folder and have it become searchable Units, so that ingesting my chat histories takes seconds.
13. As the owner, I want long chat sessions split into coherent chunks, so that search hits return readable relevant segments rather than whole sessions.
14. As the owner, I want my Simplenote and Keep notes in the corpus, so that quick captures are searchable alongside everything else.
15. As the owner, I want PDFs parsed locally, so that private documents become searchable without ever leaving my machine.
16. As the owner, I want links found in newly ingested Units fetched one level deep, so that the corpus contains the pages my sources point at.
17. As the owner, I want each Unit stamped with both origin time and ingestion time, so that I can judge freshness.
18. As the owner, I want a single connector failure (e.g. an expired X cookie) to pause only that connector, so that the rest of the pipeline keeps running.
19. As the owner, I want PDFs processed automatically when dropped in a watched folder, so that ingestion needs no command.
20. As the owner, I want connector state persisted across failures, so that recovery resumes instead of re-crawling.
21. As the owner, I want to query the corpus from the terminal, so that search is instant in my working environment.
22. As the owner, I want to start a chat at claude.ai in the browser and have Claude query my knowledgebase through a custom connector, so that web brainstorming starts from my accumulated context.
23. As the owner, I want the local MCP endpoint exposed at a stable tunneled URL, so that connector setup never changes between sessions.
24. As the owner, I want the tunnel to survive laptop sleep/wake, so that access recovers without intervention.
25. As the owner, I want unauthorized requests to the tunneled endpoint rejected, so that my corpus isn't readable by whoever learns the URL.
26. As the owner, I want the whole corpus published as web pages that any web chat's fetch tool can read, so that ChatGPT, Gemini, Z.ai, DeepSeek, and Qwen sessions can also use my knowledgebase.
27. As the owner, I want the mirror protected by a token embedded in its URLs, so that only chats I've pasted a link into can reach it.
28. As the owner, I want mirror access revocable instantly by token rotation, so that a leaked URL costs one redeploy rather than exposure.
29. As the owner, I want an llms.txt map of the corpus, so that agents navigate the knowledgebase structure without blind crawling.
30. As the owner, I want the mirror updated automatically after every pipeline run, so that web chats always see current data.
31. As the owner, I want the acceptance test runnable on demand, so that I can verify the whole system after any change.
32. As the owner, I want 50 new Units to go from ingestion to searchable in under five minutes, so that the feedback loop is usable as a daily driver.
33. As the owner, I want the core system to run entirely on free tiers and local compute, so that the knowledgebase costs nothing to operate.
34. As an AI agent in opencode, I want QMD's query and get tools available via MCP, so that I consult the corpus before answering open questions.
35. As an AI agent in opencode, I want a standing instruction to search the knowledgebase first, so that every brainstorming session starts from prior context unprompted.
36. As a Claude.ai web session, I want the corpus exposed as a remote MCP custom connector, so that I can retrieve and cite the owner's prior decisions mid-conversation.
37. As a web chat with a fetch tool, I want corpus Units at predictable URLs, so that I can incorporate them when the owner pastes a link.
38. As the maintainer, I want new sources added as SourcePlugin connectors without touching the Orchestrator, so that the system grows one file at a time.
39. As the maintainer, I want QMD treated as a black-box engine, so that search-quality work stays in configuration, never in code.
40. As the maintainer, I want the architecture ready to migrate to a VPS by repointing one tunnel, so that phase 2 is a deployment change, not a rewrite.
41. As the maintainer, I want gateway platforms (Composio, Nango) adoptable later without disturbing v1 connectors, so that SaaS sources like Gmail slot in when needed.
42. As the owner, I want Wiki Pages synthesizing related Units into topic pages, so that web chats get curated context instead of scattered fragments.
43. As a web chat, I want Wiki Pages that link to related pages and cite their sources, so that I can navigate the knowledgebase without blind fetching.
44. As the owner, I want raw Units left untouched by compilation, so that ground truth is never silently rewritten.
45. As the owner, I want the Synthesis Pass failing without blocking the rest of the pipeline, so that an LLM outage costs freshness, not ingestion.
46. As the owner, I want compile frequency configurable, so that LLM spend on synthesis stays predictable and optional.

## Implementation Decisions

- **Corpus shape:** one markdown tree; silos as top-level subtrees, each
  registered as a QMD collection: github, chats (with per-platform
  subdirectories: claude, chatgpt, gemini, qwen, zai, deepseek),
  twitter/bookmarks, notes (simplenote, keep), pdfs, web. Silo scoping is
  path scoping; unified search is unscoped query across all collections.
- **Unit format:** one file per logical item. Frontmatter fields (schema is
  normative): `source` (connector name), `silo`, `source_id` (native ID at
  origin), `url` (permalink where one exists), `created_at` (origin time),
  `ingested_at` (pull time), `tags`, `author` (for multi-voice sources),
  `content_hash` (dedup). No title field — derived from the first heading.
- **Summary Line:** every Unit body opens with a one-sentence blockquote
  describing the unit, immediately after frontmatter.
- **Per-silo body templates:** GitHub repo files carry file content as-is;
  issues are separate Units with structured comment sections. - Chat session Units alternate speaker sections and are written as
  one file per session regardless of length. No connector-side splitting:
  all chunking is QMD's (900-token chunks, 15% overlap, regex default,
  AST-aware for code), per ADR-0007. The 	-Split-Tool plays no role
  in the runtime.
  Twitter units carry tweet text, quoted tweet, and link targets. PDF units
  carry extracted text with page separators. Web units carry fetched markdown.
- **Connectors:** Python, extending the existing SourcePlugin architecture
  (forward scan, lookback, CrawlState persistence). The existing GitHub
  extractor runs per account with separate tokens; a normalizer maps its
  output into Units. Two-account dedup: first-seen wins on repo full name.
- **Schedules:** GitHub six-hourly; X bookmarks daily; link expansion runs
  against whatever was newly ingested after each connector pass; PDFs
  batch-triggered on drop; notes event-driven or manual-drop.
- **Chats and notes ingestion:** Inbox folder for manual export drops
  (ZIPs unpacked by the normalizer). Simplenote via API if live, else export;
  Keep via Takeout. No v1 automation of chat-history scraping.
- **X bookmarks:** cookie-session scraping on the daily schedule, accepting
  ToS/breakage risk (ADR-0005), bootstrapped by a manual export so the silo
  is populated from day one.
- **PDFs:** LiteParse locally for the on-disk collection; Firecrawl reserved
  for crawl-encountered and stubborn documents.
- **Link expansion:** TinyFish fetch primary (free tier), one level deep,
  only for links inside newly ingested Units; Scrapling as fallback handler
  for failed fetches. SearXNG remains a discovery-side channel, not a fetcher.
- **Orchestration:** an external scheduled script runs each connector
  independently, isolates and logs failures, then runs one combined
  re-index-plus-embed. QMD's per-collection update command is deliberately
  unused — its abort-on-failure behavior is too fragile for cookie-dependent
  connectors.
- **Search engine:** QMD as-installed. Collections = silos. Context
  descriptions per collection and a global context. No custom search code.
- **Query faces:** QMD's native CLI, MCP (stdio for local agents; HTTP daemon
  for shared use), and HTTP endpoints. MCP-over-HTTP exposed through a
  Cloudflare Tunnel, with origin allowlisting for the Claude.ai domain and
  an auth proxy checking a shared-secret token in the Authorization header.
  Claude.ai web attaches the tunnel URL as a custom connector.
- **Static Mirror:** the full corpus deployed to Cloudflare Pages after every
  pipeline run, with llms.txt at the root and a Mirror Token embedded in the
  URL path prefix — the only auth mechanism web-chat fetch tools can carry.
  Revocation is token rotation plus redeploy.
- **Agent rule:** a global instruction (agent config) telling MCP-capable
  agents to prefer the QMD query/get tools before answering open questions.
- **Phasing:** v1 is local-first. Phase 2 moves the corpus and connectors to
  a VPS and repoints the tunnel. Phase 3 admits connector gateways for
  SaaS sources needing managed OAuth.
- **Wiki synthesis layer:** after qmd update and embed, the orchestrator runs
  the Wiki Compiler over newly ingested Units, producing interlinked,
  citation-traceable Wiki Pages in corpus/wiki/. The wiki is a derived view:
  raw Units are never rewritten by compilation. Wiki Pages carry standard
  frontmatter (source: the compiler's name, silo: wiki) and are indexed by
  QMD as a wiki collection, searchable scoped or unified. The wiki directory
  is the primary navigation surface on the Static Mirror — web chats fetch
  curated, interlinked pages instead of scattered raw Units. The compiler is
  the sole LLM-calling ingestion component; its cost is bounded by compile
  frequency, which is a configuration knob. - The Wiki Compiler routes LLM calls through any OpenAI-compatible
  endpoint, configured via environment variables. Default: Cloudflare Workers
  AI free tier (10K Neurons/day, no data retention) with
  Llama-3.1-8b-instruct-fp8-fast. The provider is swappable without code
  changes — upgrading synthesis quality means pointing the compiler at a
  different base URL. Free-tier providers that use inference data for
  training are excluded from consideration.

## Testing Decisions

- A good test observes external behavior only: source fixtures go in, Units
  come out on disk; a corpus goes in, search results come out. Connectors
  are never tested through their internal call sequence.
- **One seam:** the corpus + QMD index. Connector tests run a connector
  against fixture inputs (captured API responses, sample export archives,
  sample PDFs, sample bookmark HTML) and assert Units written to the silo
  with correct frontmatter and body structure. Search tests ingest a fixture
  corpus, update and embed, then assert query results and scoping behavior.
- Prior art: the SourcePlugin pattern's yield-and-persist behavior is the
  existing connector seam; QMD's own fixture-based benchmark collections are
  prior art for search-quality assertions; the existing extractor's output
  layout is the fixture format for the GitHub normalizer.
- Thin integration smoke tests at the two external HTTP boundaries: the auth
  proxy (correct token passes, wrong token rejected) and the mirror (serves
  current corpus files under the token path; llms.txt present; untokenized
  paths unreachable).
- The acceptance test is the end-to-end gate and stays runnable on demand:
  a known personal-decision query ("OCR models I selected") returns relevant
  own-notes/own-chats Units in the top five; silo scoping works; no duplicate
  repos across accounts; the tunnel recovers after sleep/wake; a 50-unit
  batch reaches searchable state in under five minutes; a fresh Claude.ai web
  chat retrieves corpus Units through the custom connector.
- Wiki collection is queryable like any silo (scoped search works; wiki hits
  surface alongside raw hits in unified search).
- Every Wiki Page citation resolves to an existing Unit path on disk.
- A Synthesis Pass failure (missing API key, provider outage) is isolated and
  logged by the orchestrator — connectors, indexing, and mirror deploy still
  complete.

## Out of Scope

- Screenshot and voice-note OCR (parked; graduates after v1 acceptance if
  the corpus's own record of prior OCR-model decisions confirms a choice).
- The Firecrawl Research Index.
- Telegram bot and Hermes integration (phase 2, with the VPS).
- The VPS migration itself (phase 2; architecture is ready but unexecuted).
- SaaS gateway connectors — Gmail, Notion, calendar, etc. (phase 3).
- Bespoke per-platform chat plugins (permanently rejected in favor of the
  four Query Faces).
- Writing or modifying any search/ranking code (QMD is a black box).
- Multi-user access control beyond token rotation.
- Live automated sync of AI chat histories (v1 is export drops; automating
  the heaviest platform is a later, separate decision).
- Link crawling deeper than one level.
- Runtime knowledge graph platforms (Graphiti, Cognee, Semantica) and any
  graph database dependency — permanently rejected per ADR-0006.

## Further Notes

- The glossary in CONTEXT.md is normative for this spec; all future tickets
  and specs use Corpus, Silo, Unit, Connector, Query Face, Mirror Token, etc.
- Five ADRs govern the architecture and must be respected: one markdown
  corpus (0001), QMD-native query faces plus static mirror (0002),
  URL-embedded token on the mirror (0003), Python SourcePlugin connectors
  with gateways deferred (0004), X bookmarks via cookie-scraping (0005).
- Accepted risks, on record: X account-level ToS risk from low-volume
  self-scraping; mirror exposure bounded by token rotation; unauthenticated
  local endpoints assumed safe behind loopback plus the auth proxy.
- Bootstrap order matters for day-one usefulness: manual exports (X
  bookmarks, chat archives, notes exports, existing GitHub extraction
  output) seed the corpus before any scheduled connector ever fires.
  
  