#!/usr/bin/env bash
set -euo pipefail
mkdir -p "${CONFIG_DIR:-/config}/logs"
git config --global --add safe.directory '*'
git config --global advice.detachedHead false
exec python3 -u /app/webui/app.py
