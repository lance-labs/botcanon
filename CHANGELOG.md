# Changelog

BotCanon (repo slug `botcanon`; formerly second-brain-starter).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/); retrieval-quality changes are noted with their bench numbers.

## [0.6.0] - 2026-10-28
### Changed
- Project renamed to BotCanon (decided 2026-10-28). README v2: plain-to-technical order, bot-memory positioning, honest usage estimate; internals moved to `docs/`.

## [0.5.1] - 2026-10-28
### Fixed
- Score ties now break on note path, then position in the note, never on insert order, so re-indexing one note can't reshuffle tied results. (The author's vault had a worse version of this: a contentless FTS5 table never subtracted deleted rows from BM25 stats, so 13/97 goldens ranked differently after an incremental reindex. The starter's FTS5 table stores content, so its deletes were already exact.)

## [0.5.0] - 2026-10-28
### Added
- Cite-and-verify (`tools/cite.py`): `answer` returns `path:line "quote"` verified in the file, and says I don't know unless the line states the asked attribute. `answer --spans` prints verified candidate lines. MCP `answer` uses it.
- README "Agent rules" (4 rules, each tied to measured results) and `templates/HANDOFF.md`.
- Measured in the author's vault (held-out, never tuned on): made-up answers 22/22 with the score gate alone, 1/22 code-only, 0/22 with an agent following rule 2. False I don't know: 0/10, 5/10, 1/10.

## [0.4.1] - 2026-10-28
### Changed
- README known limits: the "I don't know" gate is NOT reliable for questions about the owner's personal attributes. Measured in the author's vault at -9.4: 5/6 calibration questions and 22/22 held-out "owner + attribute" questions got made-up answers. Callers must check the citation.

## [0.4.0] - 2026-10-28
### Added
- README "How it works": data-flow diagram, storage (Markdown / SQLite / JSONL) with reasons, lexical + semantic search, RRF, rerank, the "I don't know" gate, the weights table from `path_weight`, freshness/flush/verify/CI, and known limits.
- Explicit `status: proposed|approved|superseded` on notes. Ranking reads it (folder and `Prior:` fallback); `verify` checks it (`status_check` + fixture). `tools/note_status.py`, `tools/migrate_status.py`. `propose` writes `status: proposed`.
### Changed
- Index schema version 2: the status line is no longer indexed (forces one full rebuild).
### Known limits
- The "I don't know" gate can be fooled by "<owner name> + generic word" questions (measured 5/6 in the author's vault). Gate redesign is tracked separately.

## [0.3.0] - 2026-10-28
### Added
- Second-pass cross-encoder reranker (`Xenova/ms-marco-MiniLM-L-6-v2`) over the top 20 hybrid hits, blended with the hybrid rank by RRF. On by default; `BRAIN_RERANK=0` turns it off.
- `answer` uses the reranker score for "I don't know" (floor -9.4).
- Bench rows with and without the reranker. Public set: Hit@1 0.75 to 0.79, MRR 0.84 to 0.86. With the gate: no-answer correct 0.67 to 1.00, Hit@5 0.93 to 0.89.
### Changed
- Search latency rises from tens of ms to ~0.5 s per query (CPU).

## [0.2.0] - 2026-10-28
### Added
- "The problem" section at the top of the README.
- 10 paraphrase questions in `evals/public_set.yaml` (indirect, plain English). Bench: hybrid Hit@1 0.75 / MRR 0.84 vs lexical 0.68 / 0.73.
- GitHub Actions CI workflow at `ci/github-actions.yml` (copy into `.github/workflows/` to enable): gitleaks history scan, hooks, ingest, verify, MCP end-to-end, and a check that the README bench table matches the code.
- This changelog and version tags.

## [0.1.0] - 2026-10-28
### Added
- Bench vs a plain-embedding baseline (`tools/bench.py`, `evals/public_set.yaml`).
- Provenance (From/Source, log `from_agent`/`source`) and `why`.
- `answer` that says "I don't know" (exit 2); `propose` to `inbox/` only.
- MCP server (`tools/mcp_server.py`) with an end-to-end test; `demo.sh`; `docs/WHY.md`.
- Extending the boundary (`--root/--dirs/--tests`, `examples/novel`), independent eval agent and hidden-set template, fail-closed hooks.
- Initial kit: Markdown + git vault, SQLite FTS5 + local embeddings, goldens, freshness checks, flush.
