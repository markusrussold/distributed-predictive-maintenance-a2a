#!/usr/bin/env bash
# Launches all 5 agent processes locally (no Docker), each on its own port,
# logging to logs/<name>.log and tracking PIDs in .pids for stop_local.sh.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON_BIN:-.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "Creating virtualenv in .venv ..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

mkdir -p logs
: > .pids

export REGISTRY_URL="http://127.0.0.1:8000"

start() {
  local name="$1" module="$2" port="$3"
  echo "Starting $name on port $port ..."
  SELF_URL="http://127.0.0.1:${port}" \
    "$PY" -m uvicorn "$module" --host 127.0.0.1 --port "$port" \
    > "logs/${name}.log" 2>&1 &
  echo $! >> .pids
}

start registry   agents.registry.main:app          8000
sleep 1
start vibration   agents.vibration_agent.main:app   8002
start thermal     agents.thermal_agent.main:app     8003
start maintenance agents.maintenance_agent.main:app 8004
sleep 1
start orchestrator agents.orchestrator.main:app     8001

echo
echo "All agents starting. Waiting a few seconds for registration ..."
sleep 3
echo
echo "Live agents registered:"
curl -s http://127.0.0.1:8000/agents | "$PY" -m json.tool || true
echo
echo "PIDs stored in .pids. Logs in ./logs/. Run ./stop_local.sh to stop everything."
