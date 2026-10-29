#!/usr/bin/env python3
"""evals init/accept on a temp copy of the TEST FIXTURE: proposals cite real lines, accept promotes, verify uses them."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


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
        b("evals", "init")
        prop = v / "evals" / "proposed_tests.yaml"
        gs = (yaml.safe_load(prop.read_text()) or {}).get("goldens", []) if prop.exists() else []
        answerable = [g for g in gs if "expect_path" in g]
        idk = [g for g in gs if g.get("expect_known") is False]
        if len(answerable) < 10 or len(idk) < 3:
            errs.append(f"too few proposals: {len(answerable)} answerable, {len(idk)} idk")
        for g in answerable:  # every quote must be the exact line at that path:line
            path, rest = g["quote"].split(":", 1)
            n, line = rest.split(" ", 1)
            if path != g["expect_path"] or (v / path).read_text().splitlines()[int(n) - 1].strip() != line:
                errs.append(f"bad quote {g['id']}: {g['quote']}")
        b("evals", "accept")
        tests = v / "evals" / "retrieval_tests.yaml"
        if prop.exists() or not tests.exists():
            errs.append("accept should move proposed_tests.yaml into evals/retrieval_tests.yaml")
        r = b("verify")
        if f"passed: " not in r.stdout or "no evals" in r.stdout or "evals: none" in r.stdout:
            errs.append(f"verify should run the accepted tests: {r.stdout[-300:]}")
        print(r.stdout.strip().splitlines()[-4] if r.stdout.strip() else "", file=sys.stderr)
    print("test_evals: " + ("PASS" if not errs else "FAIL\n  " + "\n  ".join(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
