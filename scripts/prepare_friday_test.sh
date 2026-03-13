#!/usr/bin/env bash
# prepare_friday_test.sh — Prepare environment for Friday integration test
# Usage: bash scripts/prepare_friday_test.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Friday test preparation ==="
echo "Project root: $PROJECT_ROOT"

# 1. Verify .env exists
if [[ ! -f ".env" ]]; then
    echo "ERROR: .env not found. Copy .env.example and fill in credentials."
    exit 1
fi
echo "OK: .env found"

# 2. Verify Python environment
python --version || python3 --version
echo "OK: Python available"

# 3. Install dependencies
if [[ -f "requirements.txt" ]]; then
    pip install -r requirements.txt --quiet
    echo "OK: dependencies installed"
fi

# 4. Run unit tests to verify baseline
echo ""
echo "=== Running unit tests ==="
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
echo "OK: unit tests complete"

# 5. Verify DB init
python -c "from core.db import init_db; init_db(); print('OK: DB initialized')"

# 6. Check HH session state
HH_STORAGE=$(python -c "from core.config import config; print(config.hh_storage_state_path)")
if [[ -f "$HH_STORAGE" ]]; then
    echo "OK: HH session state found at $HH_STORAGE"
else
    echo "WARNING: HH session state NOT found at $HH_STORAGE"
    echo "   Run: python -m connectors.hh_browser.bootstrap"
fi

echo ""
echo "=== Preparation complete. Ready for Friday test. ==="
