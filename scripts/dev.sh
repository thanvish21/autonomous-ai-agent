#!/usr/bin/env bash
# One-command local dev — runs Redis in Docker (if available), backend + frontend natively.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[!] Wrote .env from .env.example — fill in ANTHROPIC_API_KEY before running."
fi

# Backend deps
python3 -m venv .venv 2>/dev/null || true
. .venv/bin/activate
pip install -q -r backend/requirements.txt

# Frontend deps
(cd frontend && npm install --silent)

# Redis (optional — agent works without it via in-memory store)
if command -v docker >/dev/null 2>&1; then
  docker run -d --rm --name agent-redis -p 6379:6379 redis:7-alpine >/dev/null 2>&1 || true
fi

# Run backend + frontend in parallel
trap 'kill 0' EXIT
python3 -m backend.run &
(cd frontend && npm run dev) &
wait
