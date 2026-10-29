#!/usr/bin/env python3
"""An incremental re-index must rank exactly like a full rebuild.

On a temp copy of the TEST FIXTURE: build the index, edit one note, delete another, force a few
unchanged notes back through the update path, and re-index incrementally. Then rebuild the same
files from scratch in a second store and compare top-10 results for every query in the fixture's
test sets, in lexical, semantic and hybrid mode. Stale BM25 statistics or rowid-dependent ties
show up as a difference here.
"""
import os, shutil, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import brain  # noqa: E402

K = 10


def queries(v: Path) -> list[str]:
    qs = []
    for f in (v / "retrieval_tests.yaml", v / "evals" / "public_set.yaml"):
        if f.is_file():
            spec = yaml.safe_load(f.read_text()) or {}
            qs += [t["query"] for t in (spec.get("goldens") or spec.get("cases") or []) if t.get("query")]
    return list(dict.fromkeys(qs))


def topk(v: Path, qs: list[str]) -> dict:
    brain.set_root(str(v), None, None)
    brain._STATUS.clear()
    return {(m, q): [(h["path"], h["heading"]) for h in brain.search(q, K, m)] for q in qs for m in ("lexical", "semantic", "hybrid")}


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "incr"
        shutil.copytree(ROOT / "tests" / "fixtures" / "vault", a, ignore=shutil.ignore_patterns(".index"))
        qs = queries(a)
        brain.set_root(str(a), None, None)
        brain.ingest(full=True)
        notes = [brain.rel(p) for p in brain.canon_files()]
        edit, gone = next(n for n in notes if n.startswith("projects/")), next(n for n in notes if n.startswith("people/"))
        p = a / edit
        p.write_text(p.read_text() + "\n- Note added in the incremental test: delivery van booked for Fridays.\n")
        (a / gone).unlink()
        conn = brain.connect()
        touched = [n for n in notes if n not in (edit, gone)][:3]
        conn.executemany("UPDATE notes SET sha='stale' WHERE path=?", [(n,) for n in touched])
        conn.commit()
        r = brain.ingest()
        if r["full"] or r["removed"] != 1:
            print(f"test_incremental: FAIL expected an incremental run with 1 removal, got {r}")
            return 1
        incr = topk(a, qs)
        b = Path(d) / "full"
        shutil.copytree(a, b, ignore=shutil.ignore_patterns(".index"))
        brain.set_root(str(b), None, None)
        brain.ingest(full=True)
        full = topk(b, qs)
    diffs = [k for k in full if full[k] != incr[k]]
    for m, q in diffs[:5]:
        print(f"DIFF [{m}] {q}\n  full: {[x for x, _ in full[(m, q)]]}\n  incr: {[x for x, _ in incr[(m, q)]]}")
    print(f"touched: edited {edit}, deleted {gone}, re-indexed {len(touched)} unchanged")
    print(f"test_incremental: {'PASS' if not diffs else 'FAIL'} ({len(full) - len(diffs)}/{len(full)} query-mode pairs identical top-{K})")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
