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
from .. import ratelimit as rl
from ..db import connect, get_settings, save_settings

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
    ua = request.headers.get("user-agent") or ""
    username = payload.username.strip()

    def fail(result: str, user_id: int | None = None, note: str = ""):
        """失败统一走这里：先落审计，再抛。避免每个分支都写一遍。"""
        auth.record_login(username, result, ip, user_id, ua, note)

    if not auth.ip_allowed(ip):
        fail("bad_ip", note="IP 不在白名单")
        raise HTTPException(403, f"IP {ip} 不在白名单内")

    # 限流前置：IP 频率 + 该 IP+用户名 是否被锁
    try:
        rl.check_login(ip, username)
    except rl.RateLimited as ex:
        fail("locked", note=str(ex))
        raise HTTPException(429, str(ex),
                            headers={"Retry-After": str(ex.retry_after)})

    row = auth.get_user_by_name(username)
    if not row:
        fail("no_user")
        # 照样计失败次数：否则「用户不存在」能无限试，等于免费爆破探针
        rl.record_failure(ip, username)
        left = max(0, rl._cfg_int("rate.fail_limit", rl.DEFAULT_FAIL_LIMIT) - 1)
        raise HTTPException(401, f"用户名或密码不正确（还可尝试 {left} 次）")

    if not auth.verify_password(payload.password, row["password_hash"]):
        info = rl.record_failure(ip, username)
        fail("bad_password", row["id"])
        if info["locked"]:
            raise HTTPException(
                429,
                f"密码错误 {info['fails']} 次，账号已临时锁定 "
                f"{max(1, info['remain'] // 60)} 分钟",
                headers={"Retry-After": str(info["remain"])})
        # 提示剩余次数，但不要暴露「用户名是否存在」
        left = max(0, rl._cfg_int("rate.fail_limit", rl.DEFAULT_FAIL_LIMIT) - info["fails"])
        raise HTTPException(401, f"用户名或密码不正确（还可尝试 {left} 次）")

    if not row.get("enabled"):
        fail("disabled", row["id"])
        raise HTTPException(403, "该账号已被停用")

    # 成功：清掉失败计数
    rl.clear_failures(ip, username)
    session = auth.create_session(row["id"], ip)
    auth.record_login(username, "ok", ip, row["id"], ua)
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
        user = auth.get_session_user(token)
        if user:
            auth.record_login(user["username"], "logout", client_ip(request),
                              user["id"], request.headers.get("user-agent") or "")
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


@router.get("/assignees")
def assignees(request: Request):
    """可选负责人列表（只给用户名和显示名）。

    普通用户也要能选负责人，但不该看到角色/停用状态/创建时间这些管理字段，
    所以单独开一个精简接口，而不是放宽 /users 的权限。
    """
    require_user(request)
    return {"users": [
        {"username": u["username"], "displayName": u.get("display_name") or u["username"]}
        for u in auth.list_users() if u.get("enabled")
    ]}


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


@router.get("/login-logs")
def login_logs(request: Request, limit: int = 50, offset: int = 0,
               username: str = "", result: str = "", keyword: str = ""):
    """登录记录（管理员）。按时间倒序，可按用户名/结果/关键词过滤。"""
    require_admin(request)
    limit = max(1, min(limit, 200))
    return auth.list_login_logs(limit=limit, offset=max(0, offset),
                                username=username.strip(), result=result.strip(),
                                keyword=keyword.strip())


@router.delete("/login-logs")
def clear_login_logs(request: Request):
    """清空登录记录（管理员）。keep_days=0 表示全清。"""
    require_admin(request)
    n = auth.purge_login_logs(keep_days=0)
    return {"ok": True, "deleted": n}


# ---------------- 限流管理（管理员） ----------------

@router.get("/rate/status")
def rate_status(request: Request):
    require_admin(request)
    return rl.status()


@router.post("/rate/unlock")
def rate_unlock(lock_key: str, request: Request):
    """手工解锁。lock_key 形如 `192.168.1.5|alice`。"""
    require_admin(request)
    rl.unlock(lock_key)
    return {"ok": True}


@router.post("/rate/clear")
def rate_clear(request: Request):
    """清空所有计数与锁（换环境/误伤时用）。"""
    require_admin(request)
    n = rl.purge_old(days=0)
    with connect() as conn:
        conn.execute("DELETE FROM rate_counter")
        conn.execute("DELETE FROM rate_lock")
    return {"ok": True, "purged": n}


@router.post("/mode")
def set_mode(payload: ModeReq, request: Request):
    """开关鉴权。关的时候要求已经登录过（防止裸奔的实例被任意关掉）。"""
    if payload.enabled is False:
        require_admin(request)
    save_settings({"auth.enabled": "1" if payload.enabled else "0"})
    return {"ok": True, "enabled": payload.enabled}
