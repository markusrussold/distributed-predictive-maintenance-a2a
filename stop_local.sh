#!/usr/bin/env bash
# Stops every agent process started by run_local.sh.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .pids ]; then
  echo "No .pids file found; nothing to stop."
  exit 0
fi

while read -r pid; do
  [ -z "$pid" ] && continue
  if kill "$pid" 2>/dev/null; then
    echo "Stopped process $pid"
  fi
done < .pids

rm -f .pids
echo "Done."
