#!/usr/bin/env bash
# Two-minute tour on a throwaway copy of the sample vault. Your checkout is never modified.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cp -r "$here"/{GOALS.md,CURRENT.md,decisions,people,projects,log,inbox,tools,evals} "$tmp"/
export BRAIN_VAULT="$tmp"
b() { python3 "$tmp/tools/brain.py" "$@" 2>/dev/null; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; sleep "${DEMO_PAUSE:-6}"; }

step "1. Load the sample notes (chunk, embed, index)"
b ingest
step "2. Hybrid search"
b search "who supplies our flour"
step "3. A cited answer, and an honest I-don't-know"
b answer "how much can we spend on the new oven" || true
b answer "what is our cryptocurrency strategy" || true
step "4. Provenance: where did the opening-hours rule come from?"
b why "opening hours" | head -14
step "5. A decision outranks an older log note"
b compile opening-hours
step "6. Edit a note without reindexing: freshness turns RED"
sleep 1; echo "- Also bakes rye on Fridays." >> "$tmp/people/ari-novak.md"
b verify | grep -E '^(freshness|verify):' || true
step "7. Reindex (only the changed note): GREEN again"
b ingest
b verify | grep -E '^(passed|recall|freshness|verify):'
step "8. Agents propose; they never write canon"
b propose "Rye flour arrives Fridays." --from-agent demo-agent --source "demo.sh"
ls "$tmp/inbox"
echo; echo "Done. Nothing in $here was changed."
