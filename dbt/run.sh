#!/bin/sh
# Build seeds, models and tests on an interval, recording every invocation's results.
# A failing dbt build is logged and recorded (visible in the UI) but does not stop the loop.
set -u
INTERVAL="${DBT_INTERVAL_SECONDS:-120}"
while true; do
  dbt build --profiles-dir . --target dev
  echo "dbt build exit code: $?"
  python record_results.py || echo "failed to record dbt results"
  [ "$INTERVAL" = "0" ] && exit 0
  sleep "$INTERVAL"
done
