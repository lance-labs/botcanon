"""Cite-and-verify: answer only with an exact, file-verified quoted line that states the asked attribute.

cited_answer(q) runs brain.answer (search + rerank gate), then picks the best line in the cited notes.
A line counts only if it states at least 2/3 of the question's weighted content words, exactly or through a
word-embedding synonym (cosine 0.78 or higher). Distinctive words (in at most 25% of notes) weigh 1.0, common
ones 0.6, so one shared common or rare word alone never answers a two-word question. Ties go to the higher-ranked
note, then to the line that states more on its own (not via the note title).
The quote is checked to be literally present at path:line. Otherwise: I don't know.
The answering agent makes the final call from the candidates (see README "Agent rules").
"""
from __future__ import annotations

import os
import re

import brain

SPAN_DF_MAX = 0.25
SPAN_SYN_COS = 0.78  # 0.75 let bakery~flour, sell~buy, order~deliver, number~one count as the same word
SPAN_COVER = 2 / 3
COMMON_W = 0.6  # weight of a common question word next to a rare one (1.0); 1 rare + 1 common hit alone = 0.625 < 2/3
STOP = {"what", "who", "when", "where", "which", "how", "why", "does", "did", "the",
        "get", "got", "make", "use", "keep", "tell", "know", "need", "want", "still", "now", "much", "many"}
OWNER = {w.lower() for w in os.environ.get("BRAIN_OWNER", "").split() if w}
_VEC: dict = {}


def _norm(w: str) -> str:
    w = re.sub(r"'s$", "", w.lower().replace("\u2019", "'")).strip("'")
    if len(w) >= 6 and w.endswith(("ies", "ier")):
        return w[:-2]  # supplies / supplier -> suppli
    for suf in ("ing", "ed", "es", "s"):
        if len(w) - len(suf) >= 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _words(t: str) -> set[str]:
    return {_norm(w) for w in re.findall(r"[A-Za-z0-9']+", t)}


def attribute_terms(q: str) -> list[str]:
    docs = [_words(p.read_text(encoding="utf-8")) for p in brain.canon_files(brain.VAULT)]
    stop = {_norm(w) for w in brain.STOPWORDS} | STOP | {_norm(w) for w in OWNER}
    terms = [t for t in dict.fromkeys(_norm(w) for w in re.findall(r"[A-Za-z0-9']+", q)) if t not in stop and len(t) >= 3]
    n = max(len(docs), 1)
    rare = [t for t in terms if sum(t in d for d in docs) / n <= SPAN_DF_MAX]
    # No rare words (common question, or a tiny vault): fall back to every content word rather
    # than to none. An empty term list used to make every line "cover" the question (BC-01).
    return rare or terms


def term_weights(q: str) -> dict[str, float]:
    """Every content word of the question counts; rare ones count more. Dropping common words
    entirely let "when does the bakery open" be answered by any line that says "bakery"."""
    docs = [_words(p.read_text(encoding="utf-8")) for p in brain.canon_files(brain.VAULT)]
    stop = {_norm(w) for w in brain.STOPWORDS} | STOP | {_norm(w) for w in OWNER}
    terms = [t for t in dict.fromkeys(_norm(w) for w in re.findall(r"[A-Za-z0-9']+", q)) if t not in stop and len(t) >= 3]
    n = max(len(docs), 1)
    rare = {t for t in terms if sum(t in d for d in docs) / n <= SPAN_DF_MAX}
    return {t: 1.0 if (t in rare or not rare) else COMMON_W for t in terms}


def _vecs(ws: list[str]):
    miss = [w for w in ws if w not in _VEC]
    if miss:
        _VEC.update(zip(miss, brain.EMB.embed(miss)))
    import numpy as np
    return np.stack([_VEC[w] for w in ws])


META_RE = re.compile(r"^[-*]?\s*(Status|Date|Owner|From|Source|Prior|Revisit|Supersedes|Updated)\s*:", re.I)


def coverage(terms: list[str] | dict[str, float], line: str, title: str = "") -> float:
    """Share of question terms the line states (exactly or by close embedding).
    The note title counts as context for the line, so "opening hours" can match the
    Decision line under "# Decision: Opening hours". No terms = nothing to verify = 0."""
    if not terms:
        return 0.0
    w = terms if isinstance(terms, dict) else dict.fromkeys(terms, 1.0)
    lw = [w for w in _words(line + " " + title) if len(w) >= 3]
    if not lw:
        return 0.0
    m = _vecs(lw)
    return sum(wt for t, wt in w.items() if t in lw or float((m @ _vecs([t])[0]).max()) >= SPAN_SYN_COS) / sum(w.values())


def in_file(c: dict) -> bool:
    lines = (brain.VAULT / c["path"]).read_text(encoding="utf-8").splitlines()
    return 0 < c["line"] <= len(lines) and c["quote"] in lines[c["line"] - 1]


def candidates(q: str, paths: list[str], n: int = 3) -> list[dict]:
    terms, out = term_weights(q), []
    for p in paths[:3]:
        lines = (brain.VAULT / p).read_text(encoding="utf-8").splitlines()
        title = next((l.lstrip("# ").split(":", 1)[-1] for l in lines if l.startswith("# ")), "")
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if len(s) < 8 or s.startswith(("#", "---")) or META_RE.match(s) or re.match(r"^status:", s):
                continue  # headings and metadata (Date:, Owner:, ...) are never the answer
            out.append({"path": p, "line": i, "quote": s, "coverage": round(coverage(terms, s, title), 3),
                        "own": coverage(terms, s)})
    # Ties (the note title fills in for every line) go to the line that states more on its own,
    # so a fact added above the answer can't win just by coming first. Across notes, search rank
    # decides first, as before.
    out.sort(key=lambda c: (-c["coverage"], paths.index(c["path"]), -c["own"]))  # then search rank, then own words
    for c in out:
        c.pop("own")
    return [c for c in out[:n] if in_file(c)]


def source_status(paths: list[str]) -> dict[str, str]:
    """approved | superseded | proposed for each source; Prior: lines count as superseded."""
    sup = brain.superseded()
    return {p: "superseded" if p in sup else (brain.read_status((brain.VAULT / p).read_text(encoding="utf-8")) or "approved")
            for p in paths}


def cited_answer(q: str) -> dict:
    base = brain.answer(q)
    if not base["known"]:
        return {**base, "candidates": [], "source_status": {}}
    st = source_status(base["sources"])
    # CURRENT.md is a derived dashboard with no writer in this repo: cite the notes it summarizes, never it (BC-10)
    current = [p for p in base["sources"] if st[p] not in ("superseded", "proposed") and p not in brain.DERIVED]
    if not current:  # only replaced notes match: never state them as the current fact
        succ = brain.successors()
        nxt = sorted({succ[p] for p in base["sources"] if p in succ})
        return {"known": False, "answer": "I don't know: only superseded notes match" + (f"; see {', '.join(nxt)}" if nxt else "") + ".",
                "sources": base["sources"], "source_status": st, "candidates": []}
    cands = candidates(q, current)
    if not cands or cands[0]["coverage"] < SPAN_COVER:
        return {"known": False, "answer": "I don't know: no line in the cited notes states it.",
                "sources": base["sources"], "source_status": st, "candidates": cands}
    c = cands[0]
    return {"known": True, "answer": c["quote"], "sources": base["sources"], "source_status": st, "candidates": cands,
            "citation": f'{c["path"]}:{c["line"]} "{c["quote"]}"'}
