"""issue-hub 后端入口。

- 单进程：FastAPI 同时提供 API 和前端静态文件，8090 一个端口就够
- 数据：data/issuehub.db（SQLite）+ data/attachments（截图）
- 鉴权：默认关闭（单人本机用）；设置 `auth.enabled=1` 后要求登录 + IP 白名单
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth as auth_mod
from .config import ATTACH_DIR, FRONTEND_DIST
from .db import init_db
from .routers import ai, auth, channels, fix, issues, projects, report, settings
from .routers.auth import OPEN_PATHS, auth_enabled, client_ip, current_user

app = FastAPI(title="Issue Hub", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """统一鉴权闸门。

    放在中间件而不是逐个路由加依赖：路由太多（22 个 MCP 工具对应的 HTTP 接口
    也在其中），漏加一个就是越权口子。中间件默认全拦、白名单放行。

    鉴权关闭时直接放行 —— 单人本机用不该被登录打扰。
    """
    path = request.url.path
    if not path.startswith("/api/") or path in OPEN_PATHS:
        return await call_next(request)
    if not auth_enabled():
        return await call_next(request)

    ip = client_ip(request)
    if not auth_mod.ip_allowed(ip):
        return JSONResponse({"detail": f"IP {ip} 不在白名单内"}, status_code=403)

    if current_user(request) is None:
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)

    return await call_next(request)


app.include_router(auth.router)
app.include_router(issues.router)
app.include_router(ai.router)
app.include_router(fix.router)
app.include_router(projects.router)
app.include_router(channels.router)
app.include_router(report.router)
app.include_router(settings.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # 没有用户时建 admin 并把初始密码打到日志（只打一次）
    initial = auth_mod.ensure_admin()
    if initial:
        print("=" * 60, flush=True)
        print("  已创建初始管理员账号", flush=True)
        print("  用户名: admin", flush=True)
        print(f"  密码:   {initial}", flush=True)
        print("  请登录后立即修改密码，并删除这条日志", flush=True)
        print("=" * 60, flush=True)


@app.get("/api/health")
def health():
    return {"ok": True}


# 附件静态访问：/files/<issue_id>/<uuid>.png
app.mount("/files", StaticFiles(directory=str(ATTACH_DIR), check_dir=False), name="files")

# 前端构建产物：存在 dist 就托管；开发期直接跑 vite（5173）代理到本服务
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


# PWA 静态文件：manifest / service worker / 图标。
# 这几个必须在 SPA 兜底路由之前，否则会被 index.html 顶掉。
_PWA_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "application/javascript",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "favicon.ico": "image/x-icon",
}


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if path in _PWA_FILES:
        f = FRONTEND_DIST / path
        if f.is_file():
            return FileResponse(f, media_type=_PWA_FILES[path])
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "前端还没构建：cd frontend && npm install && npm run build"},
        status_code=503,
    )
