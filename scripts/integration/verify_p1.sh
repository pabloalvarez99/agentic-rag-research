#!/usr/bin/env bash
# Run this agent's opt-in checks against a real production-rag instance, on the free path.
#
# The POSIX twin of verify_p1.ps1, with the same three steps and the same
# cleanup rule:
#
#   1. Use an instance already answering /health at --base-url, if there is one.
#   2. Otherwise start production-rag's own documented demo stack by running its
#      scripts/demo_setup.sh. This repository does not know how to build, ingest
#      or configure that service, and a second copy of those steps here would be
#      a copy that rots.
#   3. Run tests/integration with the opt-in variables set.
#
# Cleanup is bounded by what this script started: a stack that was already
# running is left running; a stack this script started is stopped with
# `docker compose down`, which keeps the named Qdrant volume exactly as
# production-rag's docs describe. The last lines always say what is still
# running and how to remove it.
#
# Every request the tests send pins llm=fake, embedder=fake and rerank=off, so
# no billed provider can be reached even against a deployment that has keys
# configured. No credential is read, written or printed here; the provider-key
# probe reports only whether a value is present, never the value.
#
# Usage:
#   ./scripts/integration/verify_p1.sh
#   ./scripts/integration/verify_p1.sh --base-url http://127.0.0.1:8000 --keep-stack
#   PRODUCTION_RAG_PATH=/path/to/production-rag ./scripts/integration/verify_p1.sh

set -euo pipefail

BASE_URL="http://127.0.0.1:8000"
P1_PATH="${PRODUCTION_RAG_PATH:-}"
KEEP_STACK=0
START_TIMEOUT=300

while [ $# -gt 0 ]; do
    case "$1" in
        --base-url) BASE_URL="$2"; shift 2 ;;
        --p1-path) P1_PATH="$2"; shift 2 ;;
        --keep-stack) KEEP_STACK=1; shift ;;
        --start-timeout) START_TIMEOUT="$2"; shift 2 ;;
        -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

BASE_URL="${BASE_URL%/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STARTED_STACK=0
LIVE_RAN=0
RESOLVED_P1=""

health_ok() {
    curl --silent --show-error --fail --max-time 3 "$BASE_URL/health" >/dev/null 2>&1
}

resolve_p1() {
    local candidate="${P1_PATH:-$(dirname "$REPO_ROOT")/production-rag}"
    if [ -f "$candidate/docker-compose.yml" ] && [ -f "$candidate/scripts/demo_setup.sh" ]; then
        (cd "$candidate" && pwd)
        return 0
    fi
    cat >&2 <<EOF
No production-rag checkout found (looked in: $candidate).

Point at one and re-run, or start the stack yourself and pass its address:
  ./scripts/integration/verify_p1.sh --p1-path /path/to/production-rag
  PRODUCTION_RAG_PATH=/path/to/production-rag ./scripts/integration/verify_p1.sh
EOF
    return 1
}

cleanup() {
    echo
    echo "== cleanup =="
    if [ "$STARTED_STACK" -eq 0 ]; then
        echo "nothing to clean up: this script did not start the instance at $BASE_URL, so it left it alone."
    elif [ "$KEEP_STACK" -eq 1 ]; then
        echo "--keep-stack: the demo stack this script started is still running."
        echo "  stop it with:  docker compose down       (in the production-rag checkout; keeps the vector index)"
        echo "  and with:      docker compose down -v    (also drops the production-rag-qdrant-storage volume)"
    else
        echo "stopping the demo stack this script started (the named Qdrant volume is kept, as production-rag's docs describe)."
        (cd "$RESOLVED_P1" && docker compose down) || true
        echo "removed: containers production-rag-api and production-rag-qdrant, network production-rag-net."
        echo "kept:    volume production-rag-qdrant-storage and image production-rag-api:local."
        echo "         remove them with 'docker compose down -v' and 'docker image rm production-rag-api:local'."
    fi
    if [ "$LIVE_RAN" -eq 1 ]; then
        echo "live E2E actually ran: yes"
    else
        echo "live E2E actually ran: no"
    fi
}
trap cleanup EXIT

echo "== production-rag live verification =="
echo "target: $BASE_URL"

if health_ok; then
    echo "found an instance already answering /health; this script will not start or stop anything."
else
    echo "no instance at $BASE_URL; starting production-rag's documented demo stack."
    command -v docker >/dev/null 2>&1 || {
        echo "docker is required to start the demo stack, and none is installed. Start production-rag elsewhere and pass --base-url." >&2
        exit 1
    }
    RESOLVED_P1="$(resolve_p1)"
    echo "using checkout: $RESOLVED_P1"

    # The demo stack must not be able to place a billed call, whatever this shell
    # happens to have exported. Compose still reads production-rag's own .env if
    # it has one; that is its configuration, not this lane's, and the probe below
    # reports it without failing.
    (cd "$RESOLVED_P1" && OPENAI_API_KEY="" COHERE_API_KEY="" ./scripts/demo_setup.sh)
    STARTED_STACK=1

    deadline=$(( $(date +%s) + START_TIMEOUT ))
    until health_ok; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo "the stack started but $BASE_URL/health did not answer within ${START_TIMEOUT}s." >&2
            exit 1
        fi
        sleep 3
    done
    echo "stack is up."
fi

# Evidence, not a gate: a key present in the service's environment is the
# operator's business. What matters for this lane is that every request it sends
# pins the free providers, which tests/integration asserts per request.
if [ "$STARTED_STACK" -eq 1 ]; then
    probe="$(cd "$RESOLVED_P1" && docker compose exec -T api python -c \
        "import os; print(int(bool(os.environ.get('OPENAI_API_KEY'))), int(bool(os.environ.get('COHERE_API_KEY'))))" 2>/dev/null || true)"
    if [ -n "$probe" ]; then
        echo "provider keys present in the API container (openai, cohere): $probe  [1 = a value is set; the value itself is never read or printed]"
    fi
fi

curl --silent --show-error --fail --max-time 5 "$BASE_URL/health"
echo

PYTHON="$REPO_ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

echo
echo "== tests/integration =="
set +e
(
    cd "$REPO_ROOT"
    RUN_P1_INTEGRATION=1 PRODUCTION_RAG_URL="$BASE_URL" "$PYTHON" -m pytest tests/integration -v
)
test_exit=$?
set -e
# Set before the exit check: "the live tests ran and failed" and "the live tests
# never ran" are different outcomes, and the cleanup summary has to tell them
# apart even when this script is about to exit non-zero.
LIVE_RAN=1
if [ "$test_exit" -ne 0 ]; then
    echo "tests/integration failed with exit code $test_exit." >&2
    exit "$test_exit"
fi
echo
echo "live free-path E2E: PASSED against $BASE_URL"
