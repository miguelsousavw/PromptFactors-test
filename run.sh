#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -m streamlit run "$ROOT_DIR/app.py" --server.headless true
