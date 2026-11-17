#!/usr/bin/env bash
# issue-hub 一键启动
#   ./start.sh            仅启动（首次会自动装后端依赖、构建前端）
#   ./start.sh --build    强制重新构建前端
#   ISSUEHUB_PORT=8091 ./start.sh   换端口
set -euo pipefail
cd "$(dirname "$0")"

PORT="${ISSUEHUB_PORT:-8090}"

# nvm 装的 node/dsh/claude 不在默认 PATH 里，先补进去（服务里调 CLI 执行器要用）
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[ -n "$NODE_BIN" ] && export PATH="$NODE_BIN:$PATH"

if [ ! -x backend/.venv/bin/python ]; then
  echo "==> 创建 Python 虚拟环境"
  python3 -m venv backend/.venv
fi
echo "==> 安装后端依赖"
backend/.venv/bin/pip -q install -r backend/requirements.txt

if [ "${1:-}" = "--build" ] || [ ! -d frontend/dist ]; then
  echo "==> 构建前端"
  (cd frontend && npm install --no-fund --no-audit && npm run build)
fi

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "端口 $PORT 已被占用，先执行 ./stop.sh 或换 ISSUEHUB_PORT" >&2
  exit 1
fi

echo "==> 启动 http://0.0.0.0:$PORT"
exec backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "$PORT"
