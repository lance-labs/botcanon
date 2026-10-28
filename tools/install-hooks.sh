#!/bin/sh
# Install the secret-scanning git hooks. Run once after every clone.
set -e
cd "$(dirname "$0")/.."
for h in pre-commit pre-push; do cp "tools/hooks/$h" ".git/hooks/$h"; chmod +x ".git/hooks/$h"; done
command -v gitleaks >/dev/null 2>&1 || echo "warning: install gitleaks (https://github.com/gitleaks/gitleaks); hooks block commits without it" >&2
echo "hooks installed"
