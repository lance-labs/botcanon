#!/usr/bin/env python3
"""brain.py - a small, file-first second brain.

Markdown notes are the source of truth. SQLite (FTS5 + embeddings) is a
rebuildable index. Commands: ingest, search, compile, verify, status, flush.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from note_status import STATUS_RE, read_status, status_check, status_fixture  # noqa: E402

TOOLS = Path(__file__).resolve().parent
VAULT = Path(os.environ.get("BRAIN_VAULT", TOOLS.parent)).resolve()
INDEX_DIR = VAULT / ".index"
DB_PATH = INDEX_DIR / "brain.db"
TESTS = TOOLS / "retrieval_tests.yaml"
SCHEMA_VERSION = "2"  # bump when indexed text changes; forces a full rebuild
EMBED_MODEL = os.environ.get("BRAIN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

CANON_DIRS = tuple(os.environ.get("BRAIN_DIRS", "decisions,people,projects").split(","))
CANON_ROOT = ("GOALS.md", "CURRENT.md")
RRF_K = 60
CANDIDATES = 40
MAX_HITS_PER_NOTE = 2
RECALL5_FLOOR = 0.9
INBOX_MAX_HOURS = 48

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
STOPWORDS = frozenset(
    """a an and are as at be but by can could did do does for from had has have how i if in is it its
    me my of on or our should so than that the their them then there these they this to us was we were
    what when where which who whom why will with would you your about any""".split()
)
PRIOR_RE = re.compile(r"^-\s*Prior:\s*(\S+)", re.MULTILINE)
DATE_RE = re.compile(r"^-\s*Date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
DECISION_RE = re.compile(r"^-\s*Decision:\s*(.+)$", re.MULTILINE)
REVISIT_RE = re.compile(r"^-?\s*Revisit:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# ---------------------------------------------------------------- notes

def canon_files(vault: Path = None, dirs: tuple[str, ...] | None = None) -> list[Path]:
    vault = vault or VAULT
    out = [vault / f for f in CANON_ROOT if (vault / f).is_file()]
    for d in dirs or CANON_DIRS:
        out += sorted((vault / d).rglob("*.md")) if (vault / d).is_dir() else []
    return out


def rel(p: Path, vault: Path = None) -> str:
    return p.relative_to(vault or VAULT).as_posix()


def note_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def chunk_note(text: str) -> list[tuple[str, str]]:
    """Split on headings; each chunk is (heading, body)."""
    chunks, heading, buf = [], "", []
    for line in text.splitlines():
        if re.match(r"^#{1,3} ", line):
            if "".join(buf).strip():
                chunks.append((heading, "\n".join(buf).strip()))
            heading, buf = line.lstrip("#").strip(), [line]
        else:
            buf.append(line)
    if "".join(buf).strip():
        chunks.append((heading, "\n".join(buf).strip()))
    return chunks


def superseded(vault: Path = None) -> set[str]:
    """Decisions named on a '- Prior:' line of another decision."""
    vault = vault or VAULT
    out = set()
    for p in (vault / "decisions").glob("*.md"):
        for m in PRIOR_RE.finditer(p.read_text()):
            out.add(m.group(1).strip("`"))
    return out


_STATUS: dict[str, str | None] = {}


def status_of(path: str) -> str | None:
    """Explicit `- Status:` of a note (proposed | approved | superseded), or None."""
    if path not in _STATUS:
        fp = VAULT / path
        _STATUS[path] = read_status(fp.read_text()) if fp.is_file() else None
    return _STATUS[path]


def path_weight(path: str, sup: set[str]) -> float:
    """Authority ranking. Explicit status first, then folder + Prior: fallback."""
    st = status_of(path)
    if st in ("superseded", "proposed"):
        return 0.1
    if path.startswith("decisions/"):
        return 0.1 if (st is None and path in sup) else 1.02
    if path == "GOALS.md":
        return 1.02
    if path.startswith(("people/", "projects/")):
        return 1.0
    if path == "CURRENT.md":
        return 0.4  # derived dashboard; never outranks its sources
    return 0.1


# ---------------------------------------------------------------- embeddings

class Embedder:
    def __init__(self) -> None:
        self._m = None

    def _model(self):
        if self._m is None:
            from fastembed import TextEmbedding
            self._m = TextEmbedding(EMBED_MODEL)
        return self._m

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        if query:
            texts = ["Represent this sentence for searching relevant passages: " + t for t in texts]
        v = np.array(list(self._model().embed(texts)), dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


EMB = Embedder()


# ---------------------------------------------------------------- index

def connect() -> sqlite3.Connection:
    INDEX_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS notes(path TEXT PRIMARY KEY, sha TEXT, title TEXT);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT, heading TEXT, text TEXT, emb BLOB);
        CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(text, heading, title, path UNINDEXED,
            tokenize='porter unicode61');
        """
    )
    return conn


def meta(conn, key, value=None):
    if value is None:
        r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None
    conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))


def ingest(full: bool = False) -> dict:
    """Incremental by sha256; full rebuild when schema or embed model changed."""
    conn = connect()
    if full or meta(conn, "schema") != SCHEMA_VERSION or meta(conn, "model") != EMBED_MODEL:
        conn.executescript("DELETE FROM notes; DELETE FROM chunks; DELETE FROM fts;")
        full = True
    seen, changed = set(), 0
    for p in canon_files():
        r, text = rel(p), p.read_text()
        sha = hashlib.sha256(text.encode()).hexdigest()
        seen.add(r)
        row = conn.execute("SELECT sha FROM notes WHERE path=?", (r,)).fetchone()
        if row and row["sha"] == sha:
            continue
        changed += 1
        _drop(conn, r)
        title = note_title(text, p)
        parts = chunk_note(STATUS_RE.sub("", text))  # status is ranking metadata, not content
        vecs = EMB.embed([f"{h}\n{b}" for h, b in parts]) if parts else []
        for (h, b), v in zip(parts, vecs):
            cur = conn.execute("INSERT INTO chunks(path,heading,text,emb) VALUES(?,?,?,?)", (r, h, b, v.tobytes()))
            conn.execute("INSERT INTO fts(rowid,text,heading,title,path) VALUES(?,?,?,?,?)", (cur.lastrowid, b, h, title, r))
        conn.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (r, sha, title))
    removed = [r["path"] for r in conn.execute("SELECT path FROM notes") if r["path"] not in seen]
    for r in removed:
        _drop(conn, r)
    meta(conn, "schema", SCHEMA_VERSION)
    meta(conn, "model", EMBED_MODEL)
    meta(conn, "last_index_ts", datetime.now(timezone.utc).isoformat())
    conn.commit()
    return {"changed": changed, "removed": len(removed), "full": full}


def _drop(conn, path):
    ids = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE path=?", (path,))]
    for i in ids:
        conn.execute("DELETE FROM fts WHERE rowid=?", (i,))
    conn.execute("DELETE FROM chunks WHERE path=?", (path,))
    conn.execute("DELETE FROM notes WHERE path=?", (path,))


# ---------------------------------------------------------------- search

def content_tokens(q: str) -> list[str]:
    toks = TOKEN_RE.findall(q)
    return [t for t in toks if t.lower() not in STOPWORDS] or toks


def _fts(conn, match: str) -> list[int]:
    try:
        return [r[0] for r in conn.execute("SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?", (match, CANDIDATES))]
    except sqlite3.OperationalError:
        return []


def lexical(conn, q: str) -> list[int]:
    toks = content_tokens(q)
    if not toks:
        return []
    hits = _fts(conn, " AND ".join(toks))
    return hits or (_fts(conn, " OR ".join(toks)) if len(toks) > 1 else [])  # full-sentence fallback


def title_hits(conn, q: str) -> list[int]:
    toks = content_tokens(q)
    return _fts(conn, "title : (" + " AND ".join(toks) + ")") if toks else []


SEM_MIN = 0.55  # below this cosine, a chunk is not an answer


def semantic(conn, q: str) -> list[int]:
    rows = conn.execute("SELECT id, emb FROM chunks").fetchall()
    if not rows:
        return []
    m = np.stack([np.frombuffer(r["emb"], dtype=np.float32) for r in rows])
    s = m @ EMB.embed([q], query=True)[0]
    order = np.argsort(-s)[:CANDIDATES]
    return [rows[i]["id"] for i in order if s[i] >= SEM_MIN]


# Second-pass reranker: a local cross-encoder re-scores the top RERANK_N hybrid hits. Final order is an
# equal-weight RRF of the hybrid rank and the cross-encoder rank, so authority weights still count.
# Off with BRAIN_RERANK=0.
RERANK_MODEL = os.environ.get("BRAIN_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
RERANK_N = 20
RERANK_FLOOR = -9.4  # cross-encoder logit; below it, answer() says "I don't know" (see docs/WHY.md)
_CE = None


def rerank_on() -> bool:
    return os.environ.get("BRAIN_RERANK", "1").strip().lower() not in {"0", "false", "off", "no"}


def rerank(q: str, hits: list[dict], k: int) -> list[dict]:
    global _CE
    if not hits:
        return hits
    if _CE is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _CE = TextCrossEncoder(RERANK_MODEL)
    scores = [float(x) for x in _CE.rerank(q, [f"{h['heading']}. {h['_text'][:1500]}" for h in hits])]
    ce_rank = {i: r for r, i in enumerate(sorted(range(len(hits)), key=lambda i: -scores[i]))}
    order = sorted(range(len(hits)), key=lambda i: -(1 / (RRF_K + i + 1) + 1 / (RRF_K + ce_rank[i] + 1)))
    return [{**hits[i], "rerank": round(scores[i], 4)} for i in order[:k]]


def search(q: str, k: int = 5, mode: str = "hybrid") -> list[dict]:
    use_rr = mode == "hybrid" and rerank_on()
    want = max(k, RERANK_N) if use_rr else k
    conn = connect()
    lists = {"lexical": [lexical(conn, q)], "semantic": [semantic(conn, q)]}.get(mode)
    if lists is None:
        lists = [lexical(conn, q), semantic(conn, q), title_hits(conn, q)]
    scores: dict[int, float] = {}
    for lst in lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank + 1)
    sup = superseded()
    out, per = [], {}
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id,path,heading,text FROM chunks WHERE id IN ({','.join('?' * len(scores)) or 'NULL'})", list(scores))}
    for cid, sc in sorted(((c, s * path_weight(rows[c]["path"], sup)) for c, s in scores.items()), key=lambda x: -x[1]):
        r = rows[cid]
        if per.get(r["path"], 0) >= MAX_HITS_PER_NOTE:
            continue
        per[r["path"]] = per.get(r["path"], 0) + 1
        out.append({"chunk_id": cid, "score": round(sc, 6), "path": r["path"], "heading": r["heading"],
                    "snippet": r["text"][:200], "_text": r["text"]})
        if len(out) >= want:
            break
    if use_rr:
        out = rerank(q, out, k)
    for h in out:
        h.pop("_text", None)
    return out


# ---------------------------------------------------------------- answer / provenance / propose

def answer(q: str) -> dict:
    """Cite the best note, or say 'I don't know' when nothing clears the threshold.

    Reranker on (default): confident = best cross-encoder logit > RERANK_FLOOR.
    Reranker off: confident = a lexical match on the content words, or a semantic match >= SEM_MIN.
    Title-only or OR-fallback-only hits are not enough on their own.
    """
    res = search(q, k=5)
    if res and "rerank" in res[0]:  # reranker on: trust the cross-encoder score
        hits = res if max(h["rerank"] for h in res) > RERANK_FLOOR else []
    else:
        conn = connect()
        toks = content_tokens(q)
        strict = set(_fts(conn, " AND ".join(toks))) if toks else set()
        sem = set(semantic(conn, q))
        hits = [h for h in res if h["chunk_id"] in strict | sem]
    if not hits:
        return {"known": False, "answer": "I don't know: nothing in the vault clears the threshold.", "sources": []}
    top = hits[0]
    return {"known": True, "answer": top["snippet"], "sources": [h["path"] for h in hits[:3]]}


FRONT_RE = re.compile(r"^-\s*(From|Source|Date|Owner):\s*(.+)$", re.MULTILINE)


def why(q: str) -> dict:
    """Provenance: where the best-matching note and its log claims came from."""
    hits = search(q, k=1)
    if not hits:
        return {"found": False, "reason": "I don't know: no note matches."}
    path = hits[0]["path"]
    text = (VAULT / path).read_text()
    fields = {k.lower(): v.strip() for k, v in FRONT_RE.findall(text)}
    claims = [c for c in read_log(VAULT) if c.get("canon") == path]
    return {"found": True, "path": path, "fields": fields,
            "claims": [{k: c.get(k) for k in ("id", "ts", "from_agent", "source", "text")} for c in claims]}


SLUG_RE = re.compile(r"[^a-z0-9]+")


def propose(text: str, from_agent: str, source: str, vault: Path = None) -> Path:
    """Agents never write canon. A proposal is a dated inbox file with provenance."""
    vault = vault or VAULT
    if not text.strip() or not from_agent.strip() or not source.strip():
        raise ValueError("text, from_agent and source are all required")
    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    slug = SLUG_RE.sub("-", text.lower())[:40].strip("-") or "note"
    p = inbox / f"{now:%Y-%m-%dT%H%M%S}-{slug}.md"
    p.write_text(f"---\nstatus: proposed\nfrom_agent: {json.dumps(from_agent)}\nsource: {json.dumps(source)}\n"
                 f"date: {now.isoformat()}\n---\n\n{text.strip()}\n")
    return p


# ---------------------------------------------------------------- compile

def read_log(vault: Path) -> list[dict]:
    claims = []
    for p in sorted((vault / "log").glob("*.jsonl")):
        claims += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return claims


def decision_for(vault: Path, entity: str) -> dict | None:
    sup = superseded(vault)
    for p in sorted((vault / "decisions").glob(f"*-{entity}.md"), reverse=True):
        r, t = rel(p, vault), p.read_text()
        d, dec = DATE_RE.search(t), DECISION_RE.search(t)
        if r not in sup and d and dec:
            return {"path": r, "date": d.group(1), "text": dec.group(1).strip()}
    return None


def compile_entity(entity: str, vault: Path = None) -> dict:
    """CURRENT = newest decision + current log claims newer than it. Older claims are OUTRANKED."""
    vault = vault or VAULT
    claims = [c for c in read_log(vault) if c.get("entity") == entity]
    live = [c for c in claims if not c.get("successor")]
    dec = decision_for(vault, entity)
    current, outranked = [], []
    if dec:
        current.append({"source": dec["path"], "date": dec["date"], "text": dec["text"]})
    for c in live:
        if dec and c.get("ts", "")[:10] < dec["date"]:
            outranked.append(c)
        else:
            current.append({"source": f"log:{c['id']}", "date": c.get("ts", "")[:10], "text": c["text"]})
    history = [c for c in claims if c.get("successor")]
    return {"entity": entity, "current": current, "outranked": outranked, "history": history}


def format_compile(pkg: dict) -> str:
    lines = [f"# {pkg['entity']}", "## CURRENT"]
    lines += [f"- [{c['source']} {c['date']}] {c['text']}" for c in pkg["current"]] or ["- (nothing)"]
    if pkg["outranked"]:
        lines += ["## OUTRANKED (older than the governing decision)"]
        lines += [f"- [log:{c['id']} {c.get('ts', '')[:10]}] {c['text']}" for c in pkg["outranked"]]
    if pkg["history"]:
        lines += ["## SUPERSEDED"] + [f"- [log:{c['id']}] {c['text']} -> {c['successor']}" for c in pkg["history"]]
    return "\n".join(lines)


def authority_fixture() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / "decisions").mkdir()
        (v / "log").mkdir()
        (v / "decisions" / "2026-05-01-widget.md").write_text("# Widget\n\n- Date: 2026-05-01\n- Decision: Widgets are blue.\n")
        (v / "log" / "x.jsonl").write_text(
            json.dumps({"id": "c1", "ts": "2026-04-01T00:00:00Z", "entity": "widget", "text": "Widgets are red."}) + "\n"
            + json.dumps({"id": "c2", "ts": "2026-06-01T00:00:00Z", "entity": "widget", "text": "Widgets ship in May."}) + "\n")
        p = compile_entity("widget", v)
        ok = (p["current"][0]["text"] == "Widgets are blue." and [c["id"] for c in p["outranked"]] == ["c1"]
              and any("May" in c["text"] for c in p["current"]))
        return ok, "decision outranks older log claim; newer claim kept" if ok else f"bad package: {p}"


# ---------------------------------------------------------------- freshness

def revisit_due(text: str) -> str | None:
    """'Revisit: standing ...' never comes due; 'Revisit: ~YYYY-MM-DD' does."""
    m = REVISIT_RE.search(text)
    if not m or m.group(1).strip().lower().startswith("standing"):
        return None
    d = ISO_RE.search(m.group(1))
    return d.group(1) if d else None


def freshness(vault: Path = None, last_index_ts: str | None = None, today: date | None = None,
              dirs: tuple[str, ...] | None = None) -> dict:
    vault = vault or VAULT
    today = today or date.today()
    red, yellow = [], []
    if last_index_ts:
        li = datetime.fromisoformat(last_index_ts).timestamp()
        newer = [rel(p, vault) for p in canon_files(vault, dirs) if p.stat().st_mtime > li + 1]
        if newer:
            red.append(f"{len(newer)} note(s) newer than the index: run flush")
    else:
        red.append("never indexed")
    now = datetime.now().timestamp()
    old = [p.name for p in (vault / "inbox").glob("*.md") if (now - p.stat().st_mtime) / 3600 > INBOX_MAX_HOURS] if (vault / "inbox").is_dir() else []
    if old:
        red.append(f"{len(old)} inbox item(s) older than {INBOX_MAX_HOURS}h")
    sup = superseded(vault)
    due = []
    for p in sorted((vault / "decisions").glob("*.md")) if (vault / "decisions").is_dir() else []:
        d = revisit_due(p.read_text())
        if d and d < today.isoformat() and rel(p, vault) not in sup:
            due.append({"path": rel(p, vault), "revisit": d})
    if due:
        yellow.append(f"{len(due)} decision(s) past Revisit")
    level = "red" if red else "yellow" if yellow else "green"
    return {"level": level, "red": red, "yellow": yellow, "revisit_due": due}


def freshness_fixture() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / "decisions").mkdir()
        f = v / "decisions" / "d.md"
        f.write_text("# D\n\n- Revisit: ~2000-01-01\n")
        ts = datetime.now(timezone.utc).isoformat()
        os.utime(f, (1, 1))
        if freshness(v, ts, dirs=("decisions",))["level"] != "yellow":
            return False, "past Revisit date not yellow"
        f.write_text("# D\n\n- Revisit: standing (no review date)\n")
        os.utime(f, (1, 1))
        if freshness(v, ts, dirs=("decisions",))["level"] != "green":
            return False, "standing Revisit flagged"
        os.utime(f, None)
        if freshness(v, "2000-01-01T00:00:00+00:00", dirs=("decisions",))["level"] != "red":
            return False, "note newer than index not red"
    return True, "past revisit yellow, standing green, stale index red"


def feature_fixture() -> tuple[bool, str]:
    """answer says I don't know on nonsense; why carries provenance; propose writes inbox only."""
    errs = []
    if answer("zxqv blorptastic quantum chromodynamics")["known"]:
        errs.append("answer did not say I don't know")
    if not answer("who supplies our flour")["known"]:
        errs.append("answer missed a known fact")
    w = why("opening hours")
    if not w.get("found") or not w["fields"].get("source") or not w["fields"].get("from"):
        errs.append(f"why lacks provenance: {w}")
    with tempfile.TemporaryDirectory() as d:
        p = propose("Rye flour arrives Fridays.", "test-agent", "unit test", Path(d))
        written = [x.relative_to(d).as_posix() for x in Path(d).rglob("*") if x.is_file()]
        if written != [p.relative_to(d).as_posix()] or not written[0].startswith("inbox/") or "from_agent" not in p.read_text():
            errs.append(f"propose wrote {written}")
        try:
            propose("x", "", "y", Path(d)); errs.append("propose accepted empty from_agent")
        except ValueError:
            pass
    return (not errs, "; ".join(errs) or "answer/why/propose behave")


# ---------------------------------------------------------------- verify

def load_tests() -> dict:
    import yaml
    return yaml.safe_load(TESTS.read_text())


def hooks_installed() -> tuple[bool, str]:
    git = VAULT / ".git"
    if not git.is_dir():
        return True, "not a git checkout"
    for h in ("pre-commit", "pre-push"):
        a, b = TOOLS / "hooks" / h, git / "hooks" / h
        if not b.is_file() or a.read_bytes() != b.read_bytes():
            return False, f"{h} not installed: run tools/install-hooks.sh"
    return True, "installed"


def verify(as_json: bool = False) -> bool:
    spec = load_tests()
    floor = float(spec.get("recall_at_5_floor", RECALL5_FLOOR))
    results, hit5, n5 = [], 0, 0
    for t in spec["goldens"]:
        hits = search(t["query"], k=t.get("k", 5), mode=t.get("mode", "hybrid"))
        paths = [h["path"] for h in hits]
        ok, why = True, ""
        if t.get("expect_empty"):
            ok, why = not hits, f"got {paths[:3]}"
        if "expect_path" in t:
            n5 += 1
            rank = paths.index(t["expect_path"]) + 1 if t["expect_path"] in paths else None
            hit5 += bool(rank and rank <= 5)
            ok = bool(rank and rank <= t.get("max_rank", 5))
            why = f"rank={rank}"
        if t.get("reject_path") and any(p.startswith(t["reject_path"]) for p in paths):
            ok, why = False, f"rejected path present: {paths}"
        results.append({"id": t["id"], "ok": ok, "why": why})
    recall = hit5 / n5 if n5 else 1.0
    conn = connect()
    fr = freshness(last_index_ts=meta(conn, "last_index_ts"))
    st_ok, st_errs = status_check(VAULT, canon_files(), superseded())
    checks = {"status_check": (st_ok, f"{len(canon_files())} canon notes" + ("" if st_ok else ": " + "; ".join(st_errs[:5]))),
              "status_fixture": status_fixture(), "authority_fixture": authority_fixture(), "freshness_fixture": freshness_fixture(), "hooks": hooks_installed()}
    if VAULT == TOOLS.parent:  # sample-vault features; other stores skip this
        checks["feature_fixture"] = feature_fixture()
    ok = all(r["ok"] for r in results) and recall >= floor and fr["level"] != "red" and all(c[0] for c in checks.values())
    if as_json:
        print(json.dumps({"ok": ok, "recall_at_5": recall, "results": results, "freshness": fr,
                          "checks": {k: {"ok": a, "reason": b} for k, (a, b) in checks.items()}}, indent=2))
        return ok
    for r in results:
        print(f"{r['id']}: {'PASS' if r['ok'] else 'FAIL ' + r['why']}")
    for k, (a, b) in checks.items():
        print(f"{k}: {'PASS' if a else 'FAIL'} {b}")
    print(f"passed: {sum(r['ok'] for r in results)}  failed: {sum(not r['ok'] for r in results)}")
    print(f"recall@5: {recall:.3f} floor {floor} {'PASS' if recall >= floor else 'FAIL'}")
    print(f"freshness: {fr['level'].upper()} {'; '.join(fr['red'] + fr['yellow'])}")
    for d in fr["revisit_due"]:
        print(f"  revisit due: {d['path']} ({d['revisit']})")
    print(f"verify: {'GREEN' if ok and fr['level'] == 'green' else 'YELLOW' if ok else 'RED'}")
    return ok


def status() -> dict:
    conn = connect()
    fr = freshness(last_index_ts=meta(conn, "last_index_ts"))
    s = {"notes": conn.execute("SELECT count(*) FROM notes").fetchone()[0],
         "chunks": conn.execute("SELECT count(*) FROM chunks").fetchone()[0],
         "last_index_ts": meta(conn, "last_index_ts"), "freshness": fr,
         "inbox_pending": len(list((VAULT / "inbox").glob("*.md"))) if (VAULT / "inbox").is_dir() else 0}
    (TOOLS / "status.json").write_text(json.dumps(s, indent=2))
    return s


# ---------------------------------------------------------------- flush

def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(VAULT), *args], capture_output=True, text=True)


def flush(message: str, push: bool = True) -> int:
    """Once per batch: ingest only what changed, verify, commit, push. No-op when nothing changed."""
    conn = connect()
    li = meta(conn, "last_index_ts")
    li_ts = datetime.fromisoformat(li).timestamp() if li else 0
    stale = [p for p in canon_files() + sorted((VAULT / "log").glob("*.jsonl")) if p.stat().st_mtime > li_ts]
    dirty = git("status", "--porcelain").stdout.strip() if (VAULT / ".git").is_dir() else ""
    if not stale and not dirty and li:
        print("flush: nothing changed (no-op)")
        return 0
    if stale or not li:
        print(f"flush: ingest {ingest()}")
    if not verify():
        print("flush: verify RED; refusing to commit")
        return 1
    status()
    if (VAULT / ".git").is_dir():
        git("add", "-A")
        c = git("commit", "-m", message)
        if c.returncode != 0 and "nothing to commit" not in c.stdout:
            print("flush: git commit failed (set git user.name/user.email?):\n" + c.stdout + c.stderr)
            return 1
        if push and git("remote").stdout.strip():
            p = git("push")
            if p.returncode:
                print(p.stderr)
                return 1
        print(f"flush ok head={git('rev-parse', '--short', 'HEAD').stdout.strip()}")
    return 0


# ---------------------------------------------------------------- cli

def set_root(root: str | None, tests: str | None, dirs: str | None) -> None:
    """Point the engine at another store. Each store keeps its own index and goldens."""
    global VAULT, INDEX_DIR, DB_PATH, TESTS, CANON_DIRS
    if root:
        VAULT = Path(root).resolve()
        INDEX_DIR = VAULT / ".index"
        DB_PATH = INDEX_DIR / "brain.db"
        TESTS = VAULT / "retrieval_tests.yaml"
        if not TESTS.exists():
            TESTS = VAULT / "tools" / "retrieval_tests.yaml"
    if tests:
        TESTS = Path(tests).resolve()
    if dirs:
        CANON_DIRS = tuple(d for d in dirs.split(",") if d)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", help="store to operate on (default: this repo, or $BRAIN_VAULT)")
    ap.add_argument("--tests", help="goldens file (default: <root>/retrieval_tests.yaml or <root>/tools/...)")
    ap.add_argument("--dirs", help="comma-separated content dirs to index (default: decisions,people,projects)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("ingest"); g.add_argument("--full", action="store_true")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--k", type=int, default=5)
    s.add_argument("--mode", choices=["hybrid", "lexical", "semantic"], default="hybrid")
    c = sub.add_parser("compile"); c.add_argument("entity")
    v = sub.add_parser("verify"); v.add_argument("--json", action="store_true")
    sub.add_parser("status")
    an = sub.add_parser("answer"); an.add_argument("query")
    an.add_argument("--spans", action="store_true", help="print verified candidate lines for the agent's check")
    w = sub.add_parser("why"); w.add_argument("query")
    pr = sub.add_parser("propose"); pr.add_argument("text"); pr.add_argument("--from-agent", required=True)
    pr.add_argument("--source", required=True)
    f = sub.add_parser("flush"); f.add_argument("-m", default="flush"); f.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    set_root(a.root, a.tests, a.dirs)
    if a.cmd == "ingest":
        print(json.dumps(ingest(a.full)))
    elif a.cmd == "search":
        for i, h in enumerate(search(a.query, a.k, a.mode), 1):
            print(f"[{i}] {h['score']:.4f} {h['path']} :: {h['heading']}")
    elif a.cmd == "compile":
        print(format_compile(compile_entity(a.entity)))
    elif a.cmd == "verify":
        return 0 if verify(a.json) else 1
    elif a.cmd == "answer":
        from cite import cited_answer
        r = cited_answer(a.query)
        print(r["answer"])
        if r.get("citation"):
            print(f"  quote: {r['citation']} (verified in file)")
        for s_ in r["sources"]:
            print(f"  source: {s_}")
        for c in r["candidates"] if a.spans else []:
            print(f'  candidate: {c["path"]}:{c["line"]} "{c["quote"]}" (in file; coverage {c["coverage"]})')
        return 0 if r["known"] else 2
    elif a.cmd == "why":
        print(json.dumps(why(a.query), indent=2))
    elif a.cmd == "propose":
        print(propose(a.text, a.from_agent, a.source))
    elif a.cmd == "status":
        print(json.dumps(status(), indent=2))
    elif a.cmd == "flush":
        return flush(a.m, not a.no_push)
    return 0


if __name__ == "__main__":
    sys.exit(main())
