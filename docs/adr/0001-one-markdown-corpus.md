# 0001-one-markdown-corpus.md

# One markdown corpus, one index

All ingestion sources normalize into a single markdown tree (one file per
logical unit, YAML frontmatter, silo-as-subtree), indexed by QMD as
collections. Chosen over per-silo indexes and query-time conversion because
QMD's model is a directory of markdown: silo scoping becomes subtree
scoping, and one index serves both unified and scoped search.