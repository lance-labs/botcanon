---
name: second-brain-retrieve
description: Use when answering from the second brain or assembling context for a task.
---
# Retrieve from the second brain

1. `python3 tools/brain.py search "<question>"`. Hybrid search is the default; use `--mode lexical` for exact names or codes.
2. For anything with history (hours, prices, owners), run `python3 tools/brain.py compile <entity>`. Trust CURRENT. OUTRANKED and SUPERSEDED are history, not answers.
3. Cite the note path for every claim. If nothing relevant comes back, say the vault has no answer. Never fill the gap from chat memory.
4. If `verify` reports RED, say the index is stale before answering, or run `flush`.
