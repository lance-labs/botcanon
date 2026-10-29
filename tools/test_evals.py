#!/usr/bin/env python3
"""evals init/accept on a temp copy of the TEST FIXTURE.

Checks: proposals point at real lines and current notes only, don't leak the answer's words, carry no copied
text by default; accept refuses unreviewed or placeholder tests; flush never commits proposals;
verify goes RED on an empty or unknown-key tests file and reads legacy `cases:`.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from evals_gen import REWRITE, _words, clean_title  # noqa: E402


def main() -> int:
    errs = []
    with tempfile.TemporaryDirectory() as d:
        v = Path(d) / "vault"
        shutil.copytree(ROOT / "tests" / "fixtures" / "vault", v, ignore=shutil.ignore_patterns(".index", "retrieval_tests.yaml"))
        b = lambda *a: subprocess.run([sys.executable, str(ROOT / "tools/brain.py"), "--root", str(v), *a],
                                      capture_output=True, text=True, env=os.environ)
        b("ingest")
        r = b("verify")
        if "evals init" not in r.stdout or r.returncode != 0:
            errs.append(f"verify without tests should say 'run evals init' and exit 0: {r.returncode} {r.stdout[-200:]}")

        # fix 5: flush never commits unreviewed proposals (even without a .gitignore in the store)
        g = lambda *a: subprocess.run(["git", "-C", str(v), *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@example.com"); g("config", "user.name", "t")
        for h in ("pre-commit", "pre-push"):
            shutil.copy(ROOT / "tools/hooks" / h, v / ".git/hooks" / h)
        b("evals", "init")
        prop = v / "evals" / "proposed_tests.yaml"
        r = b("flush", "-m", "t", "--no-push")
        tracked = g("ls-files").stdout.split()
        if r.returncode or not tracked or "evals/proposed_tests.yaml" in tracked:
            errs.append(f"flush must commit notes but not evals/proposed_tests.yaml: rc={r.returncode} {r.stdout[-200:]}")
        ign = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "evals/proposed_tests.yaml"])
        if ign.returncode:
            errs.append("evals/proposed_tests.yaml is not gitignored")

        gs = (yaml.safe_load(prop.read_text()) or {}).get("goldens", []) if prop.exists() else []
        answerable = [t for t in gs if "expect_path" in t]
        idk = [t for t in gs if t.get("expect_known") is False]
        if len(answerable) < 10 or len(idk) < 3:
            errs.append(f"too few proposals: {len(answerable)} answerable, {len(idk)} idk")
        sys.path.insert(0, str(ROOT / "tools"))
        import brain
        brain.set_root(str(v), None, None)
        sup = brain.superseded()
        if not sup:
            errs.append("fixture should contain a superseded decision")
        for t in gs:
            if t.get("reviewed") is not False:
                errs.append(f"{t['id']}: proposals must start reviewed: false")
        for t in answerable:
            path, n = t["source"].rsplit(":", 1)
            text = (v / path).read_text()
            line = text.splitlines()[int(n) - 1].strip()
            # fix 3: never a superseded note or the derived CURRENT.md
            if path in sup or path.endswith("CURRENT.md") or brain.read_status(text) == "superseded":
                errs.append(f"{t['id']}: targets superseded/derived note {path}")
            if path != t["expect_path"] or not line:
                errs.append(f"bad source {t['id']}: {t['source']}")
            # fix 5: no copied text by default
            if "quote" in t:
                errs.append(f"{t['id']}: quote copied without --quotes")
            # fix 2: the query must not carry the answer line's own words (beyond the note's topic)
            if not t["query"].startswith(REWRITE):
                title = set(_words(clean_title(brain.note_title(text, v / path))))
                leak = (set(_words(t["query"])) & set(_words(line))) - title
                if len(leak) > 1:
                    errs.append(f"{t['id']}: query leaks answer words {sorted(leak)}")
        # fix 2 unit: a free-text line becomes a REWRITE placeholder, a field line a template question
        from evals_gen import _question
        if not _question("Pricing", "- Croissants cost 4 dollars each", None, "x.md", 3).startswith(REWRITE):
            errs.append("free-text line should give a REWRITE: placeholder")
        if _question("Ari Novak (2026-01-02)", "- Last: 2026-03-01 call", "Last", "x.md", 3) != "when was the last contact with Ari Novak":
            errs.append("field template / title cleanup wrong")
        from evals_gen import _boilerplate
        stock = _boilerplate({"a.md": [(0, 3, "- Why: standing filter for jobs so we never re-derive it from chat", "Why")],
                              "b.md": [(0, 4, "- Why: standing filter for leads so we never re-derive it from chat", "Why"),
                                       (0, 5, "- Why: the oven fits the back room", "Why")]})
        if stock != {("a.md", 3), ("b.md", 4)}:
            errs.append(f"near-identical lines across notes should be skipped: {stock}")
        if not _question("Pricing", "- Compiler notes: use gcc 12 always", "Compiler notes", "x.md", 3).startswith(REWRITE):
            errs.append("an unknown field name should give a REWRITE: placeholder, not a template")

        # owner probes: --owner adds 'I don't know' tests about the owner, skipping topics the notes mention
        (v / "people" / "dana-okafor.md").write_text((v / "people" / "dana-okafor.md").read_text() + "\n- Dentist: Dr. Example, Main St.\n- Carpet replaced; petty cash checked.\n")
        b("evals", "init", "--owner", "Dana Okafor")
        ids = {t["id"]: t for t in yaml.safe_load(prop.read_text())["goldens"]}
        probes = [t for i, t in ids.items() if i.startswith("idk-owner-")]
        if len(probes) < 5 or any(t.get("expect_known") is not False or "Dana Okafor" not in t["query"] for t in probes):
            errs.append(f"--owner should add owner 'I don't know' probes: {sorted(ids)}")
        if "idk-owner-dentist" in ids:
            errs.append("a probe whose topic the notes mention (dentist) must be skipped")
        if "idk-owner-childhood-pet" not in ids:
            errs.append("'carpet'/'petty' must not count as the topic word 'pet' (whole words only)")
        g("checkout", "-q", "--", "people/dana-okafor.md")

        # fix 5: --quotes opt-in copies the exact line
        b("evals", "init", "--quotes")
        q = [t for t in yaml.safe_load(prop.read_text())["goldens"] if "expect_path" in t]
        for t in q:
            path, n = t["source"].rsplit(":", 1)
            if t.get("quote") != (v / path).read_text().splitlines()[int(n) - 1].strip():
                errs.append(f"--quotes: bad quote {t['id']}")

        # fix 1: accept refuses placeholders, then unreviewed tests; --all-reviewed or reviewed: true passes
        r = b("evals", "accept")
        if r.returncode == 0 or REWRITE not in r.stdout or not prop.exists():
            errs.append(f"accept must refuse REWRITE: placeholders: {r.returncode} {r.stdout}")
        spec = yaml.safe_load(prop.read_text())
        for t in spec["goldens"]:
            if t["query"].startswith(REWRITE):
                t["query"] = clean_title(brain.note_title((v / t["expect_path"]).read_text(), v / t["expect_path"]))
        prop.write_text(yaml.safe_dump(spec, sort_keys=False))
        r = b("evals", "accept")
        if r.returncode == 0 or "reviewed" not in r.stdout or not prop.exists():
            errs.append(f"accept must refuse unreviewed tests: {r.returncode} {r.stdout}")
        spec["goldens"][0]["reviewed"] = True
        prop.write_text(yaml.safe_dump(spec, sort_keys=False))
        r = b("evals", "accept")
        if r.returncode == 0:
            errs.append("accept must refuse when only some tests are reviewed")
        r = b("evals", "accept", "--all-reviewed")
        tests = v / "evals" / "retrieval_tests.yaml"
        if r.returncode or prop.exists() or not tests.exists():
            errs.append(f"accept --all-reviewed should move proposals into evals/retrieval_tests.yaml: {r.stdout}")
        elif any("reviewed" in t for t in yaml.safe_load(tests.read_text())["goldens"]):
            errs.append("accepted tests should not keep the reviewed flag")
        r = b("verify")
        if "passed: " not in r.stdout or "evals: none" in r.stdout:
            errs.append(f"verify should run the accepted tests: {r.stdout[-300:]}")
        acc = yaml.safe_load(tests.read_text())["goldens"]
        for t in (t for t in acc if "expect_path" in t):
            path, n = t["source"].rsplit(":", 1)
            if t.get("expect_quote") != brain.norm_line((v / path).read_text().splitlines()[int(n) - 1]):
                errs.append(f"{t['id']}: init must record expect_quote = the source line's normalized text")
        good_t = next(t for t in acc if "expect_path" in t and re.search(rf"^{re.escape(t['id'])}: PASS", r.stdout, re.M))
        keep = tests.read_text()

        def one(t: dict) -> subprocess.CompletedProcess:
            tests.write_text(yaml.safe_dump({"recall_at_5_floor": 0.0, "goldens": [t]}))
            b("ingest")
            return b("verify")
        # legacy expect_cite still read: a wrong expected line must FAIL even when retrieval ranks the note first
        legacy = {k: v_ for k, v_ in good_t.items() if k != "expect_quote"} | {"id": "wrong-cite", "expect_cite": good_t["expect_path"] + ":9999"}
        rb = one(legacy)
        if not re.search(r"^wrong-cite: FAIL .*cite=expected", rb.stdout, re.M) or rb.returncode == 0:
            errs.append(f"a legacy test whose answer doesn't quote expect_cite must fail: {rb.stdout[-300:]}")
        # BC-05 follow-up: a line inserted above the answer must not break the test; changing the answer must
        note = v / good_t["expect_path"]
        orig = note.read_text()
        lines = orig.splitlines(keepends=True)
        n = int(good_t["source"].rsplit(":", 1)[1])
        note.write_text("".join(lines[:n - 1] + ["\n"] + lines[n - 1:]))
        rb = one(good_t)
        if not re.search(rf"^{re.escape(good_t['id'])}: PASS", rb.stdout, re.M):
            errs.append(f"expect_quote must survive a line inserted above the answer: {[l for l in rb.stdout.splitlines() if good_t['id'] in l]}")
        changed = lines[n - 1].rstrip("\n") + " Changed on 2026-10-29.\n"
        note.write_text("".join(lines[:n - 1] + [changed] + lines[n:]))
        rb = one(good_t)
        if not re.search(rf"^{re.escape(good_t['id'])}: FAIL .*cite=expected", rb.stdout, re.M) or rb.returncode == 0:
            errs.append(f"expect_quote must fail when the answer line's text changes: {rb.stdout[-300:]}")
        note.write_text(orig)
        b("ingest")
        tests.write_text(keep)
        print(r.stdout.strip().splitlines()[-4] if r.stdout.strip() else "", file=sys.stderr)

        # fix 4: an empty or unknown-key tests file is RED and nonzero; legacy `cases:` is read
        good = yaml.safe_load(tests.read_text())
        for name, body in (("empty", {"recall_at_5_floor": 0.9, "goldens": []}),
                           ("unknown key", {"recall_at_5_floor": 0.9, "tests": good["goldens"]})):
            tests.write_text(yaml.safe_dump(body))
            r = b("verify")
            if r.returncode == 0 or "verify: RED" not in r.stdout or "tests_file: FAIL" not in r.stdout:
                errs.append(f"{name} tests file must be RED and nonzero: {r.returncode} {r.stdout[-200:]}")
        first = next(t for t in good["goldens"] if "expect_path" in t)
        legacy = good["goldens"] + [{"id": "legacy-reject-list", "query": "croissant price", "reject_path": ["inbox/", "log/"]},
                                    {"id": "any-of-list", "query": first["query"], "max_rank": first["max_rank"],
                                     "expect_path": ["people/nobody.md", first["expect_path"]]}]
        good["goldens"] = legacy
        tests.write_text(yaml.safe_dump({"recall_at_5_floor": 0.9, "cases": legacy}))
        r = b("verify")
        m = re.search(r"passed: (\d+)\s+failed: (\d+)", r.stdout)
        if not m or int(m.group(1)) + int(m.group(2)) != len(good["goldens"]) or "tests_file" in r.stdout:
            errs.append(f"legacy cases: should be read as goldens: {r.stdout[-200:]}")
        legacy_dir = v / "tools"
        legacy_dir.mkdir(exist_ok=True)
        shutil.move(str(tests), legacy_dir / "retrieval_tests.yaml")
        r2 = b("verify")
        if "using legacy tools/retrieval_tests.yaml" not in r2.stdout:
            errs.append("verify should point out a legacy tools/retrieval_tests.yaml")
        shutil.move(str(legacy_dir / "retrieval_tests.yaml"), tests)
        before = (ROOT / "tools" / "status.json").stat().st_mtime if (ROOT / "tools" / "status.json").exists() else None
        b("status")
        after = (ROOT / "tools" / "status.json").stat().st_mtime if (ROOT / "tools" / "status.json").exists() else None
        if not (v / ".index" / "status.json").is_file() or after != before:
            errs.append("status must write .index/status.json in the store, not into the engine's tools/")
        if not re.search(r"^any-of-list: PASS", r.stdout, re.M):
            errs.append("expect_path list: any listed note within max_rank should pass")
    print("test_evals: " + ("PASS" if not errs else "FAIL\n  " + "\n  ".join(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
