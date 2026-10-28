#!/usr/bin/env python3
"""Benchmark: plain embeddings (baseline) vs lexical vs this repo's hybrid, on evals/public_set.yaml.

Writes the results table into README.md between the BENCH markers. Re-run after any retrieval change:
    python3 tools/bench.py [--set evals/public_set.yaml] [--no-readme]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain  # noqa: E402


def plain_embeddings(q: str, k: int = 5) -> list[str]:
    """Baseline: cosine over chunk embeddings, top notes, no threshold, no ranking rules."""
    conn = brain.connect()
    rows = conn.execute("SELECT path, emb FROM chunks").fetchall()
    m = np.stack([np.frombuffer(r["emb"], dtype=np.float32) for r in rows])
    s = m @ brain.EMB.embed([q], query=True)[0]
    out: list[str] = []
    for i in np.argsort(-s):
        if rows[i]["path"] not in out:
            out.append(rows[i]["path"])
        if len(out) == k:
            break
    return out


SYSTEMS = {
    "plain embeddings (baseline)": plain_embeddings,
    "lexical FTS5 only": lambda q: [h["path"] for h in brain.search(q, 5, "lexical")],
    "hybrid (this repo)": lambda q: [h["path"] for h in brain.search(q, 5, "hybrid")],
    "hybrid + answer gate": lambda q: brain.answer(q)["sources"],
}


def score(fn, qs) -> dict:
    h1 = h5 = rr = na = 0
    pos = [x for x in qs if "expect_path" in x]
    neg = [x for x in qs if x.get("expect_empty")]
    for x in pos:
        r = fn(x["q"])
        if x["expect_path"] in r:
            i = r.index(x["expect_path"]) + 1
            h1 += i == 1
            h5 += i <= 5
            rr += 1 / i
    for x in neg:
        na += not fn(x["q"])
    return {"hit@1": h1 / len(pos), "hit@5": h5 / len(pos), "mrr": rr / len(pos),
            "no_answer": na / len(neg) if neg else 1.0, "n_pos": len(pos), "n_neg": len(neg)}


def table(results: dict) -> str:
    n = next(iter(results.values()))
    lines = [f"Public set: {n['n_pos']} answerable + {n['n_neg']} no-answer questions (`evals/public_set.yaml`).", "",
             "| System | Hit@1 | Hit@5 | MRR | No-answer correct |", "|---|---:|---:|---:|---:|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r['hit@1']:.2f} | {r['hit@5']:.2f} | {r['mrr']:.2f} | {r['no_answer']:.2f} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(brain.VAULT / "evals" / "public_set.yaml"))
    ap.add_argument("--no-readme", action="store_true")
    a = ap.parse_args()
    qs = yaml.safe_load(Path(a.set).read_text())["questions"]
    brain.ingest()
    t = table({name: score(fn, qs) for name, fn in SYSTEMS.items()})
    print(t)
    readme = brain.VAULT / "README.md"
    if not a.no_readme and readme.exists():
        s = readme.read_text()
        new = re.sub(r"(<!-- BENCH:START -->\n).*?(<!-- BENCH:END -->)", lambda m: m.group(1) + t + "\n" + m.group(2), s, flags=re.S)
        readme.write_text(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
