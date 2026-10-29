"""Explicit note status: proposed | approved | superseded.

Canon notes carry a `- Status: <value>` bullet; inbox notes carry `status: proposed` frontmatter.
Ranking reads the status and falls back to folder + Prior: when a note has none (old vaults).
verify (status_check) requires a valid status on every canon note and requires `superseded`
to match the decisions named on newer decisions' Prior: lines.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

VALID = ("proposed", "approved", "superseded")
STATUS_RE = re.compile(r"^(?:-\s*Status|status):\s*([A-Za-z]+)\s*$", re.MULTILINE)


def read_status(text: str) -> str | None:
    m = STATUS_RE.search(text)
    return m.group(1).lower() if m else None


def set_status(text: str, value: str) -> str:
    """Insert or replace the Status bullet (right under the H1)."""
    if STATUS_RE.search(text):
        return STATUS_RE.sub(f"- Status: {value}", text, count=1)
    lines = text.split("\n")
    i = next((n for n, l in enumerate(lines) if l.startswith("# ")), -1)
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j < len(lines) and lines[j].lstrip().startswith("- "):
        lines.insert(j, f"- Status: {value}")  # join the existing bullet block
    else:
        lines[i + 1:i + 1] = ["", f"- Status: {value}"]
    return "\n".join(lines)


def expected_status(rel: str, superseded: set[str]) -> str:
    if rel.startswith("inbox/"):
        return "proposed"
    return "superseded" if rel in superseded else "approved"


def status_check(vault: Path, canon: list[Path], superseded: set[str]) -> tuple[bool, list[str]]:
    errs = []
    for p in canon:
        rel = p.relative_to(vault).as_posix()
        st = read_status(p.read_text(encoding="utf-8", errors="replace"))
        if st not in VALID:
            errs.append(f"{rel}: missing or invalid status ({st}); add '- Status: approved' under the title, or run tools/migrate_status.py")
        elif st == "proposed":
            errs.append(f"{rel}: canon note cannot be proposed")
        elif (st == "superseded") != (rel in superseded):
            errs.append(f"{rel}: status {st} but Prior: lines say {'superseded' if rel in superseded else 'current'}; "
                        f"set '- Status: {'superseded' if rel in superseded else 'approved'}' or run tools/migrate_status.py")
    return not errs, errs


def status_fixture() -> tuple[bool, str]:
    """Behavior test on a throwaway vault: valid passes; missing, wrong, and orphan-superseded fail."""
    d = Path(tempfile.mkdtemp())
    try:
        (d / "decisions").mkdir()
        old, new = d / "decisions/old.md", d / "decisions/new.md"
        old.write_text("# Old\n\n- Status: superseded\n")
        new.write_text("# New\n\n- Status: approved\n- Prior: `decisions/old.md`\n")
        sup = {"decisions/old.md"}
        ok, e = status_check(d, [old, new], sup)
        if not ok:
            return False, f"valid vault failed: {e}"
        new.write_text("# New\n\n- Prior: `decisions/old.md`\n")
        if status_check(d, [old, new], sup)[0]:
            return False, "missing status passed"
        new.write_text("# New\n\n- Status: superseded\n")
        if status_check(d, [old, new], sup)[0]:
            return False, "superseded without a Prior: line passed"
        new.write_text("# New\n\n- Status: approved\n")
        if status_check(d, [old, new], set())[0]:
            return False, "superseded note with no newer Prior: passed"
        if read_status(set_status("# T\n\nbody\n", "approved")) != "approved":
            return False, "set_status round-trip"
        return True, "valid passes; missing, orphan, and mismatched superseded fail"
    finally:
        shutil.rmtree(d, ignore_errors=True)
