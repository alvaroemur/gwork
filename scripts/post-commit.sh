#!/usr/bin/env bash
# Git post-commit hook para cowork-drivesync.
# Instalalo copiando a .git/hooks/post-commit en el repo de Cowork y dándole +x.
# Avisa cuando un commit toca archivos en .../clientes/*/Analisis/entregables/.
# No ejecuta sync; sólo recuerda correr `cowork sync plan`.

set -eu

changed="$(git diff --name-only HEAD~1 HEAD 2>/dev/null | \
  grep -E 'clientes/[^/]+/Analisis/entregables/' || true)"

if [ -n "$changed" ]; then
  clients="$(echo "$changed" | awk -F'/clientes/' '{print $2}' | awk -F'/' '{print $1}' | sort -u)"
  echo ""
  echo "⚠️  drivesync: el commit toca entregables. Considera correr:"
  for c in $clients; do
    echo "    cd clientes/$c && cowork sync plan"
  done
  echo ""
fi
