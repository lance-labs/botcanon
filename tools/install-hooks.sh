#!/bin/sh
# Install the secret-scanning git hooks. Run once after every clone.
set -e
cd "$(dirname "$0")/.."
d=$(git rev-parse --git-path hooks)  # works in a normal clone and in a git worktree
mkdir -p "$d"
for h in pre-commit pre-push; do cp "tools/hooks/$h" "$d/$h"; chmod +x "$d/$h"; done
command -v gitleaks >/dev/null 2>&1 || echo "warning: install gitleaks (https://github.com/gitleaks/gitleaks); hooks block commits without it" >&2
echo "hooks installed"
