"""Scoped document frequency + fallback-only notes (Lance 2026-10-30 16:03 ET)."""
import os, sys, tempfile, importlib
from pathlib import Path
FAIL = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" :: {info}")); ok or FAIL.append(name)
with tempfile.TemporaryDirectory() as td:
    os.environ["BRAIN_VAULT"] = td
    sys.path.insert(0, str(Path(__file__).parent))
    import brain; importlib.reload(brain); import cite; importlib.reload(cite)
    brain.VAULT = Path(td).resolve()
    (Path(td) / "projects").mkdir(); (Path(td) / "decisions").mkdir()
    for i in range(4):  # generic rulebook: 'league' rare (1 of 4)
        (Path(td) / "decisions" / f"g{i}.md").write_text(f"# G{i}\n\n- Status: approved\n\n- Rule {i} about the {'league ' if i == 0 else ''}mound.\n")
    for i in range(6):  # fallback rulebook full of 'league'
        (Path(td) / "projects" / f"fb{i}.md").write_text(f"# FB{i}\n\n- Status: approved\n- Scope-fallback-only: true\n\n- The league mound height is {i} inches.\n")
    (Path(td) / "projects" / "lg.md").write_text("# Acme League: Rules\n\n- Status: approved\n- Scope-gate: \\bacme\\b\n- Scope-default: ^projects/fb\n\n- Acme plays 6 innings.\n")
    allp = {brain.rel(f) for f in brain.canon_files(brain.VAULT)}
    a = brain.apply_scope_gates("what is the league mound height?", allp)
    check("no-scope question never sees fallback-only notes", not any(p.startswith("projects/fb") for p in a), a)
    check("no-scope df counts only in-scope notes: 'league' stays rare", cite.term_weights("what is the league mound height?").get("league") == 1.0, cite.term_weights("what is the league mound height?"))
    brain.SCOPE_OVERRIDE = __import__("re").compile("^projects/fb")
    try:
        a2 = brain.apply_scope_gates("league mound height", allp)
        check("under its scope's default override, fallback-only notes are allowed", any(p.startswith("projects/fb") for p in a2), a2)
    finally:
        brain.SCOPE_OVERRIDE = None
    import subprocess
    B = [sys.executable, str(Path(__file__).parent / "brain.py"), "--root", td]
    subprocess.run(B + ["ingest"], capture_output=True, text=True)
    out = subprocess.run(B + ["answer", "Acme: what is the mound height?"], capture_output=True, text=True).stdout
    check("named scope silent -> falls back to fallback-only rulebook, labeled", "default applies" in out and "projects/fb" in out, out[:300])
    out = subprocess.run(B + ["answer", "what is the mound height?"], capture_output=True, text=True).stdout
    check("no-scope question does not cite fallback-only rulebook", "projects/fb" not in out, out[:300])

print("FAILED:", FAIL) if FAIL else print("all passed")
sys.exit(1 if FAIL else 0)
