# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/); retrieval-quality changes are noted with their bench numbers.

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
