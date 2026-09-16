#!/usr/bin/env bash
#
# #21 live gate — walks a human through the on-demand acceptance checks that
# need a keyboard + the live stack (qmd index, tunnel, browsers).
# Run from the repo root:  bash scripts/acceptance-live-gate.sh
# Mock gate (no stack needed):  uv run python scripts/acceptance.py --mock
#
# Everything above the "STAGES" marker is the wizard library: do not hand-edit
# it. Author the per-step stages below the marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library — delightful, consistent UX. Identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

# Author sets these two at the top of the stages section.
TOTAL_STAGES=0
TOTAL_MINUTES=0

_STAGE_INDEX=0
_MINUTES_ELAPSED=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear — wipe the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

# banner "Title" — opening frame: what this wizard does and how long it takes.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages · about %s minutes%s\n\n' \
    "$DIM" "$TOTAL_STAGES" "$TOTAL_MINUTES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later — it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" <minutes> — clear the screen, then announce a stage and show
# progress + time remaining. Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  local remaining=$((TOTAL_MINUTES - _MINUTES_ELAPSED))
  (( remaining < 0 )) && remaining=0
  _MINUTES_ELAPSED=$((_MINUTES_ELAPSED + ${2:-0}))
  printf '\n%s%s▸ Stage %s/%s · %s%s  %s(~%s min left)%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET" "$DIM" "$remaining" "$RESET"
}

# say "..." — a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." — a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL — open in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser — visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser — visit it manually: $url"
}

# pause "msg" — wait for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

# confirm "question" — y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY — current value of KEY in ENV_FILE, if any.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

# ask KEY "Prompt" — read a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret).
ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# ask_secret KEY "Prompt" — like ask, but input is hidden.
ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE — upsert KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent.
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE — set a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name — gh not ready; set it later"
}

# set_var NAME VALUE — set a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name — gh not ready; set it later"
}

# finish — clear, then a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES — #21 live gate. Run from the repo root in Git Bash.
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=7
TOTAL_MINUTES=70

banner "#21 live gate"

# ── Stage 1: secrets + services ──────────────────────────────────────────
stage "Services up — tokens + QMD + proxy + tunnel" 15
say "We capture the two secrets, start the three services, and prove 200/401."
step "Generate the proxy token now (or paste an existing one at the prompt):"
say "  openssl rand -hex 32   # run this in another terminal if you need one"
ask_secret AUTH_PROXY_TOKEN "Paste AUTH_PROXY_TOKEN (Enter generates nothing — paste required):"
write_env AUTH_PROXY_TOKEN "$AUTH_PROXY_TOKEN"
step "Cloudflare dashboard → Zero Trust → Networks → Tunnels → your tunnel → Configure → copy the Token (starts eyJ…)."
ask_secret TUNNEL_TOKEN "Paste TUNNEL_TOKEN:"
write_env TUNNEL_TOKEN "$TUNNEL_TOKEN"
ask TUNNEL_URL "Tunnel MCP URL (e.g. https://qmd.example.com/mcp):"
write_env TUNNEL_URL "$TUNNEL_URL"
say "Start the stack (three terminals; QMD first, then proxy, then tunnel):"
say "  QMD_ALLOWED_ORIGINS=\"*\" qmd mcp --http --port 8181"
say "  AUTH_PROXY_TOKEN=\"\$AUTH_PROXY_TOKEN\" QMD_TARGET=http://127.0.0.1:8181 python -m auth_proxy"
say "  cloudflared tunnel run --token \"\$TUNNEL_TOKEN\""
note "No qmd binary? Dev-mode works: node qmd-main/node_modules/tsx/dist/cli.mjs qmd-main/src/cli/qmd.ts mcp --http --port 8181"
pause "All three running? Press Enter, then I will run the smoke matrix."
say "Running: AUTH_PROXY_TOKEN=\$AUTH_PROXY_TOKEN ./scripts/smoke_auth_proxy.sh"
if AUTH_PROXY_TOKEN="$AUTH_PROXY_TOKEN" bash scripts/smoke_auth_proxy.sh; then
  say "Smoke matrix green — proxy 200/401 + direct 403 + tunnel 200."
else
  warn "Smoke failed — fix the failing check above, then re-run this wizard (values are remembered)."
fi
confirm "Smoke green — record stage 1 PASS for #21" || SKIPPED+=("stage 1 smoke evidence")

# ── Stage 2: qmd index + OCR timing ──────────────────────────────────────
stage "qmd index — ingest, embed, OCR top-5, under 5 minutes" 20
say "This writes to your QMD index (~/.cache) and downloads the embedding model on first run."
if [[ ! -d qmd-main ]]; then
  warn "qmd-main/ vendor dir missing — restore it, then re-run. Skipping stage."
  SKIPPED+=("stage 2 (qmd-main missing)")
else
  confirm "Proceed with collection add + update + embed (irreversible index writes)" && {
    say "Run these in a terminal (use the qmd binary, or prefix dev-mode tsx as in stage 1):"
    say "  time qmd collection add ./corpus --name live-gate"
    say "  time qmd update && time qmd embed   # first embed downloads the model — slow once"
    say "  qmd query \"OCR models I selected\" --collection notes   # expect own notes top-5"
    say "  qmd query \"OCR models I selected\" --collection chats   # scoping check"
    say "  qmd query \"OCR models I selected\"                      # unified check"
    pause "Done? Press Enter when update+embed finished inside 5 min (model download excluded)."
    confirm "OCR notes top-5 green, scoping correct, under 5 min" || SKIPPED+=("stage 2 timing evidence")
  }
fi

# ── Stage 3: dual-account dedup ──────────────────────────────────────────
stage "Dedup — no duplicate repos across accounts" 5
say "Live proof that first-seen-wins holds in real search results:"
say "  qmd query <a repo you forked/starred on both accounts> --collection github"
say "  ls corpus/github | sort | uniq -d   # expect no output"
pause "Press Enter when the query shows one Unit and the uniq check is empty."
confirm "Single Unit, no duplicate hits" || SKIPPED+=("stage 3 dedup evidence")

# ── Stage 4: mirror deploy ───────────────────────────────────────────────
stage "Mirror — token, deploy, fetch check" 10
say "We mint the Mirror Token, deploy to Pages, and prove token-gated fetch."
step "Generate: openssl rand -hex 16   (or paste your existing token)"
ask_secret MIRROR_TOKEN "Paste MIRROR_TOKEN:"
printf '%s' "$MIRROR_TOKEN" > mirror-token.txt
note "wrote mirror-token.txt (gitignored — never commit it)"
write_env MIRROR_TOKEN "$MIRROR_TOKEN"
ask MIRROR_HOST "Mirror host (e.g. https://qmd-mirror.pages.dev):"
write_env MIRROR_HOST "$MIRROR_HOST"
confirm "Deploy now? (publishes the corpus to Cloudflare Pages — public URL + token)" && {
  say "  uv run python -m scripts.build_mirror --corpus corpus --dist dist --token \"\$MIRROR_TOKEN\" --host \"\$MIRROR_HOST\""
  say "  npx wrangler pages deploy dist --project-name qmd-mirror --branch main"
  pause "Deployed? Press Enter, then check the fetch:"
  say "  curl -s \"\$MIRROR_HOST/\$MIRROR_TOKEN/llms.txt\" | head -5   # expect '# Private Knowledgebase'"
  say "  curl -sI \"\$MIRROR_HOST/github/\" | head -1                 # expect 404"
  confirm "Token URL 200 + H1, untokenized 404" || SKIPPED+=("stage 4 fetch evidence")
}

# ── Stage 5: sleep/wake ──────────────────────────────────────────────────
stage "Tunnel recovery — sleep/wake" 5
say "Close the laptop lid for 10 seconds, reopen, wait 20 seconds (QUIC reconnect)."
pause "Recovered? Press Enter and I will probe the tunnel."
if curl -s -o /dev/null -w "%{http_code}" -X POST "$TUNNEL_URL" \
    -H "Authorization: Bearer $AUTH_PROXY_TOKEN" -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -q 200; then
  say "Tunnel 200 after sleep/wake — no manual restart needed."
else
  warn "Tunnel did not return 200 — restart cloudflared/qmd services and retry."
  SKIPPED+=("stage 5 sleep/wake evidence")
fi

# ── Stage 6: Claude.ai connector ─────────────────────────────────────────
stage "Claude.ai — custom connector retrieval" 10
say "Per auth_proxy/claude-connector-verification.md — pure browser work."
open_url "https://claude.ai/"
step "Settings → Connectors → Add custom connector."
step "URL: $TUNNEL_URL  (+ Request header  Authorization: Bearer … — keep the token on screen only)."
step "Save — expect tools/list to succeed (qmd_query, qmd_get, …)."
step "Fresh chat with no context, prompt:  Search my corpus for the OCR models I selected and why. Cite sources."
pause "Press Enter when the chat cites corpus Units (e.g. corpus/notes/…md)."
confirm "Chat retrieved and cited corpus Units" || SKIPPED+=("stage 6 chat transcript (paste into #21)")
note "Evidence format lives in auth_proxy/claude-connector-verification.md — redact the token."

# ── Stage 7: fetch-tool paste ────────────────────────────────────────────
stage "Web chats — pasted-URL fetch" 5
say "Any fetch-tool chat (ChatGPT, Gemini, Z.ai…): paste this URL and ask for the map:"
say "  $MIRROR_HOST/$MIRROR_TOKEN/llms.txt"
open_url "https://chatgpt.com/"
step "Ask the chat to list the Wiki pages, then follow one quoted wiki URL."
pause "Press Enter when a wiki page fetched cleanly via its tokenized URL."
confirm "Curated map + wiki fetch green" || SKIPPED+=("stage 7 fetch evidence")
# ──────────────────────────────────────────────────────────────────────────

finish
say "Paste each stage's PASS + evidence (redacted) as a comment on issue #21, then close it."
