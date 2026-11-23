#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBMORPH_PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/.run"
SETUP=false
FRONTEND_PORT="${WEBMORPH_FRONTEND_PORT:-0}"
declare -a PIDS=()

if [[ "${1:-}" == "--setup" ]]; then SETUP=true; shift; fi
if [[ "$#" != 0 || ! "$FRONTEND_PORT" =~ ^(0|3000|3001)$ ]]; then
  printf 'Usage: WEBMORPH_FRONTEND_PORT=3000 bash start.sh [--setup]\n' >&2
  exit 2
fi
[[ -f "$ROOT/.env" ]] || cp "$ROOT/.env.example" "$ROOT/.env"
if [[ ! -x "$WEBMORPH_PYTHON" ]]; then
  python3 -c "import sys; assert sys.version_info >= (3, 11), 'Install Python 3.11 or newer'"
  python3 -m venv "$ROOT/.venv"
  SETUP=true
fi
if $SETUP || ! "$WEBMORPH_PYTHON" -c 'import fastapi, playwright, aiosqlite, pydantic_settings, openai, pypdf' 2>/dev/null; then
  "$WEBMORPH_PYTHON" -m pip install -r "$ROOT/backend/requirements.txt"
fi
"$WEBMORPH_PYTHON" -m playwright install chromium
if $SETUP || [[ ! -f "$ROOT/frontend/node_modules/next/dist/bin/next" ]]; then
  (cd "$ROOT/frontend" && npm ci)
fi

available() {
  "$WEBMORPH_PYTHON" -c 'import socket, sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$1" 2>/dev/null
}
if [[ "$FRONTEND_PORT" == 0 ]]; then
  if available 3000; then FRONTEND_PORT=3000; else FRONTEND_PORT=3001; fi
fi
for port in 8000 8001 "$FRONTEND_PORT"; do
  if ! available "$port"; then printf 'Port %s is unavailable.\n' "$port" >&2; exit 1; fi
done

cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$LOG_DIR"
(cd "$ROOT" && exec "$WEBMORPH_PYTHON" -m uvicorn demo_portal.app:app --host 127.0.0.1 --port 8001) >"$LOG_DIR/civicgrid.log" 2>&1 &
PIDS+=("$!")
(cd "$ROOT/backend" && exec "$WEBMORPH_PYTHON" -m app.main) >"$LOG_DIR/agent.log" 2>&1 &
PIDS+=("$!")
(cd "$ROOT/frontend" && exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port "$FRONTEND_PORT") >"$LOG_DIR/workspace.log" 2>&1 &
PIDS+=("$!")

healthy() {
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then printf 'A service exited. See %s.\n' "$LOG_DIR" >&2; exit 1; fi
  done
}
workspace="http://127.0.0.1:$FRONTEND_PORT"
for endpoint in http://127.0.0.1:8001 http://127.0.0.1:8000/api/health "$workspace"; do
  deadline=$((SECONDS + 75))
  until "$WEBMORPH_PYTHON" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=4).close()' "$endpoint" 2>/dev/null; do
    healthy
    if (( SECONDS > deadline )); then printf 'Service unavailable at %s. See %s.\n' "$endpoint" "$LOG_DIR" >&2; exit 1; fi
    sleep .4
  done
done
printf 'WebMorph is ready at %s\nCivicGrid is at http://localhost:8001. Press Ctrl+C to stop all services.\n' "$workspace"
while true; do healthy; sleep 1; done
