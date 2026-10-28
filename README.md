# second-brain-starter

A small, file-first second brain for people and AI agents. Your notes are plain Markdown in git. A SQLite index (FTS5 plus local embeddings) makes them searchable, and a test suite tells you when retrieval or freshness breaks.

The sample vault describes Juniper Bakery, a fictional business. Replace it with your own notes.

## Quickstart

```sh
git clone <this repo> my-brain && cd my-brain
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # fastembed downloads BAAI/bge-small-en-v1.5 on first use
tools/install-hooks.sh                   # needs gitleaks on PATH
python3 tools/brain.py ingest
python3 tools/brain.py verify            # expect: verify: GREEN
python3 tools/brain.py search "who supplies our flour"
python3 tools/brain.py compile opening-hours
```

After you edit notes, run `python3 tools/brain.py flush -m "what changed"`. It re-ingests only changed files, runs verify, refuses to commit on RED, then commits and pushes. If nothing changed, it does nothing.

## Layout

| Path | What lives there |
|---|---|
| `decisions/` | One file per decision: `- Date:`, `- Owner:`, `- Decision:`, optional `- Prior:`, `- Revisit:` |
| `people/`, `projects/` | One note per person or project |
| `GOALS.md` | Goals and house rules |
| `CURRENT.md` | Derived dashboard; it ranks below its sources |
| `log/*.jsonl` | Append-only claims (`id`, `ts`, `entity`, `text`, `successor`). Read by compile, never searched |
| `inbox/` | Proposals waiting for the curator. Never searched |
| `skills/` | Agent instructions for promoting and retrieving |
| `tools/` | `brain.py`, goldens, hooks |

## Design

- **Search:** hybrid. FTS5 with BM25 and porter stemming, cosine similarity on bge-small embeddings, and a title-match list, fused with reciprocal rank fusion. Stopwords are dropped, and a full-sentence question falls back to an OR query when the strict AND query finds nothing. At most 2 hits per note. Semantic hits below a similarity floor are dropped, so a question with no answer comes back empty.
- **Authority:** decisions and GOALS win ties (+2%) over people and projects. A decision named on a newer decision's `- Prior:` line sinks to 0.1. The weights break ties; they do not override relevance.
- **Compile:** for an entity, CURRENT is the newest non-superseded decision plus log claims dated after it. Older claims move to OUTRANKED, and claims with a `successor` move to SUPERSEDED.
- **Freshness:**
  - RED: a note is newer than the index, or an inbox item is older than 48 hours.
  - YELLOW: a decision is past its `Revisit: ~YYYY-MM-DD` date.
  - `Revisit: standing (no review date)` never comes due.
- **Verify:** runs every golden (expected path within a rank, rejected paths, no-answer cases) and enforces a recall@5 floor. It also runs the authority and freshness fixtures and checks that the git hooks are installed.
- **Ingest:** incremental by sha256. A schema or embedding-model change triggers a full rebuild.

## Why it works this way

- **Files over a database.** Markdown in git is readable, diffable, and survives any tool. The index can always be deleted and rebuilt.
- **Chat memory is not a record.** Agents propose through `inbox/`, and one curator writes canon. "I remembered" is never a source.
- **Tests, not hope.** Each promotion adds a golden. Retrieval that quietly gets worse fails verify instead of misleading you later.
- **No clock.** flush runs on every write batch, so freshness doesn't depend on a scheduled job staying alive.
- **Small on purpose.** One file of Python, SQLite, and a local model. There is no server, graph database, or API key.

## License
MIT
