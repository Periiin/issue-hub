"""issue-hub 后端入口。

- 单进程：FastAPI 同时提供 API 和前端静态文件，8090 一个端口就够
- 数据：data/issuehub.db（SQLite）+ data/attachments（截图）
- 局域网使用：不加登录，靠网络隔离；要外网暴露请先套 nginx basic auth
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ATTACH_DIR, FRONTEND_DIST
from .db import init_db
from .routers import ai, fix, issues, report, settings

app = FastAPI(title="Issue Hub", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(issues.router)
app.include_router(ai.router)
app.include_router(fix.router)
app.include_router(report.router)
app.include_router(settings.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True}


# 附件静态访问：/files/<issue_id>/<uuid>.png
app.mount("/files", StaticFiles(directory=str(ATTACH_DIR), check_dir=False), name="files")

# 前端构建产物：存在 dist 就托管；开发期直接跑 vite（5173）代理到本服务
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "前端还没构建：cd frontend && npm install && npm run build"},
        status_code=503,
    )
