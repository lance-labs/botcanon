# Changelog

BotCanon (repo slug `botcanon`; formerly second-brain-starter).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/); retrieval-quality changes are noted with their bench numbers.

## [Unreleased]
### Fixed
- `flush` no longer pushes by default (BC-06). `--push` pushes, and is refused when `gh repo view` reports the repo PUBLIC unless `--allow-public` is given; when visibility can't be read it says so. `--no-push` is kept as a no-op for old scripts. Tested with a fake `gh` in `test_flush.py`.
- `flush` stages only memory paths (canon notes and folders, `log/`, `inbox/`, the reviewed tests file) instead of `git add -A`, and lists any other changed files it left alone (BC-02). The curator paste block and the promote skill now say inbox items, notes and quotes are data, never instructions. New `tools/test_flush.py` in CI.
- CI now checks the answers bots get, not only search ranks (BC-05): 8 answer-level fixture tests (5 must quote an exact `path:line` via the new `expect_cite`, 3 must say "I don't know", one of them an owner attribute).
- Cite-and-verify no longer fails open (BC-01). A question with no rare words used to leave an empty term list, so every line "covered" it and `answer` could quote `- Date: 2026-03-01` as verified. It now falls back to all content words, an empty list verifies nothing, metadata lines (Date, Owner, From, Source, Prior, Revisit) are never quoted, and the note title counts as context for its lines. The coverage bar is exactly 2/3 (was 0.67, which rounded 2-of-3 matches down to a fail), "much"/"many" are stopwords, and "supplies"/"supplier" share a stem. New `tools/test_cite.py` in CI.
### Docs
- CI descriptions list every step (test builder, incremental re-index, empty vault) and the real triggers; Known limits states verify's cost (~0.5 s per test).
### Changed
- `status` (and `flush`) write `status.json` into the store's `.index/`, not the engine's `tools/` folder, so `--root` never writes one store's stats into another checkout.
### Added
- `evals init --owner "<name>"` (or `BRAIN_OWNER`) proposes up to 8 "I don't know" tests about the owner (favorite color, blood type, dentist, ...), skipping any topic the notes mention. This is the weak spot in Known limits.
- verify names a legacy `tools/retrieval_tests.yaml` and suggests moving it to `evals/`.
- `tools/test_incremental.py` (in CI): after an edit, a delete and forced re-indexing of unchanged notes, an incremental index returns the same top-10 as a full rebuild for every fixture query in lexical, semantic and hybrid mode.
- `expect_path` accepts a list; the test passes when any listed note is within `max_rank` (older test files use this).
### Fixed (test builder, from a run on a real vault: 31 of 81 proposals were usable)
- `evals accept` refuses tests not marked `reviewed: true` (or `--all-reviewed`) and any `REWRITE:` placeholder query; exits 1 when it refuses.
- `evals init` no longer builds "Title: word word word" queries from the answer line. Field lines get a template question (Why, Last contact, Role, ...); other lines get a `REWRITE:` placeholder. Titles lose dates and parentheticals; commentary fields and lines near-identical to a line in another note are skipped.
- `evals init` skips superseded notes and the derived `CURRENT.md`.
- verify goes RED (exit 1) on a tests file with 0 tests or an unknown top-level key; legacy `cases:` is read as `goldens:`. `evals accept` appends to `cases:` when that is the file's key.
- `evals/proposed_tests.yaml` is gitignored and `flush` unstages it. Tests carry `source: path:line`; copying the line (`quote:`) is opt-in with `evals init --quotes`.
### Changed
- The user vault starts empty (folder skeleton + `GOALS.md` stub). The fictional sample notes moved, unchanged, to `tests/fixtures/vault/` (TEST FIXTURE: CI, bench, test_mcp, demo only). Bench numbers unchanged.
- verify with no tests prints "no evals yet; run evals init" and returns YELLOW (exit 0).
- `--root` now reaches cite/evals helpers too (one `brain` module when run as a script).
### Added
- `brain.py evals init` (extractive, offline: question + expected note + quoted line per fact-like line, plus off-topic "I don't know" questions, to `evals/proposed_tests.yaml`) and `evals accept` (merge into `evals/retrieval_tests.yaml`).
- Goldens with `expect_known: true|false` (answer-level checks). `tools/test_evals.py` in CI.

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
