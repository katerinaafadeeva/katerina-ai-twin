#!/usr/bin/env bash
# verify_friday_test.sh — Verify Friday integration test results
# Usage: bash scripts/verify_friday_test.sh
# Run this AFTER the bot has been running for 10-15 minutes on Friday.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Friday test verification ==="
echo "Project root: $PROJECT_ROOT"

DB_PATH=$(python -c "from core.config import config; print(config.db_path)" 2>/dev/null || echo "data/career.db")
echo "DB: $DB_PATH"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found at $DB_PATH"
    exit 1
fi

echo ""
echo "--- Ingested today ---"
python -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
row = conn.execute(\"SELECT COUNT(*) FROM job_raw WHERE date(created_at) = date('now')\").fetchone()
print(f'  Vacancies ingested today: {row[0]}')
"

echo ""
echo "--- Scored today ---"
python -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
total = conn.execute(\"SELECT COUNT(*) FROM job_scores WHERE date(scored_at) = date('now')\").fetchone()[0]
pre_filter = conn.execute(\"SELECT COUNT(*) FROM job_scores WHERE date(scored_at) = date('now') AND model = 'pre_filter'\").fetchone()[0]
llm_scored = total - pre_filter
print(f'  Total scored: {total}')
print(f'  Pre-filtered (no LLM): {pre_filter}')
print(f'  LLM-scored: {llm_scored}')
"

echo ""
echo "--- Actions today ---"
python -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
rows = conn.execute(\"SELECT action_type, COUNT(*) FROM actions WHERE date(created_at) = date('now') GROUP BY action_type\").fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')
"

echo ""
echo "--- Apply runs today ---"
python -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
rows = conn.execute(\"SELECT status, COUNT(*) FROM apply_runs WHERE date(finished_at) = date('now') GROUP BY status\").fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')
done = conn.execute(\"SELECT COUNT(*) FROM apply_runs WHERE status IN ('done','done_without_letter') AND date(finished_at) = date('now')\").fetchone()[0]
print(f'  --- Total successful: {done}')
"

echo ""
echo "--- Recent events ---"
python -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
rows = conn.execute(\"SELECT event_name, COUNT(*) FROM events WHERE date(created_at) = date('now') GROUP BY event_name ORDER BY COUNT(*) DESC\").fetchall()
for r in rows[:10]:
    print(f'  {r[0]}: {r[1]}')
"

echo ""
echo "=== Verification complete. ==="
