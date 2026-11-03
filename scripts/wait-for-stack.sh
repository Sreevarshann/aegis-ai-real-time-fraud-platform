#!/usr/bin/env bash
# Wait for the stack to become usable, failing loudly (with logs) if a startup step fails.
set -uo pipefail
COMPOSE="${COMPOSE:-docker compose}"
TIMEOUT="${STACK_TIMEOUT:-420}"
start=$(date +%s)

fail() {
  echo ""
  echo "ERROR: $1"
  [ -n "${2:-}" ] && { echo "---- last log lines from '$2' ----"; $COMPOSE logs --tail=40 "$2"; }
  exit 1
}

oneshot_status() {  # prints: running | ok | failed:<code> | missing
  local id; id=$($COMPOSE ps -a -q "$1" 2>/dev/null | head -1)
  [ -z "$id" ] && { echo missing; return; }
  local state code
  state=$(docker inspect -f '{{.State.Status}}' "$id"); code=$(docker inspect -f '{{.State.ExitCode}}' "$id")
  if [ "$state" = "exited" ]; then [ "$code" = "0" ] && echo ok || echo "failed:$code"; else echo running; fi
}

echo -n "Waiting for AEGIS stack (migrations -> seed -> model training -> pipeline -> API -> UI)"
while true; do
  for job in migrate trainer; do
    s=$(oneshot_status "$job")
    [[ "$s" == failed:* ]] && fail "startup job '$job' exited with code ${s#failed:}" "$job"
  done
  for svc in consumer api; do
    id=$($COMPOSE ps -a -q "$svc" | head -1)
    if [ -n "$id" ] && [ "$(docker inspect -f '{{.RestartCount}}' "$id")" -gt 3 ]; then
      fail "service '$svc' is crash-looping" "$svc"
    fi
  done
  if curl -fsS http://localhost:8000/health/ready >/dev/null 2>&1 \
     && curl -fsS http://localhost:3000/ >/dev/null 2>&1 \
     && curl -fsS http://localhost:9108/metrics >/dev/null 2>&1; then
    echo " ready ($(( $(date +%s) - start ))s)"
    $COMPOSE ps --format 'table {{.Service}}\t{{.Status}}'
    exit 0
  fi
  [ $(( $(date +%s) - start )) -gt "$TIMEOUT" ] && fail "stack not ready after ${TIMEOUT}s (see 'docker compose ps')" api
  echo -n "."
  sleep 5
done
