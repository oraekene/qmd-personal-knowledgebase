"""Apply CPU latency and search optimizations to local qmd-main distribution.

Optimizations:
1. buildFTS5Query: supports 'AND' and 'OR' operators.
2. searchFTS: falls back to OR ranking with BM25 when AND returns 0 matches for conversational queries.
3. hybridQuery: skips slow CPU LLM query expansion and embedding when skipRerank is true.
4. MCP server: registers fast 'search' tool (BM25 <50ms) and sets rerank default to false.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QMD_DIR = REPO_ROOT / "qmd-main"

def patch_store():
    store_file = QMD_DIR / "src" / "store.ts"
    if not store_file.exists():
        print(f"[SKIP] {store_file} not found")
        return

    content = store_file.read_text(encoding="utf-8")
    modified = False

    # 1. buildFTS5Query operator
    if "function buildFTS5Query(query: string): string | null {" in content:
        content = content.replace(
            "function buildFTS5Query(query: string): string | null {",
            "function buildFTS5Query(query: string, operator: 'AND' | 'OR' = 'AND'): string | null {"
        )
        content = content.replace(
            "let result = positive.join(' AND ');",
            "let result = positive.join(` ${operator} `);"
        )
        modified = True

    # 2. searchFTS OR fallback
    target_search_fts = "let rows = db.prepare(sql).all(...params) as { filepath: string; display_path: string; title: string; body: string; hash: string; bm25_score: number; metadata_json: string | null }[];"
    if "const rows = db.prepare(sql).all(...params)" in content:
        old_str = "  const rows = db.prepare(sql).all(...params) as { filepath: string; display_path: string; title: string; body: string; hash: string; bm25_score: number; metadata_json: string | null }[];\n  return rows.map(row => {"
        new_str = """  let rows = db.prepare(sql).all(...params) as { filepath: string; display_path: string; title: string; body: string; hash: string; bm25_score: number; metadata_json: string | null }[];

  // If AND search returned 0 results and query has multiple terms, fall back to OR ranking (in cpu-only mode)
  const isCpuOnly = (process.env.QMD_RETRIEVAL_MODE ?? process.env.RETRIEVAL_MODE ?? 'cpu-only').toLowerCase() === 'cpu-only';
  if (isCpuOnly && rows.length === 0 && ftsQuery.includes(' AND ')) {
    const orQuery = buildFTS5Query(query, 'OR');
    if (orQuery) {
      const orParams = [orQuery, ...params.slice(1)];
      rows = db.prepare(sql).all(...orParams) as { filepath: string; display_path: string; title: string; body: string; hash: string; bm25_score: number; metadata_json: string | null }[];
    }
  }

  return rows.map(row => {"""
        content = content.replace(old_str, new_str)
        modified = True

    # 3. hybridQuery skip expansion & vector embedding on skipRerank (in cpu-only mode)
    if "const expanded = hasStrongSignal\n    ? []\n    : await store.expandQuery(query);" in content:
        content = content.replace(
            "const expanded = hasStrongSignal\n    ? []\n    : await store.expandQuery(query);",
            "const isCpuOnly = (process.env.QMD_RETRIEVAL_MODE ?? process.env.RETRIEVAL_MODE ?? 'cpu-only').toLowerCase() === 'cpu-only';\n  const expanded = (hasStrongSignal || (skipRerank && isCpuOnly))\n    ? []\n    : await store.expandQuery(query);"
        )
        modified = True

    if "if (hasVectors) {\n    const vecQueries" in content:
        content = content.replace(
            "if (hasVectors) {\n    const vecQueries",
            "if (hasVectors && !(skipRerank && isCpuOnly)) {\n    const vecQueries"
        )
        modified = True

    if modified:
        store_file.write_text(content, encoding="utf-8")
        print(f"[OK] Patched {store_file}")
    else:
        print(f"[NO-OP] {store_file} already has optimizations")


def patch_mcp_server():
    server_file = QMD_DIR / "src" / "mcp" / "server.ts"
    if not server_file.exists():
        print(f"[SKIP] {server_file} not found")
        return

    content = server_file.read_text(encoding="utf-8")
    modified = False

    # 1. rerank default false
    if "rerank: z.boolean().optional().default(true).describe(" in content:
        content = content.replace(
            'rerank: z.boolean().optional().default(true).describe(\n          "Rerank results using LLM (default: true). Set to false for faster results on CPU-only machines."',
            'rerank: z.boolean().optional().default(false).describe(\n          "Rerank results using LLM (default: false for sub-second responses). Set to false for fastest results on CPU; set to true only when GPU acceleration is available."'
        )
        modified = True

    # 2. search tool registration
    if 'server.registerTool(\n    "search"' not in content:
        target = '  // ---------------------------------------------------------------------------\n  // Tool: qmd_get (Retrieve document)\n  // ---------------------------------------------------------------------------'
        search_tool_code = """  // ---------------------------------------------------------------------------
  // Tool: search (Fast keyword/BM25 search)
  // ---------------------------------------------------------------------------

  server.registerTool(
    "search",
    {
      title: "Search Knowledgebase",
      description: "Fast keyword & BM25 search across documents. Returns immediately (<50ms). Best for looking up notes, concepts, and topics by keyword or natural phrase.",
      annotations: { readOnlyHint: true, openWorldHint: false },
      inputSchema: z.object({
        query: z.string().describe("Keywords or question to search for (e.g. 'OCR models', 'authentication', 'Simplenote')"),
        collections: z.array(z.string()).optional().describe("Filter to collections (OR match)"),
        limit: z.number().optional().default(10).describe("Max results (default: 10)"),
      }),
    },
    track(async ({ query, collections, limit }) => {
      const effectiveCollections = collections ?? defaultCollectionNames;
      const results = await store.searchLex(query, {
        collection: effectiveCollections.length > 0 ? effectiveCollections : undefined,
        limit: limit ?? 10,
      });

      const filtered: SearchResultItem[] = results.map(r => {
        const { line, snippet } = extractSnippet(r.body, query, 300);
        return {
          docid: `#${r.docid}`,
          file: r.displayPath,
          title: r.title,
          score: Math.round(r.score * 100) / 100,
          context: r.context,
          line,
          snippet: addLineNumbers(snippet, line),
        };
      });

      return {
        content: [{ type: "text", text: formatSearchSummary(filtered, query) }],
        structuredContent: { results: filtered },
      };
    })
  );

  // ---------------------------------------------------------------------------
  // Tool: qmd_get (Retrieve document)
  // ---------------------------------------------------------------------------"""
        if target in content:
            content = content.replace(target, search_tool_code)
            modified = True

    if modified:
        server_file.write_text(content, encoding="utf-8")
        print(f"[OK] Patched {server_file}")
    else:
        print(f"[NO-OP] {server_file} already has optimizations")


if __name__ == "__main__":
    patch_store()
    patch_mcp_server()
