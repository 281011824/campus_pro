#!/bin/bash
# 双机数据同步：台式机（业务主库）→ 主云（公网镜像/灾备）。
# 需在可同时 SSH 到主云与台式机的机器上执行；台式机经主云跳板访问。
# 注意：主云写入会在下次同步时被覆盖，主云仅作镜像与灾备。
set -euo pipefail

CLOUD=root@124.221.26.96
DESKTOP=fc@10.66.0.4
JUMP=root@124.221.26.96
ROOT=/opt/school_pro
DATE=$(date +%Y%m%d_%H%M%S)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== 1/5 台式机数据库热备 =="
SNAP_PY='
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
print("snapshot ok")
'
B64=$(printf '%s' "$SNAP_PY" | base64 | tr -d '\n')
ssh -J "$JUMP" "$DESKTOP" "printf '%s' '$B64' | base64 -d | $ROOT/website/.venv/bin/python - $ROOT/runtime/dywork.db /tmp/dywork_sync_$DATE.db"

echo "== 2/5 拉取主库快照 =="
scp -J "$JUMP" "$DESKTOP:/tmp/dywork_sync_$DATE.db" "$WORK/primary.db"

echo "== 3/5 备份主云并停机替换 =="
scp "$WORK/primary.db" "$CLOUD:/tmp/dywork_sync_$DATE.db"
ssh "$CLOUD" "set -e
  mkdir -p $ROOT/_backup/db_sync_$DATE
  systemctl stop htw-website
  cp -f $ROOT/runtime/dywork.db $ROOT/_backup/db_sync_$DATE/dywork_before.db
  install -m 644 -o root -g root /tmp/dywork_sync_$DATE.db $ROOT/runtime/dywork.db
  rm -f $ROOT/runtime/dywork.db-wal $ROOT/runtime/dywork.db-shm
  systemctl start htw-website
  for i in \$(seq 1 25); do
    code=\$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:5004/healthz || true)
    [ \"\$code\" = 200 ] && break
    sleep 1
  done
  echo healthz=\$code
  [ \"\$code\" = 200 ]
  rm -f /tmp/dywork_sync_$DATE.db"

echo "== 4/5 取回主云快照并审计 =="
ssh "$CLOUD" "$ROOT/website/.venv/bin/python - $ROOT/runtime/dywork.db /tmp/dywork_mirror_$DATE.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
scp "$CLOUD:/tmp/dywork_mirror_$DATE.db" "$WORK/mirror.db"
ssh "$CLOUD" "rm -f /tmp/dywork_mirror_$DATE.db"

python3 "$(dirname "$0")/db_audit.py" "$WORK/primary.db" "$WORK/mirror.db"

echo "== 5/5 同步完成 =="
echo "主云备份：$ROOT/_backup/db_sync_$DATE/dywork_before.db"
