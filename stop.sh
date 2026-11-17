#!/usr/bin/env bash
# 停掉 issue-hub（按端口找进程，不用记 pid）
set -euo pipefail
PORT="${ISSUEHUB_PORT:-8090}"
PIDS="$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $0}' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
if [ -z "$PIDS" ]; then
  echo "端口 $PORT 上没有进程"
  exit 0
fi
echo "==> 停止 pid: $PIDS"
kill $PIDS
sleep 1
ss -ltn 2>/dev/null | grep -q ":$PORT " && { echo "还在，强制 kill -9"; kill -9 $PIDS; } || echo "已停止"
