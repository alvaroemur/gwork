#!/usr/bin/env bash
# Git post-commit hook for gwork.
# Copy it to .git/hooks/post-commit in the target repository and make it executable.
# It warns when a commit changes files under .../clientes/*/Analisis/entregables/.
# It does not run sync; it only suggests `gwork sync plan`.

set -eu

changed="$(git diff --name-only HEAD~1 HEAD 2>/dev/null | \
  grep -E 'clientes/[^/]+/Analisis/entregables/' || true)"

if [ -n "$changed" ]; then
  clients="$(echo "$changed" | awk -F'/clientes/' '{print $2}' | awk -F'/' '{print $1}' | sort -u)"
  echo ""
  echo "⚠️  gwork: this commit changes deliverables. Consider running:"
  for c in $clients; do
    echo "    cd clientes/$c && gwork sync plan"
  done
  echo ""
fi
