#!/usr/bin/env bash
# ============================================================
# Repo Viability Scanner — Execution Wrapper
# Injected into every Codespace via devcontainer postStartCommand.
#
# Detects project type, installs dependencies, attempts to start
# the app, and writes a structured result to scanner_result.json
# in the repo root, then git-pushes it back to the fork so the
# backend can read it via the GitHub Contents API.
# ============================================================

set -euo pipefail

RESULT_FILE="${GITHUB_WORKSPACE:-$PWD}/scanner_result.json"
WORKDIR="${GITHUB_WORKSPACE:-$PWD}"
PORT=""
STAGE_REACHED="cloned"
EXIT_CODE=0
STDOUT_TAIL=""
STDERR_TAIL=""
START_TIME=$(date +%s)

log() { echo "[scanner] $*" >&2; }

# ------------------------------------------------------------------
# Helper: write result JSON and git-push it
# ------------------------------------------------------------------
write_result() {
  local stage="$1"
  local exit_code="$2"
  local port="${3:-}"
  local health_url="${4:-}"

  local port_json="null"
  if [ -n "$port" ]; then port_json="$port"; fi

  local url_json="null"
  if [ -n "$health_url" ]; then url_json="\"$health_url\""; fi

  # Use python3 for safe JSON encoding of multiline strings
  python3 - <<PYEOF
import json, os, sys

data = {
    "stage_reached": "$stage",
    "port": $port_json,
    "health_check_url": $url_json,
    "stdout_tail": os.environ.get("_STDOUT_TAIL", ""),
    "stderr_tail": os.environ.get("_STDERR_TAIL", ""),
    "exit_code": $exit_code,
    "duration_sec": $(( $(date +%s) - START_TIME ))
}

with open("$RESULT_FILE", "w") as f:
    json.dump(data, f, indent=2)
print("Result written.")
PYEOF

  # Export stdout/stderr tails for Python to pick up
  export _STDOUT_TAIL="$STDOUT_TAIL"
  export _STDERR_TAIL="$STDERR_TAIL"

  python3 -c "
import json, os
data = {
    'stage_reached': '$stage',
    'port': $port_json,
    'health_check_url': $url_json,
    'stdout_tail': os.environ.get('_STDOUT_TAIL', ''),
    'stderr_tail': os.environ.get('_STDERR_TAIL', ''),
    'exit_code': $exit_code,
    'duration_sec': $(($(date +%s) - START_TIME))
}
with open('$RESULT_FILE', 'w') as f:
    json.dump(data, f, indent=2)
"

  log "Result written to $RESULT_FILE (stage=$stage, exit=$exit_code)"
  _git_push_result
}

# ------------------------------------------------------------------
# Helper: git commit and push result file to fork
# ------------------------------------------------------------------
_git_push_result() {
  log "Pushing result to fork..."
  cd "$WORKDIR"
  git config user.email "scanner@codespace.local" 2>/dev/null || true
  git config user.name "Repo Viability Scanner" 2>/dev/null || true
  git add scanner_result.json 2>/dev/null || true
  git commit -m "chore: scanner result" --allow-empty-message 2>/dev/null || true
  # Use the GITHUB_TOKEN from the Codespace environment for auth
  git push 2>/dev/null || log "Warning: git push failed — result may not be retrievable"
}

# ------------------------------------------------------------------
# Helper: wait for a port to be listening (max 60s)
# ------------------------------------------------------------------
wait_for_port() {
  local port="$1"
  local timeout=60
  local elapsed=0
  while [ $elapsed -lt $timeout ]; do
    if nc -z localhost "$port" 2>/dev/null || (echo > /dev/tcp/localhost/"$port") 2>/dev/null; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

# ------------------------------------------------------------------
# Helper: start background server, wait for port, capture output
# ------------------------------------------------------------------
start_server() {
  local port="$1"
  shift
  local tmp_out tmp_err
  tmp_out=$(mktemp)
  tmp_err=$(mktemp)
  "$@" >"$tmp_out" 2>"$tmp_err" &
  local pid=$!
  sleep 3
  if wait_for_port "$port"; then
    STDOUT_TAIL=$(tail -50 "$tmp_out")
    STDERR_TAIL=$(tail -50 "$tmp_err")
    rm -f "$tmp_out" "$tmp_err"
    echo "$pid"
    return 0
  else
    kill "$pid" 2>/dev/null || true
    STDOUT_TAIL=$(tail -50 "$tmp_out")
    STDERR_TAIL=$(tail -50 "$tmp_err")
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

  if [ -f "requirements.txt" ]; then
    log "Installing requirements.txt..."
    pip install -r requirements.txt -q 2>&1 | tail -5 && STAGE_REACHED="installed" || {
      STDERR_TAIL=$(pip install -r requirements.txt 2>&1 | tail -50)
      write_result "cloned" 1
      exit 0
    }
  elif [ -f "pyproject.toml" ]; then
    log "Installing via pyproject.toml..."
    pip install -e . -q 2>&1 | tail -5 && STAGE_REACHED="installed" || {
      STDERR_TAIL=$(pip install -e . 2>&1 | tail -50)
      write_result "cloned" 1
      exit 0
    }
  fi

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

  # python main.py / app.py / run.py / server.py
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
    write_result "started" 0 "$PORT" "http://localhost:$PORT"
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
  npm install --silent 2>&1 | tail -5 && STAGE_REACHED="installed" || {
    STDERR_TAIL=$(npm install 2>&1 | tail -50)
    write_result "cloned" 1
    exit 0
  }

  PORT=3000
  SERVER_PID=""

  log "Trying: npm start"
  SERVER_PID=$(start_server "$PORT" npm start) || true

  if [ -z "$SERVER_PID" ]; then
    log "Trying: npm run dev"
    SERVER_PID=$(start_server "$PORT" npm run dev) || true
  fi

  if [ -z "$SERVER_PID" ] && [ -f "index.js" ]; then
    log "Trying: node index.js"
    SERVER_PID=$(start_server "$PORT" node index.js) || true
  fi

  if [ -n "$SERVER_PID" ]; then
    write_result "started" 0 "$PORT" "http://localhost:$PORT"
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
  go mod download 2>&1 | tail -5 && STAGE_REACHED="installed" || {
    STDERR_TAIL=$(go mod download 2>&1 | tail -50)
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
  cargo build --release 2>&1 | tail -10 && STAGE_REACHED="installed" || {
    STDERR_TAIL=$(cargo build --release 2>&1 | tail -50)
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
  docker build -t "$IMAGE_NAME" . 2>&1 | tail -10 && STAGE_REACHED="installed" || {
    STDERR_TAIL=$(docker build -t "$IMAGE_NAME" . 2>&1 | tail -50)
    write_result "cloned" 1
    exit 0
  }

  log "Running Docker container..."
  docker run -d -p "$PORT:$PORT" --name scanner_container "$IMAGE_NAME"
  sleep 5

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
STDERR_TAIL="Could not detect project type. No requirements.txt, package.json, go.mod, Cargo.toml, or Dockerfile found."
write_result "cloned" 1
