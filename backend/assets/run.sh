#!/usr/bin/env bash
# ============================================================
# Repo Viability Scanner — Execution Wrapper
# Injected into every Codespace via devcontainer postStartCommand.
#
# Detects project type, installs dependencies, attempts to start
# the app, and writes a structured result to /tmp/scanner_result.json.
# ============================================================

set -euo pipefail

RESULT_FILE="/tmp/scanner_result.json"
WORKDIR="${PWD}"
PORT=""
STAGE_REACHED="cloned"
EXIT_CODE=0
STDOUT_TAIL=""
STDERR_TAIL=""
START_TIME=$(date +%s)

log() { echo "[scanner] $*"; }

# ------------------------------------------------------------------
# Helper: write result JSON and exit
# ------------------------------------------------------------------
write_result() {
  local stage="$1"
  local exit_code="$2"
  local port="${3:-}"
  local health_url="${4:-}"

  cat > "$RESULT_FILE" <<EOF
{
  "stage_reached": "$stage",
  "port": ${port:-null},
  "health_check_url": ${health_url:+"\"$health_url\""}${health_url:-null},
  "stdout_tail": $(echo "$STDOUT_TAIL" | tail -50 | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))"),
  "stderr_tail": $(echo "$STDERR_TAIL" | tail -50 | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))"),
  "exit_code": $exit_code,
  "duration_sec": $(($(date +%s) - START_TIME))
}
EOF
  log "Result written to $RESULT_FILE (stage=$stage, exit=$exit_code)"
}

# ------------------------------------------------------------------
# Helper: wait for a port to be listening (max 60s)
# ------------------------------------------------------------------
wait_for_port() {
  local port="$1"
  local timeout=60
  local elapsed=0
  while [ $elapsed -lt $timeout ]; do
    if nc -z localhost "$port" 2>/dev/null; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

# ------------------------------------------------------------------
# Helper: run a command, capture output, set STDOUT_TAIL/STDERR_TAIL
# ------------------------------------------------------------------
run_cmd() {
  local tmp_out tmp_err
  tmp_out=$(mktemp)
  tmp_err=$(mktemp)
  "$@" > "$tmp_out" 2> "$tmp_err" &
  local pid=$!
  wait "$pid" || true
  EXIT_CODE=$?
  STDOUT_TAIL=$(cat "$tmp_out")
  STDERR_TAIL=$(cat "$tmp_err")
  rm -f "$tmp_out" "$tmp_err"
}

# ------------------------------------------------------------------
# Helper: start a background server, wait for port, return PID
# ------------------------------------------------------------------
start_server() {
  local port="$1"
  shift
  local tmp_out tmp_err
  tmp_out=$(mktemp)
  tmp_err=$(mktemp)
  "$@" > "$tmp_out" 2> "$tmp_err" &
  local pid=$!
  sleep 3
  if wait_for_port "$port"; then
    STDOUT_TAIL=$(cat "$tmp_out")
    STDERR_TAIL=$(cat "$tmp_err")
    rm -f "$tmp_out" "$tmp_err"
    echo "$pid"
    return 0
  else
    kill "$pid" 2>/dev/null || true
    STDOUT_TAIL=$(cat "$tmp_out")
    STDERR_TAIL=$(cat "$tmp_err")
    rm -f "$tmp_out" "$tmp_err"
    echo ""
    return 1
  fi
}

# ==================================================================
# MAIN DETECTION + EXECUTION
# ==================================================================

cd "$WORKDIR"
log "Working directory: $WORKDIR"
log "Files: $(ls | head -20 | tr '\n' ' ')"

# ------------------------------------------------------------------
# PYTHON
# ------------------------------------------------------------------
if [ -f "requirements.txt" ] || [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
  log "Detected: Python project"

  # Install dependencies
  if [ -f "requirements.txt" ]; then
    log "Installing requirements.txt..."
    pip install -r requirements.txt -q && STAGE_REACHED="installed" || {
      write_result "cloned" 1
      exit 0
    }
  elif [ -f "pyproject.toml" ]; then
    log "Installing via pyproject.toml..."
    pip install -e . -q && STAGE_REACHED="installed" || {
      write_result "cloned" 1
      exit 0
    }
  fi

  # Try common entrypoints in priority order
  PORT=8000
  SERVER_PID=""

  # uvicorn (FastAPI / ASGI)
  if python3 -c "import uvicorn" 2>/dev/null; then
    for entry in main:app app:app src.main:app; do
      log "Trying: uvicorn $entry --port $PORT"
      SERVER_PID=$(start_server "$PORT" uvicorn "$entry" --host 0.0.0.0 --port "$PORT") || true
      [ -n "$SERVER_PID" ] && break
    done
  fi

  # gunicorn
  if [ -z "$SERVER_PID" ] && python3 -c "import gunicorn" 2>/dev/null; then
    log "Trying: gunicorn"
    SERVER_PID=$(start_server "$PORT" gunicorn --bind "0.0.0.0:$PORT" main:app) || true
  fi

  # flask run
  if [ -z "$SERVER_PID" ] && python3 -c "import flask" 2>/dev/null; then
    log "Trying: flask run"
    PORT=5000
    SERVER_PID=$(start_server "$PORT" flask run --host 0.0.0.0 --port "$PORT") || true
  fi

  # python main.py / app.py / run.py
  if [ -z "$SERVER_PID" ]; then
    for script in main.py app.py run.py server.py; do
      if [ -f "$script" ]; then
        log "Trying: python3 $script"
        SERVER_PID=$(start_server "$PORT" python3 "$script") || true
        [ -n "$SERVER_PID" ] && break
      fi
    done
  fi

  if [ -n "$SERVER_PID" ]; then
    HEALTH_URL="http://localhost:$PORT"
    write_result "started" 0 "$PORT" "$HEALTH_URL"
  else
    write_result "installed" 1
  fi
  exit 0
fi

# ------------------------------------------------------------------
# NODE.JS
# ------------------------------------------------------------------
if [ -f "package.json" ]; then
  log "Detected: Node.js project"

  log "Installing npm dependencies..."
  npm install --silent && STAGE_REACHED="installed" || {
    write_result "cloned" 1
    exit 0
  }

  PORT=3000
  SERVER_PID=""

  # npm start
  log "Trying: npm start"
  SERVER_PID=$(start_server "$PORT" npm start) || true

  # npm run dev
  if [ -z "$SERVER_PID" ]; then
    log "Trying: npm run dev"
    SERVER_PID=$(start_server "$PORT" npm run dev) || true
  fi

  # node index.js
  if [ -z "$SERVER_PID" ] && [ -f "index.js" ]; then
    log "Trying: node index.js"
    SERVER_PID=$(start_server "$PORT" node index.js) || true
  fi

  if [ -n "$SERVER_PID" ]; then
    HEALTH_URL="http://localhost:$PORT"
    write_result "started" 0 "$PORT" "$HEALTH_URL"
  else
    write_result "installed" 1
  fi
  exit 0
fi

# ------------------------------------------------------------------
# GO
# ------------------------------------------------------------------
if [ -f "go.mod" ]; then
  log "Detected: Go project"

  log "Downloading Go modules..."
  go mod download && STAGE_REACHED="installed" || {
    write_result "cloned" 1
    exit 0
  }

  PORT=8080
  log "Trying: go run ."
  SERVER_PID=$(start_server "$PORT" go run .) || true

  if [ -n "$SERVER_PID" ]; then
    write_result "started" 0 "$PORT" "http://localhost:$PORT"
  else
    write_result "installed" 1
  fi
  exit 0
fi

# ------------------------------------------------------------------
# RUST
# ------------------------------------------------------------------
if [ -f "Cargo.toml" ]; then
  log "Detected: Rust project"

  log "Building with cargo..."
  cargo build --release 2>&1 && STAGE_REACHED="installed" || {
    write_result "cloned" 1
    exit 0
  }

  PORT=8080
  log "Trying: cargo run --release"
  SERVER_PID=$(start_server "$PORT" cargo run --release) || true

  if [ -n "$SERVER_PID" ]; then
    write_result "started" 0 "$PORT" "http://localhost:$PORT"
  else
    write_result "installed" 1
  fi
  exit 0
fi

# ------------------------------------------------------------------
# DOCKER
# ------------------------------------------------------------------
if [ -f "Dockerfile" ]; then
  log "Detected: Dockerfile"

  PORT=8080
  IMAGE_NAME="scanner-$(basename "$WORKDIR")-$(date +%s)"

  log "Building Docker image..."
  docker build -t "$IMAGE_NAME" . && STAGE_REACHED="installed" || {
    write_result "cloned" 1
    exit 0
  }

  log "Running Docker container..."
  docker run -d -p "$PORT:$PORT" --name scanner_container "$IMAGE_NAME" && sleep 5

  if wait_for_port "$PORT"; then
    write_result "started" 0 "$PORT" "http://localhost:$PORT"
  else
    write_result "installed" 1
  fi
  exit 0
fi

# ------------------------------------------------------------------
# UNKNOWN — nothing matched
# ------------------------------------------------------------------
log "No recognized project type found."
write_result "cloned" 1
