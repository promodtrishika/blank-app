#!/usr/bin/env bash
# Azure App Service startup command:  bash startup.sh
# Also works anywhere else Linux runs the portal.
set -euo pipefail
cd "$(dirname "$0")"

# Code runs from a temporary folder on App Service; anything that must
# survive a restart (the database, the SharePoint sync queue, the sign-in
# cookie secret) lives under /home.
if [ -n "${WEBSITE_SITE_NAME:-}" ]; then
  export RTPS_DATA_DIR="${RTPS_DATA_DIR:-/home/data/rtps}"
else
  export RTPS_DATA_DIR="${RTPS_DATA_DIR:-$PWD/.rtps_cache}"
fi
mkdir -p "$RTPS_DATA_DIR"
export RTPS_QAP_DB="${RTPS_QAP_DB:-$RTPS_DATA_DIR/rtps_qap.db}"
export RTPS_SP_CACHE_PATH="${RTPS_SP_CACHE_PATH:-$RTPS_DATA_DIR/sharepoint-cache.db}"

# The Python the build installed into.
if [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif [ -x antenv/bin/python ]; then PY=antenv/bin/python
else PY=python3
fi

"$PY" -m app.deploy_secrets

exec "$PY" -m streamlit run streamlit_app.py \
  --server.port "${PORT:-8000}" \
  --server.address 0.0.0.0 \
  --server.headless true
