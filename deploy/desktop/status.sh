#!/usr/bin/env bash
pgrep -af 'campus_pro/website/.venv/bin/python|redis-server --port 6381' || echo "no campus processes"
ss -lntp 2>/dev/null | grep -E ':(5005|6381)' || true
