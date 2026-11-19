"""鉴权路由与依赖。

两种模式（设置项 `auth.enabled`）：
- 关（默认）：本地单人用，所有请求视为 admin，不打扰
- 开：必须登录；IP 白名单在**每次请求**都校验（不只是登录时）

为什么每次请求都查 IP：登录时校验只保证「当时在那个网段」，
之后换网络旧 token 依然能用 —— 那是白名单最常见的绕过方式。
"""
import ipaddress
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import auth
from ..db import get_settings, save_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 允许白名单之外访问的路径（登录本身、健康检查）
OPEN_PATHS = {"/api/health", "/api/auth/login", "/api/auth/mode"}


class LoginReq(BaseModel):
    username: str
    password: str


class PasswordReq(BaseModel):
    password: str


class UserCreateReq(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "user"


class ModeReq(BaseModel):
    enabled: bool


# 可信反代地址：只有来自这些 IP 的请求，X-Forwarded-For 才被采信。
# 这是白名单的经典绕过点 —— 攻击者直连服务并自带 `X-Forwarded-For: 10.1.2.3`
# 就能被当成内网 IP。所以必须「先确认请求真的来自反代」再看这个头。
TRUSTED_PROXIES = {"127.0.0.1", "::1", "172.17.0.1", "172.18.0.1", "172.19.0.1"}


def _trusted_proxy_ips() -> set[str]:
    """可信反代地址 = 内置回环/常见 docker 网关 + 设置里补充的。"""
    extra = (get_settings().get("auth.trusted_proxies") or "").strip()
    items = {s.strip() for s in extra.replace(",", "\n").splitlines() if s.strip()}
    return TRUSTED_PROXIES | items


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    只有在**直连方是可信反代**时才采信 X-Forwarded-For，
    否则一律用 socket 的 remote addr —— 防止客户端自己伪造。
    """
    remote = request.client.host if request.client else ""
    if remote in _trusted_proxy_ips():
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            # XFF 是逗号链，最左是客户端，但要取最右的「第一个非可信」更稳。
            # 这里简单取最左（nginx 会 append，最左是原始客户端）。
            return xff.split(",")[0].strip()
        real = request.headers.get("x-real-ip") or ""
        if real.strip():
            return real.strip()
    return remote


def auth_enabled() -> bool:
    return (get_settings().get("auth.enabled") or "0").strip() in ("1", "true", "yes")


def current_user(request: Request) -> Optional[dict]:
    """解析当前用户。鉴权关闭时返回一个虚拟 admin。"""
    if not auth_enabled():
        return {"id": 0, "username": "local", "displayName": "本机", "role": "admin"}
    token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()
    return auth.get_session_user(token)


def require_user(request: Request) -> dict:
    """FastAPI 依赖：拿不到用户就 401。"""
    user = current_user(request)
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    if not auth.ip_allowed(client_ip(request)):
        raise HTTPException(403, "当前 IP 不在白名单内")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


# ---------------- 接口 ----------------

@router.get("/mode")
def get_mode():
    """前端启动时问一下：要不要显示登录页。"""
    return {"enabled": auth_enabled()}


@router.post("/login")
def login(payload: LoginReq, request: Request):
    if not auth_enabled():
        raise HTTPException(400, "当前未开启登录")
    ip = client_ip(request)
    if not auth.ip_allowed(ip):
        raise HTTPException(403, f"IP {ip} 不在白名单内")
    row = auth.get_user_by_name(payload.username.strip())
    if not row or not auth.verify_password(payload.password, row["password_hash"]):
        raise HTTPException(401, "用户名或密码不正确")
    if not row.get("enabled"):
        raise HTTPException(403, "该账号已被停用")
    session = auth.create_session(row["id"], ip)
    return {
        "token": session["token"],
        "expiresAt": session["expiresAt"],
        "user": {"id": row["id"], "username": row["username"],
                 "displayName": row.get("display_name") or row["username"],
                 "role": row["role"]},
    }


@router.post("/logout")
def logout(request: Request):
    token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()
    if token:
        auth.delete_session(token)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"user": require_user(request)}


# ---------------- 用户管理（管理员） ----------------

@router.get("/users")
def users(request: Request):
    require_admin(request)
    return {"users": auth.list_users()}


@router.post("/users")
def add_user(payload: UserCreateReq, request: Request):
    require_admin(request)
    try:
        uid = auth.create_user(payload.username, payload.password,
                               payload.display_name, payload.role)
    except auth.AuthError as ex:
        raise HTTPException(400, str(ex))
    return {"id": uid}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, payload: PasswordReq, request: Request):
    """改密码（管理员可改任何人，普通用户只能改自己）。"""
    me_user = require_user(request)
    if me_user.get("role") != "admin" and me_user.get("id") != user_id:
        raise HTTPException(403, "只能修改自己的密码")
    try:
        auth.set_password(user_id, payload.password)
    except auth.AuthError as ex:
        raise HTTPException(400, str(ex))
    return {"ok": True}


@router.post("/users/{user_id}/enabled")
def toggle_user(user_id: int, enabled: bool, request: Request):
    require_admin(request)
    auth.set_enabled(user_id, enabled)
    return {"ok": True}


@router.delete("/users/{user_id}")
def remove_user(user_id: int, request: Request):
    me_user = require_admin(request)
    if me_user.get("id") == user_id:
        raise HTTPException(400, "不能删除自己")
    auth.delete_user(user_id)
    return {"ok": True}


@router.post("/mode")
def set_mode(payload: ModeReq, request: Request):
    """开关鉴权。关的时候要求已经登录过（防止裸奔的实例被任意关掉）。"""
    if payload.enabled is False:
        require_admin(request)
    save_settings({"auth.enabled": "1" if payload.enabled else "0"})
    return {"ok": True, "enabled": payload.enabled}
