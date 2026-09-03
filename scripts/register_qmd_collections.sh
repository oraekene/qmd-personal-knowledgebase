#!/usr/bin/env bash
# Register QMD collections (silos 1:1) including wiki — for #20
# Per spec.md:82-86 + qmd.index.yml.example. Requires `qmd` binary.
# Usage: ./scripts/register_qmd_collections.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

add() {
  local name=$1 path=$2
  if [ -d "$path" ]; then
    echo "→ qmd collection add $path --name $name"
    qmd collection add "$path" --name "$name" || echo "  (warn: add $name failed, continuing)"
  else
    echo "  (skip $name: $path missing — will be indexed once created)"
    # Still register via config? qmd requires path to exist, so document instead
    echo "  To register later: qmd collection add $path --name $name"
  fi
}

add github corpus/github
add chats corpus/chats
add twitter corpus/twitter
add notes corpus/notes
add pdfs corpus/pdfs
add web corpus/web
add wiki corpus/wiki

echo "Done. Verify: qmd ls && qmd query --collection wiki \"nebula\""
echo "Or copy qmd.index.yml.example to ~/.config/qmd/index.yml / .qmd/index.yml"
