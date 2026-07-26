#!/usr/bin/env bash
# Redeploy the backend on the VM: pull the latest code and restart the service.
# Run from the repo root ON THE VM:  bash deploy/redeploy.sh
set -euo pipefail

git pull
sudo systemctl restart backend
sudo systemctl status backend --no-pager
