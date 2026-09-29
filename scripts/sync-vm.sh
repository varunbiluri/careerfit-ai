#!/usr/bin/env bash
# Sync project tree to the capstone VM (rsync over SSH).
# Prereq: ssh with ~/Downloads/vm-dev.pem (or set SYNC_SSH_KEY).
#
# Usage:
#   ./scripts/sync-vm.sh
#   SYNC_SSH_KEY=~/other.pem SYNC_REMOTE='~/ai-job-market' ./scripts/sync-vm.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${SYNC_HOST:-20.84.92.101}"
USER="${SYNC_USER:-vignesh}"
REMOTE="${SYNC_REMOTE:-~/ai-job-market}"
KEY="${SYNC_SSH_KEY:-$HOME/Downloads/vm-dev.pem}"

echo "Syncing: $ROOT/ -> ${USER}@${HOST}:${REMOTE}/"
rsync -avz --delete \
  --exclude '.git/' \
  --exclude 'backend/.venv/' \
  --exclude 'frontend/node_modules/' \
  --exclude '**/__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  -e "ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  "$ROOT/" "${USER}@${HOST}:${REMOTE}/"

echo "Done. On the VM, reinstall backend deps and restart the API, e.g.:"
echo "  cd '$REMOTE/backend' && uv sync && sudo systemctl restart <your-api-service>"
