#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

question="${1:-What does hybrid retrieval buy over dense retrieval alone?}"
python_bin=".venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
  python3 -m venv .venv
fi

"$python_bin" -m pip install -e ".[dev]"

export OPENAI_API_KEY=""
export COHERE_API_KEY=""
export PRODUCTION_RAG_URL=""

result="$("$python_bin" -m agentic_rag.research \
  --question "$question" \
  --retriever fake \
  --quiet)"

printf '%s\n' "$result" | "$python_bin" -c '
import json
import sys

payload = json.load(sys.stdin)
print(json.dumps({
    "status": payload["status"],
    "steps_used": payload["steps_used"],
    "citations": len(payload["citations"]),
    "request_id": payload["request_id"],
}, separators=(",", ":")))
'
