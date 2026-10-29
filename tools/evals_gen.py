"""`brain.py evals init|accept`: build retrieval tests from the user's own notes. Extractive, offline, no API.

init  reads every canon note, picks its most fact-like lines, and writes evals/proposed_tests.yaml:
      one question per line (expected note + the quoted line it should come from), plus a few
      off-topic "I don't know" questions. Nothing is trusted until you review it.
accept refuses REWRITE: placeholders and tests not marked reviewed: true, then merges the reviewed file into the store's retrieval tests and removes the proposal.
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


COMMENT_KEYS = {"note", "notes", "aside", "comment", "comments", "todo", "see also", "bar fit"}
KEY_QUESTIONS = {  # common field names mapped to questions people actually ask
    "why": "why did we decide {t}", "rationale": "why did we decide {t}", "reason": "why did we decide {t}",
    "last": "when was the last contact with {t}", "last contact": "when was the last contact with {t}",
    "primary": "what is the primary source for {t}", "role": "what is the role of {t}",
    "contact": "how do we contact {t}", "meeting": "when is the meeting for {t}",
    "owner": "who owns {t}", "deadline": "what is the deadline for {t}", "due": "when is {t} due",
    "budget": "what is the budget for {t}", "cost": "what does {t} cost", "price": "what is the price of {t}",
    "goal": "what is the goal of {t}", "next step": "what is the next step for {t}", "location": "where is {t}",
    "schedule": "what is the schedule for {t}", "email": "what is the email for {t}", "phone": "what is the phone number for {t}",
}
OWNER_PROBES = [  # personal attributes a bot vault rarely holds; the README's known weak spot for the score gate
    ("favorite color", "what is {o}'s favorite color"), ("blood type", "what is {o}'s blood type"),
    ("dentist", "who is {o}'s dentist"), ("shoe size", "what is {o}'s shoe size"),
    ("passport", "what is {o}'s passport number"), ("bank account", "what is {o}'s bank account number"),
    ("childhood pet", "what was the name of {o}'s childhood pet"), ("allergies", "what is {o} allergic to"),
]
DERIVED = brain.DERIVED  # dashboards rank below their sources by design; never a test target
REWRITE = "REWRITE:"


def clean_title(title: str) -> str:
    t = re.sub(r"^(decision|project|person)\s*:\s*", "", title, flags=re.I)
    t = re.sub(r"\([^)]*\)", "", t)
    t = brain.ISO_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -:,;\u2014\u2013")


def _question(title: str, line: str, key: str | None, rel: str, n: int) -> str:
    """A question that names the topic but not the answer; otherwise a REWRITE placeholder for a human."""
    t = clean_title(title)
    k = (key or "").lower()
    if k in KEY_QUESTIONS and t:  # unknown field names make ungrammatical questions; a human writes those
        q = KEY_QUESTIONS[k].format(t=t)
        if t.lower() in ("current", "goals"):
            q = f"what is our current {k}"
        return q  # template + topic only: the answer line's own words never enter the query
    return f"{REWRITE} ask, in your own words, the question that {rel} line {n} answers"


def _boilerplate(per_note: dict[str, list[tuple]]) -> set[tuple[str, int]]:
    """(note, line) pairs whose wording is near-identical (word Jaccard >= 0.4) to a line in another note.
    Stock sentences can't tell notes apart, so they make tests that pass or fail by luck."""
    lines = [(rel, n, set(_words(KV_RE.match(line).group(2) if key else line)))
             for rel, cands in per_note.items() for _s, n, line, key in cands]
    out = set()
    for i, (ra, na, wa) in enumerate(lines):
        for rb, nb, wb in lines[i + 1:]:
            if ra != rb and wa and wb and len(wa & wb) / len(wa | wb) >= 0.4:
                out |= {(ra, na), (rb, nb)}
    return out


def _targets() -> list[Path]:
    sup = brain.superseded()
    out = []
    for p in brain.canon_files():
        text = p.read_text()
        rel = brain.rel(p)
        if STUB_MARK in text or p.name in DERIVED or rel in sup or brain.read_status(text) == "superseded":
            continue
        out.append(p)
    return out


def owner_probes(owner: str, notes: list[Path]) -> list[dict]:
    """'I don't know' tests about the owner. A probe is skipped when its topic word appears in any note,
    since then the vault might really answer it."""
    words = set(re.findall(r"[a-z0-9]+", " ".join(p.read_text().lower() for p in notes)))
    out = []
    for topic, q in OWNER_PROBES:
        if any(w in words for w in topic.split()):  # whole words: "pet" is not in "carpet"
            continue
        out.append({"id": "idk-owner-" + topic.replace(" ", "-"), "query": q.format(o=owner),
                    "expect_known": False, "reviewed": False})
    return out


def evals_init(per_note: int = 2, quotes: bool = False, owner: str = "") -> tuple[str, int]:
    notes = _targets()
    if not notes:
        return "evals init: no notes yet. Add a few notes to decisions/, people/ or projects/, then run it again.", 0
    cands = {brain.rel(p): [c for c in _candidates(p.read_text()) if not (c[3] and c[3].lower() in COMMENT_KEYS)] for p in notes}
    stock = _boilerplate(cands)
    goldens, seen, n_rewrite = [], set(), 0
    for p in notes:
        text = p.read_text()
        rel = brain.rel(p)
        title = brain.note_title(text, p)
        picked = [c for c in cands[rel] if (rel, c[1]) not in stock]
        for _score, n, line, key in picked[:per_note]:
            q = _question(title, line, key, rel, n)
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            n_rewrite += q.startswith(REWRITE)
            slug = re.sub(r"[^a-z0-9]+", "-", f"{Path(rel).stem}-{n}".lower()).strip("-")
            g = {"id": slug, "query": q, "expect_path": rel, "max_rank": 3, "source": f"{rel}:{n}", "reviewed": False}
            if quotes:
                g["quote"] = line
            goldens.append(g)
    for q in IDK_QUESTIONS:
        goldens.append({"id": "idk-" + re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-"), "query": q,
                        "expect_known": False, "reviewed": False})
    probes = owner_probes(owner, notes) if owner else []
    goldens += probes
    out = brain.VAULT / "evals" / "proposed_tests.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ("# PROPOSED tests from `brain.py evals init`. This file is gitignored; it is never committed.\n"
              "# For each test:\n"
              "#  - if the query starts with REWRITE:, open the source line and write the question you would ask;\n"
              "#  - reword any other query the way you or your bots would actually ask it (don't copy the answer's words);\n"
              "#  - delete tests whose line isn't a fact worth remembering;\n"
              "#  - never change expect_path to whatever search returns today; that hides misses;\n"
              "#  - then set reviewed: true.\n"
              "# Then run: python3 tools/brain.py evals accept   (or --all-reviewed once you've checked every test)\n")
    out.write_text(header + yaml.safe_dump({"recall_at_5_floor": brain.RECALL5_FLOOR, "goldens": goldens},
                                           sort_keys=False, allow_unicode=True, width=200))
    n_idk = len(IDK_QUESTIONS) + len(probes)
    hint = "" if owner else " Tip: add --owner \"<name>\" (or set BRAIN_OWNER) to also probe questions about you."
    return (f"evals init: wrote {brain.rel(out)} ({len(goldens) - n_idk} answerable from {len(notes)} notes, "
            f"{n_rewrite} need a question written, {n_idk} I-don't-know). Review it, then run: evals accept.{hint}"), 0


def evals_accept(all_reviewed: bool = False) -> tuple[str, int]:
    prop = brain.VAULT / "evals" / "proposed_tests.yaml"
    if not prop.is_file():
        return "evals accept: nothing to accept; run evals init first", 1
    new = (yaml.safe_load(prop.read_text()) or {}).get("goldens") or []
    rewrite = [g["id"] for g in new if str(g.get("query", "")).startswith(REWRITE)]
    if rewrite:
        return (f"evals accept: refused. {len(rewrite)} test(s) still have a REWRITE: placeholder query "
                f"(first: {rewrite[0]}). Write the question or delete the test."), 1
    unreviewed = [g["id"] for g in new if g.get("reviewed") is not True]
    if unreviewed and not all_reviewed:
        return (f"evals accept: refused. {len(unreviewed)} of {len(new)} test(s) are not marked reviewed: true "
                f"(first: {unreviewed[0]}). Review them, or pass --all-reviewed to confirm you checked every one."), 1
    target = brain.TESTS
    cur = (yaml.safe_load(target.read_text()) if target.is_file() else None) or {"recall_at_5_floor": brain.RECALL5_FLOOR}
    key = "cases" if "cases" in cur else "goldens"
    have = {g["id"] for g in cur.get(key) or []}
    added = [{k: v for k, v in g.items() if k != "reviewed"} for g in new if g["id"] not in have]
    cur[key] = (cur.get(key) or []) + added
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Retrieval tests for this store (accepted from evals init; edit freely).\n"
                      + yaml.safe_dump(cur, sort_keys=False, allow_unicode=True, width=200))
    prop.unlink()
    return f"evals accept: added {len(added)} tests to {brain.rel(target) if target.is_relative_to(brain.VAULT) else target} ({len(cur[key])} total). Run verify.", 0
