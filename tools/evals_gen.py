"""`brain.py evals init|accept`: build retrieval tests from the user's own notes. Extractive, offline, no API.

init  reads every canon note, picks its most fact-like lines, and writes evals/proposed_tests.yaml:
      one question per line (expected note + the quoted line it should come from), plus a few
      off-topic "I don't know" questions. Nothing is trusted until you review it.
accept merges the reviewed file into the store's retrieval tests and removes the proposal.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import brain

META_KEYS = {"status", "date", "owner", "from", "source", "prior", "revisit", "updated", "id", "tags"}
STUB_MARK = "<!-- botcanon:stub -->"
KV_RE = re.compile(r"^[-*]\s*\**([A-Za-z][A-Za-z /&-]{1,30}?)\**\s*:\s*(.+)$")
IDK_QUESTIONS = [  # off-topic for any bot vault; cite-and-verify must say "I don't know"
    "what is the capital of Peru",
    "what is the boiling point of tungsten",
    "who won the 1998 World Cup",
]


def _words(text: str) -> list[str]:
    return [w for w in brain.TOKEN_RE.findall(text.lower()) if w not in brain.STOPWORDS and len(w) > 2]


def _candidates(text: str) -> list[tuple[float, int, str, str | None]]:
    """(score, line_no, line, key) for fact-like lines; more specific lines score higher."""
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "<!--", "```", "|")):
            continue
        if re.search(r"\(see [^)]+\)", line):  # a pointer: the fact lives in the linked note, not here
            continue
        m = KV_RE.match(line)
        key = m.group(1).strip() if m else None
        if key and key.lower() in META_KEYS:
            continue
        words = _words(m.group(2) if m else line)
        if len(words) < 3:
            continue
        specific = sum(any(c.isdigit() for c in w) for w in words) + sum(t[:1].isupper() for t in line.split()[1:])
        out.append((len(set(words)) + 2 * specific, n, line, key))
    return sorted(out, key=lambda c: (-c[0], c[1]))


def _question(title: str, line: str, key: str | None) -> str:
    title = re.sub(r"^(decision|project|person)\s*:\s*", "", title, flags=re.I)
    if key and key.lower() != "decision":
        return f"what is our current {key.lower()}" if title.lower() in ("current", "goals") else f"what is the {key.lower()} for {title}"
    body = KV_RE.match(line).group(2) if key else line.lstrip("-* ")
    top = [w for w in dict.fromkeys(_words(body)) if w not in _words(title)][:3]
    return f"{title}: {' '.join(top)}".strip()


def evals_init(per_note: int = 2) -> str:
    notes = [p for p in brain.canon_files() if STUB_MARK not in p.read_text()]
    if not notes:
        return "evals init: no notes yet. Add a few notes to decisions/, people/ or projects/, then run it again."
    goldens, seen = [], set()
    for p in notes:
        text = p.read_text()
        rel = brain.rel(p)
        title = brain.note_title(text, p)
        for _score, n, line, key in _candidates(text)[:per_note]:
            q = _question(title, line, key)
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            slug = re.sub(r"[^a-z0-9]+", "-", f"{Path(rel).stem}-{n}".lower()).strip("-")
            goldens.append({"id": slug, "query": q, "expect_path": rel, "max_rank": 3, "quote": f"{rel}:{n} {line}"})
    for q in IDK_QUESTIONS:
        goldens.append({"id": "idk-" + re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-"), "query": q, "expect_known": False})
    out = brain.VAULT / "evals" / "proposed_tests.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ("# PROPOSED tests from `brain.py evals init`. Review before accepting:\n"
              "#  - reword each query the way you or your bots would actually ask it (keep the meaning);\n"
              "#  - delete any test whose quoted line isn't a fact worth remembering;\n"
              "#  - never change expect_path to whatever search returns today; that hides misses.\n"
              "# Then run: python3 tools/brain.py evals accept\n")
    out.write_text(header + yaml.safe_dump({"recall_at_5_floor": brain.RECALL5_FLOOR, "goldens": goldens},
                                           sort_keys=False, allow_unicode=True, width=200))
    n_idk = len(IDK_QUESTIONS)
    return f"evals init: wrote {brain.rel(out)} ({len(goldens) - n_idk} answerable from {len(notes)} notes, {n_idk} I-don't-know). Review it, then run: evals accept"


def evals_accept() -> str:
    prop = brain.VAULT / "evals" / "proposed_tests.yaml"
    if not prop.is_file():
        return "evals accept: nothing to accept; run evals init first"
    new = yaml.safe_load(prop.read_text()) or {}
    target = brain.TESTS
    cur = yaml.safe_load(target.read_text()) if target.is_file() else {"recall_at_5_floor": new.get("recall_at_5_floor", brain.RECALL5_FLOOR), "goldens": []}
    have = {g["id"] for g in cur.get("goldens") or []}
    added = [g for g in new.get("goldens") or [] if g["id"] not in have]
    cur["goldens"] = (cur.get("goldens") or []) + added
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Retrieval tests for this store (accepted from evals init; edit freely).\n"
                      + yaml.safe_dump(cur, sort_keys=False, allow_unicode=True, width=200))
    prop.unlink()
    return f"evals accept: added {len(added)} tests to {brain.rel(target) if target.is_relative_to(brain.VAULT) else target} ({len(cur['goldens'])} total). Run verify."
