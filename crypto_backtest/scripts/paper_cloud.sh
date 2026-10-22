#!/usr/bin/env bash
# Corrida diaria en la nube: restaura el estado desde la rama `paper-state`, corre
# `paper.py run` y guarda el estado/bitácora de vuelta en esa rama.
# Sin secretos: solo datos públicos y órdenes simuladas.
set -euo pipefail
cd "$(dirname "$0")/.."   # carpeta crypto_backtest
PYTHON="${PYTHON:-python}"
RAMA="paper-state"

git config user.name "paper-trading-bot"
git config user.email "paper-trading-bot@users.noreply.github.com"

# 1. Restaurar el estado (o crear la rama huérfana la primera vez)
if git ls-remote --exit-code --heads origin "$RAMA" >/dev/null 2>&1; then
  git fetch --quiet origin "+refs/heads/$RAMA:refs/remotes/origin/$RAMA"
  git worktree add -B "$RAMA" paper_state "origin/$RAMA"
else
  git worktree add --detach paper_state
  (cd paper_state && git checkout --orphan "$RAMA" && git rm -rfq . )
fi

# 2. Correr (un error de datos devuelve código 1 pero igual se guarda la bitácora)
set +e
"$PYTHON" paper.py run --dir paper_state
rc=$?
set -e

# 3. Guardar el estado si cambió
cd paper_state
git add -A
if ! git diff --cached --quiet; then
  git commit -q -m "paper: $(date -u +%F) ($( [ $rc -eq 0 ] && echo ok || echo error ))"
  git push --quiet origin "$RAMA"
fi
exit $rc
