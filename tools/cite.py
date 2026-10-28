"""Cite-and-verify: answer only with an exact, file-verified quoted line that states the asked attribute.

cited_answer(q) runs brain.answer (search + rerank gate), then picks the best line in the cited notes.
A line counts only if it states at least 2/3 (strictly above 0.67) of the question's distinctive terms
(terms in at most 25% of notes), exactly or through a word-embedding synonym (cosine 0.75 or higher).
The quote is checked to be literally present at path:line. Otherwise: I don't know.
The answering agent makes the final call from the candidates (see README "Agent rules").
"""
from __future__ import annotations

import os
import re

import brain

SPAN_DF_MAX = 0.25
SPAN_SYN_COS = 0.75
SPAN_COVER = 0.67
STOP = {"what", "who", "when", "where", "which", "how", "why", "does", "did", "the",
        "get", "got", "make", "use", "keep", "tell", "know", "need", "want", "still", "now"}
OWNER = {w.lower() for w in os.environ.get("BRAIN_OWNER", "").split() if w}
_VEC: dict = {}


def _norm(w: str) -> str:
    w = re.sub(r"'s$", "", w.lower().replace("\u2019", "'")).strip("'")
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
    return [t for t in terms if sum(t in d for d in docs) / n <= SPAN_DF_MAX]


def _vecs(ws: list[str]):
    miss = [w for w in ws if w not in _VEC]
    if miss:
        _VEC.update(zip(miss, brain.EMB.embed(miss)))
    import numpy as np
    return np.stack([_VEC[w] for w in ws])


def coverage(terms: list[str], line: str) -> float:
    if not terms:
        return 1.0
    lw = [w for w in _words(line) if len(w) >= 3]
    if not lw:
        return 0.0
    m = _vecs(lw)
    return sum(t in lw or float((m @ _vecs([t])[0]).max()) >= SPAN_SYN_COS for t in terms) / len(terms)


def in_file(c: dict) -> bool:
    lines = (brain.VAULT / c["path"]).read_text(encoding="utf-8").splitlines()
    return 0 < c["line"] <= len(lines) and c["quote"] in lines[c["line"] - 1]


def candidates(q: str, paths: list[str], n: int = 3) -> list[dict]:
    terms, out = attribute_terms(q), []
    for p in paths[:3]:
        for i, ln in enumerate((brain.VAULT / p).read_text(encoding="utf-8").splitlines(), 1):
            s = ln.strip()
            if len(s) < 8 or s.startswith(("#", "---")) or re.match(r"^(-\s*Status|status):", s):
                continue
            out.append({"path": p, "line": i, "quote": s, "coverage": round(coverage(terms, s), 3)})
    out.sort(key=lambda c: -c["coverage"])
    return [c for c in out[:n] if in_file(c)]


def cited_answer(q: str) -> dict:
    base = brain.answer(q)
    if not base["known"]:
        return {**base, "candidates": []}
    cands = candidates(q, base["sources"])
    if not cands or cands[0]["coverage"] < SPAN_COVER:
        return {"known": False, "answer": "I don't know: no line in the cited notes states it.",
                "sources": base["sources"], "candidates": cands}
    c = cands[0]
    return {"known": True, "answer": c["quote"], "sources": base["sources"], "candidates": cands,
            "citation": f'{c["path"]}:{c["line"]} "{c["quote"]}"'}
