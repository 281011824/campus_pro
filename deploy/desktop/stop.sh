#!/usr/bin/env bash
pkill -f 'campus_pro/website/.venv/bin/python -m uvicorn' 2>/dev/null || true
pkill -f 'campus_pro/website/.venv/bin/python -m tasks.interfaces.worker' 2>/dev/null || true
pkill -f 'redis-server --port 6381' 2>/dev/null || true
sleep 1
echo stopped
