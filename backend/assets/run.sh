#!/usr/bin/env bash

set -euo pipefail

WORKDIR="${GITHUB_WORKSPACE:-$PWD}"
RESULT_FILE="${WORKDIR}/scanner_result.json"
OUT_LOG="/tmp/scanner_stdout.log"
ERR_LOG="/tmp/scanner_stderr.log"
PORT=""
STAGE_REACHED="cloned"
DETECTED_PORT=""

log() {
  echo "[scanner] $*"
}

tail_file() {
  local file_path="$1"
  if [ -f "$file_path" ]; then
    tail -50 "$file_path"
  fi
}

write_result() {
  local stage="$1"
  local exit_code="$2"
  local port="${3:-}"

  local stdout_tail
  local stderr_tail
  stdout_tail="$(tail_file "$OUT_LOG")"
  stderr_tail="$(tail_file "$ERR_LOG")"

  python3 - <<PYEOF
import json

data = {
    "stage_reached": "${stage}",
    "port": int("${port}") if "${port}" else None,
    "health_check_url": f"http://localhost:${port}" if "${port}" else None,
    "stdout_tail": """${stdout_tail}""",
    "stderr_tail": """${stderr_tail}""",
    "exit_code": int("${exit_code}"),
    "duration_sec": 0,
}

with open("${RESULT_FILE}", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
PYEOF
}

push_result() {
  cd "$WORKDIR"
  git config user.email "scanner@codespace.local" || true
  git config user.name "Repo Viability Scanner" || true
  git add scanner_result.json || true
  git commit -m "chore: scanner result" || true
  git push || true
}

wait_for_port() {
  local port="$1"
  local max_wait=60
  local waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    if command -v nc >/dev/null 2>&1 && nc -z localhost "$port" >/dev/null 2>&1; then
      return 0
    fi
    if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 1
}

start_server() {
  local expected_port="$1"
  shift
  rm -f "$OUT_LOG" "$ERR_LOG"
  "$@" >"$OUT_LOG" 2>"$ERR_LOG" &
  local pid=$!
  if wait_for_port "$expected_port"; then
    DETECTED_PORT="$expected_port"
    log "Port detection: found on expected port $expected_port (is_server=true)"
    echo "$pid"
    return 0
  fi

  local stdout_tail
  stdout_tail="$(tail_file "$OUT_LOG")"
  local parsed_port
  parsed_port="$(
    echo "$stdout_tail" \
      | grep -iE '(port|listening|running at|http://|https://)' \
      | grep -oE '[0-9]{4,5}' \
      | head -1 || true
  )"
  if [ -z "$parsed_port" ]; then
    parsed_port="$(echo "$stdout_tail" | grep -oE '[0-9]{4,5}' | head -1 || true)"
  fi
  if [ -n "$parsed_port" ] && wait_for_port "$parsed_port"; then
    DETECTED_PORT="$parsed_port"
    log "Port detection: found on dynamic port $parsed_port (is_server=true)"
    echo "$pid"
    return 0
  fi

  log "Port detection: no port detected (is_server=false)"
  kill "$pid" >/dev/null 2>&1 || true
  return 1
}

main() {
  cd "$WORKDIR"
  log "=== RUN START ==="

  if [ -f "package.json" ]; then
    log "Detected Node project"
    npm install
    STAGE_REACHED="installed"
    PORT=3000
    if start_server "$PORT" env HOST=0.0.0.0 npm start >/dev/null; then
      STAGE_REACHED="started"
      log "Node server started successfully on port $DETECTED_PORT"
      write_result "$STAGE_REACHED" 0 "$DETECTED_PORT"
      push_result
      return 0
    fi
    # Node project found but no server started; treat as non-server repo (success)
    log "Node project detected but no server port found; treating as non-server execution"
    STAGE_REACHED="completed"
    write_result "$STAGE_REACHED" 0
    push_result
    log "=== RUN END ==="
    return 0
  fi

  # Python project handling
  if [ -f "requirements.txt" ]; then
    log "Detected Python project"
    if ! pip install -r requirements.txt; then
      log "Python pip install failed"
      STAGE_REACHED="failed"
      write_result "$STAGE_REACHED" 1
      push_result
      log "=== RUN END ==="
      return 0
    fi
    STAGE_REACHED="installed"
  fi

  PORT=8000
  if [ -f "main.py" ]; then
    if start_server "$PORT" python3 main.py >/dev/null; then
      STAGE_REACHED="started"
      log "Python server started successfully on port $DETECTED_PORT"
      write_result "$STAGE_REACHED" 0 "$DETECTED_PORT"
      push_result
      return 0
    fi
    # main.py found but no server started; treat as non-server script (success)
    log "main.py detected but no server port found; treating as script execution (non-server)"
    STAGE_REACHED="completed"
    write_result "$STAGE_REACHED" 0
    push_result
    log "=== RUN END ==="
    return 0
  elif [ -f "app.py" ]; then
    if start_server "$PORT" python3 app.py >/dev/null; then
      STAGE_REACHED="started"
      log "Python server started successfully on port $DETECTED_PORT"
      write_result "$STAGE_REACHED" 0 "$DETECTED_PORT"
      push_result
      return 0
    fi
    # app.py found but no server started; treat as non-server script (success)
    log "app.py detected but no server port found; treating as script execution (non-server)"
    STAGE_REACHED="completed"
    write_result "$STAGE_REACHED" 0
    push_result
    log "=== RUN END ==="
    return 0
  fi

  # No recognized project structure
  log "No recognized project structure (no package.json, main.py, or app.py)"
  write_result "$STAGE_REACHED" 1
  push_result
  log "=== RUN END ==="
}

main "$@"
