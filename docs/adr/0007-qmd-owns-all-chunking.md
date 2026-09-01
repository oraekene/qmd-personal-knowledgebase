# 0007-qmd-owns-all-chunking.md

# QMD owns all chunking; connectors write whole Units

Connectors and normalizers write one Unit per logical item regardless of
size and do no chunking or splitting. All chunking happens inside QMD at
embed time (900-token chunks, 15% overlap), which preserves session-level
context on every chunk hit and keeps the normalizers purely mechanical.
Connector-side pre-splitting (porting the NotebookLM-era combine/split
logic) was considered and rejected as redundant with QMD's chunker and
fragmenting to the logical unit. Very large Units are paged locally via
QMD's ranged get, and served to web chats through the wiki synthesis
layer rather than raw fetches.