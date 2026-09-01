# 0006-wiki-synthesis-layer-not-runtime-kg.md

# Wiki synthesis layer, not a runtime knowledge graph

We add a wiki-compilation step (llm-wiki-compiler) that runs
after ingestion, producing interlinked synthesis pages from the raw corpus.
We reject runtime knowledge graph platforms (Cognee, Graphiti, Semantica)
because they require running services that cannot be deployed to Cloudflare
Pages, compete with QMD's retrieval rather than complementing it, and add
infrastructure complexity that marginal gain doesn't justify for a
personal-scale corpus. The wiki pages live in corpus/wiki/ as a separate
QMD collection and serve as the primary navigation surface on the static
mirror.