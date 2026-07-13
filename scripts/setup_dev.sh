#!/usr/bin/env bash
# setup_dev.sh — first-time Atlas developer setup
# Usage: bash scripts/setup_dev.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}▶ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠  $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; exit 1; }

# ── 1. Python version ──────────────────────────────────────────────────────────
step "Checking Python version"
PYTHON=$(command -v python3.11 || command -v python3 || fail "Python 3.11+ not found")
PY_VER=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "  Using $PYTHON ($PY_VER)"
[[ "$PY_VER" < "3.11" ]] && fail "Python 3.11+ required, found $PY_VER"

# ── 2. Virtual environment ─────────────────────────────────────────────────────
step "Creating virtual environment"
if [[ -d .venv ]]; then
  warn ".venv already exists — skipping creation"
else
  $PYTHON -m venv .venv
  echo "  Created .venv"
fi

# ── 3. Install dependencies ────────────────────────────────────────────────────
step "Installing dependencies"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"
echo "  Done"

# ── 4. .env file ──────────────────────────────────────────────────────────────
step "Setting up .env"
if [[ -f .env ]]; then
  warn ".env already exists — skipping"
else
  cp .env.example .env
  echo "  Created .env from .env.example"
  echo ""
  warn "ACTION REQUIRED: open .env and set OPENAI_API_KEY=sk-..."
fi

# ── 5. Docker infrastructure ───────────────────────────────────────────────────
step "Starting Qdrant + Redis via docker-compose"
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
  docker compose up -d
  echo "  Qdrant  → http://localhost:6333"
  echo "  Redis   → localhost:6379"
else
  warn "Docker not running — start Qdrant and Redis manually"
  echo "  Qdrant: docker run -p 6333:6333 qdrant/qdrant"
  echo "  Redis:  docker run -p 6379:6379 redis:7"
fi

# ── 6. Run tests ───────────────────────────────────────────────────────────────
step "Running test suite"
.venv/bin/pytest --tb=short -q || warn "Some tests failed — check output above"

# ── 7. Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete. Next steps:"
echo ""
echo "  1. Edit .env — add your OPENAI_API_KEY"
echo "  2. make fetch-corpus   # download FastAPI docs"
echo "  3. make ingest         # index into Qdrant"
echo "  4. make serve          # start the API on :8010"
echo "  5. make eval           # run the eval harness"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
