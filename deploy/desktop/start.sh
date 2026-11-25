#!/usr/bin/env bash
# 台式机（无 root 权限）常驻启动：redis 6381 + uvicorn 10.66.0.4:5005 + worker
set -e
DEST=/opt/campus_pro
mkdir -p "$DEST/logs" "$DEST/runtime"
set -a; . "$DEST/campus.env"; set +a
if ! pgrep -f 'redis-server --port 6381' >/dev/null; then
  setsid nohup /usr/bin/redis-server --port 6381 --bind 127.0.0.1 --save "" --appendonly no \
    --maxmemory 256mb --maxmemory-policy noeviction >> "$DEST/logs/redis.log" 2>&1 < /dev/null &
  sleep 1
fi
if ! pgrep -f 'campus_pro/website/.venv/bin/python -m uvicorn' >/dev/null; then
  cd "$DEST/website"
  setsid nohup "$DEST/website/.venv/bin/python" -m uvicorn app.main:app \
    --host 10.66.0.4 --port 5005 --workers 2 --proxy-headers --forwarded-allow-ips 10.66.0.1 \
    >> "$DEST/logs/website.log" 2>&1 < /dev/null &
fi
if ! pgrep -f 'campus_pro/website/.venv/bin/python -m tasks.interfaces.worker' >/dev/null; then
  cd "$DEST"
  setsid nohup "$DEST/website/.venv/bin/python" -m tasks.interfaces.worker \
    >> "$DEST/logs/worker.log" 2>&1 < /dev/null &
fi
sleep 3
echo started
