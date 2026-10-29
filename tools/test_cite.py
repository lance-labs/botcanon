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
    for ask in ("bakery closes Mondays", "opening hours"):  # BC-17: the real leak property, at answer level
        _, lq = answer(v, ask)
        check(f"never cites log/ or inbox/: {ask}", "log/" not in lq and "inbox/" not in lq, lq)
    check("opening hours quotes the Decision line", known and "2026-03-01-opening-hours.md:8" in q and "Decision:" in q, q)
    for ask in ("what are the opening hours", "when does the bakery open", "how much is a sourdough loaf"):
        _, q = answer(v, ask)
        check(f"never quotes metadata: {ask}", not any(f"- {m}:" in q for m in ("Date", "Owner", "From", "Source", "Prior", "Revisit")), q)
    # BC-03: the replaced winter hours are labelled and never quoted as the answer.
    r = run(v, "answer", "8 AM to 2 PM Wednesday to Sunday")
    check("superseded source labelled", "2026-01-10-opening-hours.md (superseded: not current)" in r.stdout, r.stdout[-300:])
    check("superseded line never quoted", "2026-01-10-opening-hours.md:" not in r.stdout)
    for ask in ("what is the capital of Peru", "what is the employee dental plan"):
        known, q = answer(v, ask)
        check(f"I don't know: {ask}", not known, q)
    # BC-01 gap: a question with no rare terms must not be answered by a line sharing only one common word
    known, q = answer(v, "when does the bakery open")
    check("'when does the bakery open' never quotes a bakery-only line",
          not known or "2026-03-01-opening-hours.md:" in q, q)
    # A fact added above the answer must not win just by coming first in the note (title fills in for both)
    pricing = v / "decisions" / "2026-02-01-pricing.md"
    orig = pricing.read_text()
    lines = orig.splitlines(keepends=True)
    at = next(i for i, l in enumerate(lines) if "Price sourdough" in l)
    pricing.write_text("".join(lines[:at] + ["- Added later: the shop cat is called Biscuit.\n"] + lines[at:]))
    run(v, "ingest")
    known, q = answer(v, "Bread pricing")
    check("inserted fact above the answer: 'Bread pricing' still quotes the price line",
          known and f"2026-02-01-pricing.md:{at + 2}" in q and "Price sourdough" in q, q)
    pricing.write_text(orig)
    run(v, "ingest")
    # Owner-attribute weak spot: the person's name comes from the note title and "number" must not ride on "phone"
    dana = v / "people" / "dana-okafor.md"
    dorig = dana.read_text()
    dana.write_text(dorig + "- Prefers phone.\n")
    run(v, "ingest")
    known, q = answer(v, "what is Dana Okafor's passport number")
    check("passport number with a 'Prefers phone.' line: I don't know", not known, q)
    dana.write_text(dorig)
    run(v, "ingest")


    # Tiny vault: every word is "common" (1 of 3 notes > 25%). Must not cite a Date line.
    t = Path(td) / "tiny"
    (t / "decisions").mkdir(parents=True)
    for n, (title, dec) in enumerate([("Parking", "Park behind the shop."), ("Coffee", "Use the Lisbon roaster."),
                                      ("Holidays", "Close the last week of August.")]):
        (t / "decisions" / f"2026-0{n+1}-01-{title.lower()}.md").write_text(
            f"# Decision: {title}\n\n- Status: approved\n- Date: 2026-0{n+1}-01\n- Decision: {dec}\n")
    (t / "decisions" / "2026-04-01-parking.md").write_text(
        "# Decision: Parking\n\n- Status: approved\n- Date: 2026-04-01\n- Decision: Park on Elm Street.\n"
        "- Prior: decisions/2026-01-01-parking.md\n")
    p0 = t / "decisions" / "2026-01-01-parking.md"
    p0.write_text(p0.read_text().replace("Status: approved", "Status: superseded"))
    run(t, "ingest")
    r = run(t, "answer", "park behind the shop")
    check("only-superseded match never quoted", "2026-01-01-parking.md:" not in r.stdout, r.stdout[-300:])
    for ask in ("where do we park", "which coffee roaster", "parking coffee holidays"):
        _, q = answer(t, ask)
        check(f"tiny vault never cites Date: {ask}", "- Date:" not in q, q)

# BC-09: compile picks by Date, not filename; a bad log line is reported, not fatal.
with tempfile.TemporaryDirectory() as td:
    v = Path(td) / "vault"
    shutil.copytree(ROOT / "tests" / "fixtures" / "vault", v)
    (v / "decisions" / "zz-old-opening-hours.md").write_text(
        "# Decision: Opening hours (draft)\n\n- Status: approved\n- Date: 2025-12-01\n- Decision: Open daily.\n")
    with open(v / "log" / "2026-03.jsonl", "a") as f:
        f.write("{not json\n")
    r = run(v, "compile", "opening-hours")
    check("compile picks latest Date", r.returncode == 0 and "2026-03-01-opening-hours.md" in r.stdout and "Open daily" not in r.stdout.split("OUTRANKED")[0], r.stdout[:300] + r.stderr[-200:])
    run(v, "ingest")
    r = run(v, "verify")
    check("verify reports a bad log line", r.returncode != 0 and "2026-03.jsonl:" in r.stdout, r.stdout[-300:])
# BC-08: one process (like the MCP server) must see a status edit without restarting.
with tempfile.TemporaryDirectory() as td:
    v = Path(td) / "vault"
    shutil.copytree(ROOT / "tests" / "fixtures" / "vault", v)
    sys.path.insert(0, str(ROOT / "tools"))
    import brain  # noqa: E402
    brain.set_root(str(v), None, None)
    n = "people/ari-novak.md"
    before = brain.path_weight(n, set())
    import os, time
    f = v / n
    f.write_text(f.read_text().replace("Status: approved", "Status: superseded"))
    os.utime(f, (time.time() + 5, time.time() + 5))
    after = brain.path_weight(n, set())
    check("status edit seen in the same process", before == 1.0 and after == 0.1, f"{before} -> {after}")

# BC-13: same-second, same-text proposals both survive.
with tempfile.TemporaryDirectory() as td:
    import brain  # noqa: E402
    a = brain.propose("Flour price rises in May", "t", "test", Path(td))
    b = brain.propose("Flour price rises in May", "t", "test", Path(td))
    check("same-second proposals both kept", a != b and a.exists() and b.exists())

# Prior: lines may be prose naming several decisions in backticks (real-vault style)
sys.path.insert(0, str(ROOT / "tools"))
import brain  # noqa: E402
got = brain.prior_paths("- Prior: twice-daily window in `decisions/b.md` (and earlier in `decisions/a.md`).\n- Prior: decisions/c.md\n")
check("prose Prior: lines name every decision", got == ["decisions/b.md", "decisions/a.md", "decisions/c.md"], str(got))

# "On what date" needs a day in the fact itself: a month range or the provenance Date: does not count
import cite  # noqa: E402
brain.set_root(str(ROOT / "tests" / "fixtures" / "vault"), None, None)
c = {"quote": "- Was a Acme Corp Manager, Jan 2011-Jun 2015. Date: 2026-10-29. From: Jira.", "path": "decisions/2026-02-15-supplier.md", "line": 3}
check("what-date refuses month range + provenance date", cite.check_line("On what date did Alex start at Acme Corp?", c) is not None)
c2 = {"quote": "- Started at Acme Corp on Jan 10, 2011.", "path": "decisions/2026-02-15-supplier.md", "line": 3}
check("what-date accepts a day-level date", cite.DAY_RE.search(c2["quote"]) is not None)

# Context block: a cited line comes with its heading chain and the whole enclosing block, never alone
with tempfile.TemporaryDirectory() as td:
    (Path(td) / "projects").mkdir()
    (Path(td) / "projects" / "r.md").write_text("# League\n\n- Status: approved\n\n## Pitching\n\n### e\n- e. Pitch limits (may exceed to finish an at bat);\n- e › vi. 14U will not exceed 95 pitches.\n- e › viii. EXCEPTION: may finish the batter.\n\n### f\n- f. Once a pitcher leaves he may not return.\n")
    brain.set_root(td, None, None)
    cx = cite.context_for("projects/r.md", 9)
    texts = [b["text"] for b in cx["block"]]
    check("context has heading chain", cx["headings"] == ["League", "Pitching", "e"], str(cx["headings"]))
    check("context has parent condition and exception", any("Pitch limits" in t for t in texts) and any("EXCEPTION" in t for t in texts), str(texts))
    check("context stops at the next rule", not any("may not return" in t for t in texts) and not any("Status:" in t for t in texts), str(texts))
    brain.set_root(str(ROOT / "tests" / "fixtures" / "vault"), None, None)

# Scope-gate: a gated note answers only when the query names its scope, and then excludes ungated notes
with tempfile.TemporaryDirectory() as td:
    for d in ("projects", "decisions"):
        (Path(td) / d).mkdir()
    (Path(td) / "projects" / "lg.md").write_text("# Acme League\n\n- Status: approved\n- Scope-gate: \\bacme\\b\n\n## Pitching\n- Acme pitchers may throw 75 pitches per game.\n")
    (Path(td) / "decisions" / "hs.md").write_text("# State\n\n- Status: approved\n\n## Pitching\n- Varsity pitchers may throw 110 pitches per game.\n")
    run(Path(td), "ingest")
    _, q1 = answer(Path(td), "how many pitches per game may pitchers throw")
    _, q2 = answer(Path(td), "how many pitches per game may Acme pitchers throw")
    _, q3 = answer(Path(td), "how many pitches per game may Acme varsity pitchers throw")
    check("scope-gate hides gated note from unscoped query", "lg.md" not in q1 and "hs.md" in q1, q1)
    check("scope-gate serves gated note when named", "lg.md" in q2, q2)
    check("named scope excludes ungated notes", "hs.md" not in q3, q3)

# Age groups and numbers are identifiers: "9U"/"12U" are content words and only match exactly
check("2-char digit tokens are content words", cite._keep("9u") and cite._keep("46") and not cite._keep("in"))
check("12u does not cover a 10U line", cite.coverage({"12u": 1.0}, "10U: Base Path=60'") == 0.0)
check("12u covers the 12U line", cite.coverage({"12u": 1.0}, "12U: Base Path=70'") == 1.0)

print("test_cite:", "PASS" if not FAILS else f"FAIL {FAILS}")
sys.exit(1 if FAILS else 0)
