#!/usr/bin/env bash
# Redeploy the backend on the VM: fetch the deploy branch, reinstall dependencies
# only if they changed, restart the service, and verify it actually came up.
# If the health check fails, rolls the checkout back to the previous commit.
#
# On the VM, from anywhere:
#   bash ~/huaweitech4city/deploy/redeploy.sh
#   BRANCH=app-integration bash deploy/redeploy.sh    # deploy something else
#
# Also invoked over SSH by .github/workflows/deploy-vm.yml.
set -euo pipefail

BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"   # the SEA-LION model load takes ~30-60s
SERVICE="${SERVICE:-backend}"
REQ_FILES=(pipeline/requirements.txt backend/requirements.txt)
VENV_PIP="backend/.venv/bin/pip"

cd "$(dirname "$0")/.."                   # repo root, regardless of caller's cwd

log() { printf '\n=== %s\n' "$*"; }

# Blob hashes of the requirements files at the current HEAD. Cheaper and more
# reliable than diffing paths: catches the case where an earlier deploy failed
# part-way and the venv is out of sync with the checkout.
req_fingerprint() {
  local f
  for f in "${REQ_FILES[@]}"; do git rev-parse "HEAD:${f}" 2>/dev/null || echo missing; done
}

install_deps() {
  log "Installing dependencies into backend/.venv"
  # No --upgrade: torch is deliberately installed from the CPU-only index
  # (see notes/DEPLOYMENT_PLAN.md 1c) and must not be re-resolved from PyPI.
  "$VENV_PIP" install -r pipeline/requirements.txt -r backend/requirements.txt
}

wait_for_health() {
  local deadline=$(( SECONDS + HEALTH_TIMEOUT ))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "$HEALTH_URL" | grep -q '"ok"'; then return 0; fi
    sleep 3
  done
  return 1
}

# --- 1. Remember where we are so a bad deploy can be undone ------------------
PREVIOUS_SHA="$(git rev-parse HEAD)"
BEFORE_REQS="$(req_fingerprint)"

# --- 2. Move the checkout to the deploy branch, discarding local drift -------
# -f -B handles all three cases: clean fast-forward, locally-modified tracked
# files, and a VM still sitting on the branch it was originally cloned with.
# backend/.env and backend/.venv/ are gitignored, so nothing live is touched.
log "Fetching origin/${BRANCH}"
git fetch --prune origin "$BRANCH"
git checkout -f -B "$BRANCH" "origin/${BRANCH}"
log "Deploying ${PREVIOUS_SHA:0:8} -> $(git rev-parse --short HEAD)"

# --- 3. Dependencies, only when they actually moved -------------------------
AFTER_REQS="$(req_fingerprint)"
REQS_CHANGED=0
if [[ "$BEFORE_REQS" != "$AFTER_REQS" ]]; then
  REQS_CHANGED=1
  install_deps
else
  log "Requirements unchanged - skipping pip install"
fi

# --- 4. Restart and prove it came up ----------------------------------------
log "Restarting ${SERVICE}"
sudo systemctl restart "$SERVICE"

if wait_for_health; then
  log "Healthy at $(git rev-parse --short HEAD)"
  systemctl status "$SERVICE" --no-pager --lines=5
  exit 0
fi

# --- 5. Rollback ------------------------------------------------------------
log "HEALTH CHECK FAILED after ${HEALTH_TIMEOUT}s - rolling back to ${PREVIOUS_SHA:0:8}"
journalctl -u "$SERVICE" -n 60 --no-pager || true

git reset --hard "$PREVIOUS_SHA"
if (( REQS_CHANGED == 1 )); then install_deps; fi
sudo systemctl restart "$SERVICE"

if wait_for_health; then
  log "Rolled back to ${PREVIOUS_SHA:0:8} and healthy. The pushed commit is broken."
else
  log "ROLLBACK ALSO UNHEALTHY - the VM needs manual attention (SSH in, journalctl -u ${SERVICE})"
fi
exit 1
