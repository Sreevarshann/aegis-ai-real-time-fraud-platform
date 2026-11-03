"""Persist dbt run_results.json into public.transformation_runs so the API/UI can show them."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg2


def main(path: str = "target/run_results.json") -> int:
    results = json.loads(Path(path).read_text())
    invocation = results["metadata"]["invocation_id"]
    completed = results["metadata"].get("generated_at") or datetime.now(UTC).isoformat()
    rows = []
    for r in results["results"]:
        node = r["unique_id"]
        rows.append((
            invocation, node, node.split(".")[0], r["status"], r.get("execution_time"),
            (r.get("adapter_response") or {}).get("rows_affected"), (r.get("message") or "")[:2000], completed,
        ))
    conn = psycopg2.connect(host=os.environ.get("DBT_HOST", "localhost"), port=int(os.environ.get("DBT_PORT", "5432")),
                            user=os.environ.get("DBT_USER", "aegis"), password=os.environ["DBT_PASSWORD"],
                            dbname=os.environ.get("DBT_DBNAME", "aegis"))
    with conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO transformation_runs (invocation_id, node_id, resource_type, status, execution_time_s,
                                               rows_affected, message, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", rows)
    conn.close()
    failed = [r for r in rows if r[3] in ("fail", "error")]
    print(f"recorded {len(rows)} dbt results for invocation {invocation}; failures: {len(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
