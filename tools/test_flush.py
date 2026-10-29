#!/usr/bin/env python3
"""flush commits memory paths only, and pushes only when asked and the repo is not public.

On a temp git copy of the TEST FIXTURE (with a local bare repo as its remote):
- a changed note is committed; a stray file in the checkout is not, and is reported;
- plain `flush` does not push; `flush --push` does;
- `flush --push` refuses when GitHub reports the repo PUBLIC (a fake `gh` on PATH), unless --allow-public.
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = [sys.executable, str(ROOT / "tools" / "brain.py")]
FAILS = []


def sh(cwd, *a):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True)


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as td:
    v, bare = Path(td) / "vault", Path(td) / "remote.git"
    shutil.copytree(ROOT / "tests" / "fixtures" / "vault", v)
    sh(td, "git", "init", "-q", "--bare", str(bare))
    for c in (["init", "-q", "-b", "main"], ["config", "user.name", "test"], ["config", "user.email", "t@example.invalid"],
              ["remote", "add", "origin", str(bare)]):
        sh(v, "git", *c)
    for h in ("pre-commit", "pre-push"):
        shutil.copy(ROOT / "tools" / "hooks" / h, v / ".git" / "hooks" / h)
    (v / ".gitignore").write_text(".index/\n")
    sh(v, "git", "add", "-A"); sh(v, "git", "commit", "-qm", "init"); sh(v, "git", "push", "-q", "-u", "origin", "main")

    note = v / "people" / "ari-novak.md"
    note.write_text(note.read_text() + "- Closed on public holidays.\n")
    (v / "export-scratch.txt").write_text("not memory\n")
    r = subprocess.run(BRAIN + ["--root", str(v), "flush", "-m", "t1"], capture_output=True, text=True)
    files = sh(v, "git", "show", "--name-only", "--format=", "HEAD").stdout.split()
    check("flush exit 0", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
    check("changed note committed", "people/ari-novak.md" in files, str(files))
    check("stray file not committed", "export-scratch.txt" not in files and "?? export-scratch.txt" in sh(v, "git", "status", "--porcelain").stdout)
    check("stray file reported", "non-memory" in r.stdout)
    local, remote = sh(v, "git", "rev-parse", "HEAD").stdout, sh(bare, "git", "rev-parse", "main").stdout
    check("no push by default", local != remote)

    fake = Path(td) / "bin"; fake.mkdir()
    (fake / "gh").write_text("#!/bin/sh\necho PUBLIC\n"); (fake / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    note.write_text(note.read_text() + "- Prefers email.\n")
    r = subprocess.run(BRAIN + ["--root", str(v), "flush", "-m", "t2", "--push"], capture_output=True, text=True, env=env)
    local, remote = sh(v, "git", "rev-parse", "HEAD").stdout, sh(bare, "git", "rev-parse", "main").stdout
    check("public repo: push refused", r.returncode == 1 and local != remote and "PUBLIC" in r.stdout, r.stdout[-200:])
    note.write_text(note.read_text() + "- Prefers phone.\n")
    r = subprocess.run(BRAIN + ["--root", str(v), "flush", "-m", "t3", "--push", "--allow-public"], capture_output=True, text=True, env=env)
    local, remote = sh(v, "git", "rev-parse", "HEAD").stdout, sh(bare, "git", "rev-parse", "main").stdout
    check("--push --allow-public pushes", r.returncode == 0 and local == remote, r.stdout[-300:] + r.stderr[-300:])

print("test_flush:", "PASS" if not FAILS else f"FAIL {FAILS}")
sys.exit(1 if FAILS else 0)
