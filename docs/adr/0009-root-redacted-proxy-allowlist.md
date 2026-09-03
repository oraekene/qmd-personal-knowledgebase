# 0009 — Root map redacted + proxy enforces origin allowlist

Root `dist/llms.txt` is a redacted pointer (counts only) and never contains the
Mirror Token; the full tokenized map lives only under `dist/<token>/llms.txt`.
Rationale: root is served unauthenticated, so tokenized URLs there leak the
secret and defeat rotation (ADR-0003). Amends the mirror builder without
changing token format or deploy targets.

The Auth Proxy enforces `QMD_ALLOWED_ORIGINS` (comma-separated, default `*`
passthrough) with 403 on spoofed `Origin` when configured (e.g.
`https://claude.ai`). Rationale: `spec.md:25` + `spec.md:129-130` require
rejection + allowlisting; deferring solely to QMD left the tunneled path
unenforced. Default `*` preserves prior passthrough; setting the env closes it.
Reopens ADR-0002 passthrough narrowly, by documented env knob only.
