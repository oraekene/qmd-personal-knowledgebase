# 0011 — Cloudflare Artifacts (Git Versioning) & R2 Binary Snapshot Sync

## Context
A rich personal knowledgebase accumulates gigabytes of user corpus data over time (documents, notes, chat histories, crawled web pages, vector indices, SQLite databases). Storing entire user corpora inside GitHub repositories creates severe practical issues: git repo bloat, strict GitHub storage and push limits, LFS billing overhead, and privacy exposure risks. At the same time, users need Git-grade revision history, point-in-time rollbacks, and zero-configuration cloud backup.

## Decision
We decouple textual version control from binary snapshot storage using Cloudflare developer platform primitives:

1. **Cloudflare Artifacts for Textual Corpus**: The markdown corpus (`corpus/`) is committed and synchronized against a Cloudflare Artifacts edge Git repository. This yields branchable, commit-tracked revision histories with instant rollback capability via standard Git protocols, without cluttering the application source code repository.
2. **Cloudflare R2 for Binary Databases & Media**: Pre-computed QMD indices (`.qmd.db`, vector caches, SQLite databases) and heavy binary attachments are synced to Cloudflare R2 object storage (S3-compatible API with zero egress fees).
3. **Three-Tier Operational Modes**:
   - `offline-only`: Strictly local execution; no network requests or external credentials required.
   - `offline+cloudflare-wiki`: Corpus remains strictly local; only rendered public/tokenized wiki synthesis pages deploy to Cloudflare Pages mirror.
   - `full`: Complete bidirectional sync enabled across Artifacts, R2, and Edge Mirror.

## Consequences
- The knowledgebase software repository remains lightweight, distributable, and free of private user data.
- Users enjoy zero egress fees and generous free-tier storage on Cloudflare.
- Ephemeral cloud workers (Modal/E2B) can hydrate an isolated microVM in seconds by pulling snapshots from R2/Artifacts.
