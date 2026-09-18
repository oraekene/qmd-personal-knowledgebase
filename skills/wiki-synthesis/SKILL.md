---
name: wiki-synthesis
description: Synthesize disparate documents across silos into structured wiki topic notes and concept indexes.
metadata:
  target_silo: wiki
---

# Wiki Synthesis Protocol

Use this skill to discover cross-silo connections and update compiled conceptual summaries.

## Workflow
1. **Discover Hub Topics**:
   - Query `corpus/wiki/` to see existing concept pages.
2. **Synthesize Missing Links**:
   - Identify shared themes across notes, GitHub codebases, and web research.
3. **Execute Synthesis**:
   - Trigger the wiki compiler via `tool_call(tool_name="compile_wiki", arguments={"max_items": 10})` or use Workers AI free tier synthesis.
4. **Link Integrity**:
   - Verify all `[[wikilinks]]` resolve properly to files within `corpus/wiki/`.
