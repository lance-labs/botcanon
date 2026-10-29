#!/usr/bin/env python3
"""Cite-and-verify must quote the line that states the fact, or say "I don't know".

Regression for BC-01: a question whose words are all common in the vault ("what are the
opening hours") left no rare terms, every line then counted as covering it, and the answer
quoted "- Date: 2026-03-01" as verified. Runs on temp copies only.
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = [sys.executable, str(ROOT / "tools" / "brain.py")]
FAILS = []


def run(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(BRAIN + ["--root", str(root), *args], capture_output=True, text=True)


def answer(root: Path, q: str) -> tuple[bool, str]:
    r = run(root, "answer", q)
    quote = next((l for l in r.stdout.splitlines() if l.strip().startswith("quote:")), "")
    return r.returncode == 0, quote


def check(name: str, ok: bool, detail: str = ""):
    print(f"{'ok  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as td:
    v = Path(td) / "vault"
    shutil.copytree(ROOT / "tests" / "fixtures" / "vault", v)
    run(v, "ingest")
    known, q = answer(v, "what are the opening hours")
    check("opening hours quotes the Decision line", known and "2026-03-01-opening-hours.md:8" in q and "Decision:" in q, q)
    for ask in ("what are the opening hours", "when does the bakery open", "how much is a sourdough loaf"):
        _, q = answer(v, ask)
        check(f"never quotes metadata: {ask}", not any(f"- {m}:" in q for m in ("Date", "Owner", "From", "Source", "Prior", "Revisit")), q)
    for ask in ("what is the capital of Peru", "what is the employee dental plan"):
        known, q = answer(v, ask)
        check(f"I don't know: {ask}", not known, q)

    # Tiny vault: every word is "common" (1 of 3 notes > 25%). Must not cite a Date line.
    t = Path(td) / "tiny"
    (t / "decisions").mkdir(parents=True)
    for n, (title, dec) in enumerate([("Parking", "Park behind the shop."), ("Coffee", "Use the Lisbon roaster."),
                                      ("Holidays", "Close the last week of August.")]):
        (t / "decisions" / f"2026-0{n+1}-01-{title.lower()}.md").write_text(
            f"# Decision: {title}\n\n- Status: approved\n- Date: 2026-0{n+1}-01\n- Decision: {dec}\n")
    run(t, "ingest")
    for ask in ("where do we park", "which coffee roaster", "parking coffee holidays"):
        _, q = answer(t, ask)
        check(f"tiny vault never cites Date: {ask}", "- Date:" not in q, q)

print("test_cite:", "PASS" if not FAILS else f"FAIL {FAILS}")
sys.exit(1 if FAILS else 0)
