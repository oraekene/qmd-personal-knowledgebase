# 0002-query-faces-qmd-native-plus-static-mirror.md

# Query faces are QMD-native plus a static mirror

We build zero bespoke chat-platform plugins. Access is QMD's native
CLI/MCP/HTTP (MCP tunneled to Claude.ai web via Cloudflare Tunnel with an
auth proxy), plus a full static mirror of the corpus on Cloudflare Pages
with llms.txt. Bespoke plugins are N builds chasing moving targets; the
mirror is the lowest-common-denominator face every web chat's fetch tool
can already reach.