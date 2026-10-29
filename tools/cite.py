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


MONTHS = {m: m[:3] for m in ("january", "february", "march", "april", "june", "july", "august", "september",
                              "october", "november", "december")} | {"sept": "sep"}


def _norm(w: str) -> str:
    w = re.sub(r"'s$", "", w.lower().replace("\u2019", "'")).strip("'")
    if w in MONTHS:
        return MONTHS[w]  # "September" in a question matches "Sep-10" in a note
    if len(w) >= 6 and w.endswith(("ies", "ier")):
        return w[:-2]  # supplies / supplier -> suppli
    if len(w) >= 7 and w.endswith(("ings", "ers")):
        w = w[:-1]  # "briefings" and "briefing" both end at "brief"
    for suf in ("ing", "ed", "es", "s"):
        if len(w) - len(suf) >= 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _words(t: str) -> set[str]:
    return {_norm(w) for w in re.findall(r"[A-Za-z0-9']+", t)}


def _keep(t: str) -> bool:
    """Content word: 3+ letters, or a 2+ char token with a digit (9U, 46, 60)."""
    return len(t) >= 3 or (len(t) >= 2 and any(ch.isdigit() for ch in t))


def attribute_terms(q: str) -> list[str]:
    docs = [_words(p.read_text(encoding="utf-8")) for p in brain.canon_files(brain.VAULT)]
    stop = {_norm(w) for w in brain.STOPWORDS} | STOP | {_norm(w) for w in OWNER}
    terms = [t for t in dict.fromkeys(_norm(w) for w in re.findall(r"[A-Za-z0-9']+", q)) if t not in stop and _keep(t)]
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
    terms = [t for t in dict.fromkeys(_norm(w) for w in re.findall(r"[A-Za-z0-9']+", q)) if t not in stop and _keep(t)]
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
# Rationale lines explain a fact; they state it only for a why/how question.
RATIONALE_RE = re.compile(r"^[-*]?\s*(Why|How|Related|Proof|Bar fit)\s*:", re.I)
# A metadata line is the answer when the question asks for that field.
META_ASKED = {"status": r"\bstatus\b", "revisit": r"\b(revisit\w*|review\w* again|check\w* again|re-?check\w*|reconsider\w*)\b",
              "owner": r"\b(owner|owns)\b", "source": r"\bsource\b"}


def skip_line(q: str, s: str) -> bool:
    """Headings, metadata (unless asked for) and rationale (unless a why/how question) are never the answer."""
    if len(s) < 8 or s.startswith(("#", "---")) or re.match(r"^status:", s):
        return True
    m = META_RE.match(s)
    if m:
        pat = META_ASKED.get(m.group(1).lower())
        return not (pat and re.search(pat, q, re.I))
    r = RATIONALE_RE.match(s)
    if r:
        return not re.match(rf"^\s*{'why' if r.group(1).lower() == 'why' else '(why|how)'}\b", q, re.I)
    return False


def coverage(terms: list[str] | dict[str, float], line: str, title: str = "", taken: set[str] | None = None) -> float:
    """Share of question terms the line states (exactly or by close embedding).
    The note title counts as context for the line, so "opening hours" can match the
    Decision line under "# Decision: Opening hours". No terms = nothing to verify = 0."""
    if not terms:
        return 0.0
    w = terms if isinstance(terms, dict) else dict.fromkeys(terms, 1.0)
    lw = [w for w in _words(line + " " + title) if _keep(w)]
    if not lw:
        return 0.0
    m = _vecs(lw)
    # A line word that already matches a question word exactly can't also stand in for another one
    # ("Prefers phone." must not cover both "phone" and "number").
    # `taken`: the other question words, when checking one word at a time ("offer" must not be stood in for by
    # "accepted", which already states the question's "accept").
    free = [i for i, x in enumerate(lw) if x not in w and x not in (taken or ())]
    # Words with a digit (12U, 2027, 46-60) are identifiers: exact match only. Embeddings put "12u" next to "10u".
    hit = lambda t: t in lw or not any(ch.isdigit() for ch in t) and bool(free) and float((m[free] @ _vecs([t])[0]).max()) >= SPAN_SYN_COS
    return sum(wt for t, wt in w.items() if hit(t)) / sum(w.values())


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
            if skip_line(q, s):
                continue
            out.append({"path": p, "line": i, "quote": s, "coverage": round(coverage(terms, s, title), 3),
                        "own": coverage(terms, s)})
    # Ties (the note title fills in for every line) go to the line that states more on its own,
    # so a fact added above the answer can't win just by coming first. Across notes, search rank
    # decides first, as before.
    out.sort(key=lambda c: (-c["coverage"], paths.index(c["path"]), -c["own"]))  # then search rank, then own words
    for c in out:
        c.pop("own")
    return [c for c in out[:n] if in_file(c)]


RESCUE_POOL = 60  # most lines sent to the cross-encoder
RESCUE_CE = 3.0  # MiniLM logit on (question, "title. line") a rescued line needs
RESCUE_MARGIN = 8.0  # or: beats the runner-up by this much (with half coverage); a lone candidate never qualifies


SPAN_COVER_TOP = 0.5  # looser coverage for a line in the top-ranked note, if the cross-encoder agrees


def _ce(q: str, docs: list[str]) -> list[float]:
    if brain._CE is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        brain._CE = TextCrossEncoder(brain.RERANK_MODEL)
    return [float(x) for x in brain._CE.rerank(q, docs)]


def top_note_ok(q: str, c: dict, top: str) -> bool:
    """Ported from the author's own vault: in the top-ranked note, half coverage is enough when the line's own
    words carry the asked attribute and the cross-encoder scores (question, "title. line") >= RESCUE_CE."""
    if c["path"] != top or c["coverage"] < SPAN_COVER_TOP or coverage(term_weights(q), c["quote"]) <= 0:
        return False
    lines = (brain.VAULT / top).read_text(encoding="utf-8").splitlines()
    title = next((l.lstrip("# ").split(":", 1)[-1] for l in lines if l.startswith("# ")), "")
    return _ce(q, [f"{title}. {c['quote']}"])[0] >= RESCUE_CE


def rescue(q: str, skip: set[str]) -> dict | None:
    """Fallback search (ported from the author's own vault, 2026-10-29): when the top notes hold no stating line,
    look line by line through every other current note. A line needs the question's distinctive words verbatim
    (2, or all of them when there are 1-2), full coverage as usual plus a cross-encoder logit >= RESCUE_CE,
    or a clear win over the runner-up. Superseded, proposed and derived notes are never searched."""
    terms, weights = attribute_terms(q), term_weights(q)
    if not terms:
        return None
    need = 1 if len(terms) <= 2 else 2
    sup = brain.superseded()
    pool = []
    files = brain.canon_files(brain.VAULT)
    allowed = brain.apply_scope_gates(q, {brain.rel(f) for f in files})  # exclusive scopes, as in search
    for f in files:
        p = brain.rel(f)
        if p in skip or p in sup or p in brain.DERIVED or p not in allowed:
            continue
        text = f.read_text(encoding="utf-8")
        if (brain.read_status(text) or "approved") == "proposed":
            continue
        lines = text.splitlines()
        title = next((l.lstrip("# ").split(":", 1)[-1] for l in lines if l.startswith("# ")), "")
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if skip_line(q, s):
                continue
            lw = _words(s)
            n = sum(t in lw for t in terms)
            if n >= need:
                pool.append({"path": p, "line": i, "quote": s, "_doc": f"{title}. {s}", "_n": n, "_title": title})
    if len(pool) < 2:
        return None
    pool.sort(key=lambda d: (-d["_n"], d["path"], d["line"]))
    pool = pool[:RESCUE_POOL]
    for d, ce in zip(pool, _ce(q, [d["_doc"] for d in pool])):
        d["ce"] = round(float(ce), 3)
    pool.sort(key=lambda d: -d["ce"])
    top = pool[0]
    top["coverage"] = round(coverage(weights, top["quote"], top["_title"]), 3)
    ok = (top["coverage"] >= SPAN_COVER and top["ce"] >= RESCUE_CE) or \
         (top["coverage"] >= 0.5 and top["ce"] >= 0.0 and top["ce"] - pool[1]["ce"] >= RESCUE_MARGIN)
    if not ok or not in_file(top):
        return None
    return {k: v for k, v in top.items() if not k.startswith("_")}


def unseen_terms(q: str) -> list[str]:
    """Question words that appear in no canon note at all (e.g. "passport")."""
    docs = [_words(p.read_text(encoding="utf-8")) for p in brain.canon_files(brain.VAULT)]
    return [t for t in term_weights(q) if not any(t in d for d in docs)]


YESNO_RE = re.compile(r"^\s*(did|does|do|is|are|was|were|has|have|had|can|could|should|will|would)\b", re.I)


def states_unseen(q: str, c: dict) -> bool:
    """A word the vault never uses must be stated (exactly or by close synonym) by the cited line, unless the
    line itself repeats a question word verbatim. Otherwise the line answers a nearby question:
    "Prefers phone." (phone ~ number, nothing verbatim) is not Dana's passport number.
    A line word that already states another question word can't be the synonym ("accepted" for "offer").
    Yes/no questions get no verbatim fallback: the answer depends on every word of the claim."""
    lines = (brain.VAULT / c["path"]).read_text(encoding="utf-8").splitlines()
    title = next((l.lstrip("# ").split(":", 1)[-1] for l in lines if l.startswith("# ")), "")
    qw = set(term_weights(q))
    if all(coverage({t: 1.0}, c["quote"], title, taken=qw - {t}) > 0 for t in unseen_terms(q)):
        return True
    if YESNO_RE.match(q):
        return False
    # A paraphrase ("coaches", "held") may be unseen too; it is fine when the line itself states a question word verbatim.
    return bool(qw & _words(c["quote"]))


# ---------------------------------------------------------------- answer check (local, no LLM)
# The line must state an answer of the asked kind, not just share the question's words.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
NAME2_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
TIME_RE = re.compile(r"\b(\d{4}-\d{2}(-\d{2})?|\d{1,2}:\d{2}|\d{1,2}\s*(am|pm)|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[\s-]*\d{1,2}|"
                     r"(19|20)\d{2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|daily|weekly|"
                     r"monthly|tonight|today|tomorrow|morning|evening|noon|midnight|after|before|every|each|whenever|once|until|upon|\d+\s*(day|week|month|year)s?)\b", re.I)
IDENT_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|[A-Z]{1,4}-\d{3,}|\d{4,})\b")
CHECK_CE = os.environ.get("BRAIN_CHECK_CE")  # optional MiniLM floor on (question, "title. line"); off by default:
# on keyword queries ("food cost target") the cross-encoder scores a right line below a wrong one.


# Provenance tail ("Date: ... From: ... Source: ...") records when a fact was written, not the fact.
PROV_RE = re.compile(r"\b(?:Date|From|Source|Supersedes)\s*:")
DAY_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(st|nd|rd|th)?\b(?!\d)|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", re.I)


def check_line(q: str, c: dict) -> str | None:
    """Why the cited line does not answer q (None = it does). Rules, then the local cross-encoder; an optional
    external check (BRAIN_CHECK_CMD) runs last. Every rule is about the kind of answer, not about a vault."""
    ql, line = q.lower(), c["quote"]
    note = (brain.VAULT / c["path"]).read_text(encoding="utf-8")
    title = next((l.lstrip("# ").split(":", 1)[-1] for l in note.splitlines() if l.startswith("# ")), "")
    if re.search(r"\be-?mail\b", ql) and not EMAIL_RE.search(line):
        return "asks for an email address; the line has none"
    if re.search(r"\b(phone|cell|mobile|telephone)\b", ql) and not PHONE_RE.search(line):
        return "asks for a phone number; the line has none"
    if re.search(r"\b(last name|surname|family name|full name)\b", ql) and not NAME2_RE.search(line):
        return "asks for a full or last name; the line has none"
    if re.search(r"\bstands? for\b", ql) and not re.search(r"\bstands? for\b|\bshort for\b|abbreviat", line, re.I):
        return "asks what something stands for; the line does not expand it"
    # An asked-for Revisit:/Date: line is the answer even when it says "standing (no review date)".
    if re.match(r"^\s*(when|what (time|date|day|year|month))\b", ql) and not META_RE.match(line) and not TIME_RE.search(line):
        return "asks when; the line states no date or time"
    # "On what date" wants a day, not a month or year range ("Jan 2011-Jun 2015").
    if re.search(r"\b(on )?(what|which|exact) date\b", ql) and not META_RE.match(line) and not DAY_RE.search(PROV_RE.split(line)[0]):
        return "asks for a date; the line states no day-level date"
    # A named date must be the cited note's own date (path or Date line) or be in the line itself;
    # other identifiers (R-13882, 2026) must appear somewhere in the note.
    date_line = next((l for l in note.splitlines() if re.match(r"^[-*]?\s*Date\s*:", l)), "")
    for ident in IDENT_RE.findall(q):
        hay = line + " " + c["path"] + " " + date_line if re.match(r"\d{4}-\d{2}-\d{2}$", ident) else note + " " + c["path"]
        if ident not in hay:
            return f"the question names {ident}; the cited note is not about it"
    rare = attribute_terms(q)
    if rare and not set(rare) & _words(line + " " + title + " " + c["path"].replace("-", " ").replace("/", " ")):
        return "none of the question's distinctive words (" + ", ".join(rare) + ") are in the line; synonyms alone don't answer"
    if CHECK_CE is not None and _ce(q, [f"{title}. {line}"])[0] < float(CHECK_CE):
        return "the cross-encoder does not rate the line as an answer"
    cmd = os.environ.get("BRAIN_CHECK_CMD")
    if cmd:  # optional, off by default: an LLM judge reading the prompt on stdin, answering YES or NO
        import subprocess
        prompt = (f"Question: {q}\nLine from the note \"{title}\": {line}\n"
                  "Does this line itself state the answer to the question? Reply YES or NO only.")
        try:
            out = subprocess.run(cmd, shell=True, input=prompt, capture_output=True, text=True, timeout=120).stdout
        except Exception:
            return "external check failed (fail closed)"
        if not re.search(r"\byes\b", out, re.I):
            return "external check: the line does not state the answer"
    return None


def source_status(paths: list[str]) -> dict[str, str]:
    """approved | superseded | proposed for each source; Prior: lines count as superseded."""
    sup = brain.superseded()
    return {p: "superseded" if p in sup else (brain.read_status((brain.VAULT / p).read_text(encoding="utf-8")) or "approved")
            for p in paths}


CONTEXT_MAX_LINES = 40


def context_for(path: str, line: int) -> dict:
    """Fuller context for a cited line: the heading chain above it, and the whole block under its nearest
    heading (the enclosing rule with its conditions, exceptions and sub-items), so a quote never travels alone."""
    lines = (brain.VAULT / path).read_text(encoding="utf-8").splitlines()
    i = max(0, min(int(line), len(lines)) - 1)
    lvl = lambda s: len(s) - len(s.lstrip("#")) if re.match(r"^#{1,6} ", s) else 0
    start = next((j for j in range(i, -1, -1) if lvl(lines[j])), None)
    chain, need = [], (lvl(lines[start]) if start is not None else 7)
    for j in range(start if start is not None else i, -1, -1):
        if lvl(lines[j]) and lvl(lines[j]) <= need:
            chain.insert(0, lines[j].lstrip("#").strip()); need = lvl(lines[j]) - 1
    b0 = start + 1 if start is not None else 0
    end = next((j for j in range(b0, len(lines)) if lvl(lines[j]) and lvl(lines[j]) <= (lvl(lines[start]) if start is not None else 6)), len(lines))
    block = [(n + 1, lines[n]) for n in range(b0, end) if lines[n].strip() and not META_RE.match(lines[n].strip())]
    if len(block) > CONTEXT_MAX_LINES:  # keep a window centred on the cited line
        k = next((x for x, (n, _) in enumerate(block) if n == i + 1), 0)
        lo = max(0, min(k - CONTEXT_MAX_LINES // 2, len(block) - CONTEXT_MAX_LINES))
        block = block[lo:lo + CONTEXT_MAX_LINES]
    return {"headings": chain, "block": [{"line": n, "text": t} for n, t in block], "path": path}


def cited_answer(q: str) -> dict:
    r = _cited_answer(q)
    m = re.match(r"^(.+?):(\d+) ", r.get("citation", "")) if r.get("known") else None
    if m:
        r["context"] = context_for(m.group(1), int(m.group(2)))
    return r


def _cited_answer(q: str) -> dict:
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
    missing = [t for t in unseen_terms(q)]
    if missing and not (cands and states_unseen(q, cands[0])):
        return {"known": False, "answer": f"I don't know: the vault never mentions {', '.join(missing)}.",
                "sources": base["sources"], "source_status": st, "candidates": cands}
    # A why-question that matches a note strongly is answered by that note's own "- Why:" line, if it has one
    if re.match(r"^\s*why\b", q, re.I) and cands and cands[0]["coverage"] >= SPAN_COVER:
        w = next((c for c in cands if c["path"] == cands[0]["path"] and re.match(r"^[-*]?\s*Why\s*:", c["quote"], re.I)), None)
        if w and not check_line(q, w):
            return {"known": True, "answer": w["quote"], "sources": base["sources"], "source_status": st, "candidates": cands,
                    "citation": f'{w["path"]}:{w["line"]} "{w["quote"]}"'}
    if cands and cands[0]["coverage"] < SPAN_COVER and top_note_ok(q, cands[0], current[0]) and not check_line(q, cands[0]):
        c = cands[0]
        return {"known": True, "answer": c["quote"], "sources": base["sources"], "source_status": st, "candidates": cands,
                "citation": f'{c["path"]}:{c["line"]} "{c["quote"]}"'}
    if not cands or cands[0]["coverage"] < SPAN_COVER:
        r = rescue(q, set(base["sources"][:3]))
        if r and not check_line(q, r):
            return {"known": True, "answer": r["quote"], "sources": list(dict.fromkeys([r["path"]] + base["sources"]))[:5],
                    "source_status": st, "candidates": [r] + cands[:2], "rescued": True,
                    "citation": f'{r["path"]}:{r["line"]} "{r["quote"]}"'}
        return {"known": False, "answer": "I don't know: no line in the cited notes states it.",
                "sources": base["sources"], "source_status": st, "candidates": cands}
    # Answer check: the first stating line that also passes check_line; otherwise I don't know.
    why_not = []
    for c in (c for c in cands if c["coverage"] >= SPAN_COVER):
        reason = check_line(q, c)
        if reason is None:
            return {"known": True, "answer": c["quote"], "sources": base["sources"], "source_status": st, "candidates": cands,
                    "citation": f'{c["path"]}:{c["line"]} "{c["quote"]}"'}
        why_not.append(f'{c["path"]}:{c["line"]}: {reason}')
    if why_not:  # the top notes' stating lines don't answer: look through the other notes, same check
        r = rescue(q, set(base["sources"][:3]))
        if r and not check_line(q, r):
            return {"known": True, "answer": r["quote"], "sources": list(dict.fromkeys([r["path"]] + base["sources"]))[:5],
                    "source_status": st, "candidates": [r] + cands[:2], "rescued": True,
                    "citation": f'{r["path"]}:{r["line"]} "{r["quote"]}"'}
    return {"known": False, "answer": "I don't know: " + (why_not[0].split(": ", 1)[1] if why_not else "no line states it") + ".",
            "sources": base["sources"], "source_status": st, "candidates": cands, "check": why_not}
