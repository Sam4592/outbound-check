#!/usr/bin/env bash
# Fetch the pinned version of kaymen99/sales-outreach-automation-langgraph and
# install only what the adapter needs (no Google, Airtable or LLM SDKs).
set -euo pipefail

DIR="${1:-.cache/targets/sales-outreach-automation-langgraph}"
COMMIT="2e2761ccc16c26fe20adf101b4ec702cd0876b15"

if [ ! -d "$DIR/.git" ]; then
  git clone --quiet https://github.com/kaymen99/sales-outreach-automation-langgraph "$DIR"
fi
git -C "$DIR" fetch --quiet --depth 1 origin "$COMMIT" 2>/dev/null || true
git -C "$DIR" checkout --quiet "$COMMIT"

pip install --quiet "langgraph==1.2.22" "langchain-core==1.8.2" "pydantic>=2" colorama python-dotenv beautifulsoup4 html2text requests

echo "Ready. Run:"
echo "  TARGET_DIR=$DIR outbound-check run --agent benchmarks/kaymen99/adapter.py:run --out results/kaymen99"
