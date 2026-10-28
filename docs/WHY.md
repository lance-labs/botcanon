# Why this second brain looks the way it does

Most "memory for agents" projects begin with storage: a vector database, a graph, a summarizer that runs every night. This one begins with a different question: when an agent tells you something from memory, how would you know it is true, current, and still the rule? Every design choice here follows from wanting a good answer to that question.

## Plain files are the record; the index can be thrown away

Notes are Markdown in a git repository. You can read them without any tool, diff them, review them, and revert them. The SQLite index (full-text plus embeddings) is derived from the notes and can be rebuilt at any time: delete `.index/` and run `ingest`. So the index can be wrong, but it can never be the only copy of anything. Bugs in retrieval cost you a reindex, not your history.

## Chat memory proposes; one curator asserts

Agents are good at noticing facts and bad at deciding which facts should be permanent. An agent that writes straight into long-term memory turns every mistake, rumor, and prompt injection into "something I remember." Here, anything can propose (`propose`, or a file in `inbox/`), and only one curator promotes proposals into canon. Each canon fact carries where it came from (`From:`, `Source:`, `Date:`), and `why` will show you. Read access is wide and write access is narrow, the same split we use for production systems.

## Authority is explicit, and it breaks ties rather than overriding relevance

A decision should beat an offhand note when the two disagree. That's encoded twice:
- Search weights decisions slightly above other notes and pushes replaced decisions to the bottom.
- `compile` sorts an entity's claims into CURRENT, OUTRANKED, and SUPERSEDED, so the answer and its history are both visible and never blended.

The search weights are deliberately small. A first version let authority override relevance, and a decision that was only loosely related beat the note that actually answered the question. Authority is the tie-breaker, not the judge.

## Saying "I don't know" is a feature

A retriever that always returns its top five will always produce an answer, which means that sometimes it will confidently answer from nothing. `answer` requires an actual lexical match or a semantic match above a floor, and otherwise says so. The benchmark counts no-answer questions separately for this reason: in the README table, plain embeddings score zero there by construction.

## Staleness has to be loud

The worst failure of a memory system is quiet staleness: the index stops updating and nobody notices for weeks. Freshness is part of `verify`:
- RED: a note is newer than the index, or a proposal has waited more than 48 hours.
- YELLOW: a decision is past its revisit date.

`flush` runs on every write batch and refuses to commit on RED, so freshness never depends on a scheduled job staying alive.

## Tests are the contract, and the curator does not grade itself

Every promoted fact should come with a golden question that would fail if the fact got lost. A recall floor stops slow decay. The curator writes those goldens, though, so they share its blind spots. A separate eval agent keeps a hidden question set and runs it on a schedule. That is the only number in the system the curator can't game, even by accident.

## Small on purpose

One Python file, SQLite, and a local embedding model. There is no server to keep running, no API key, and no graph database to fix. When the vault outgrows that, the files are still just files, and you can move them to something bigger. Don't add the bigger thing until a failing test asks for it.
