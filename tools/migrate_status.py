#!/usr/bin/env python3
"""Idempotent: give every canon note an explicit Status from its folder and Prior: state.

    python3 tools/migrate_status.py [--check]      (BRAIN_VAULT / BRAIN_DIRS select another store)
canon -> approved; a decision named on a newer decision's Prior: line -> superseded. Inbox stays proposed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain  # noqa: E402
from note_status import expected_status, read_status, set_status  # noqa: E402


def main() -> int:
    check = "--check" in sys.argv
    sup = brain.superseded()
    changed = []
    for p in brain.canon_files():
        r = brain.rel(p)
        text = p.read_text()
        want = expected_status(r, sup)
        if read_status(text) != want:
            changed.append(f"{r} -> {want}")
            if not check:
                p.write_text(set_status(text, want))
    print("\n".join(changed) or "all notes already carry the right status")
    return 1 if (check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
