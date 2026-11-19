"""登录与会话。

安全模型：
- 密码用 `hashlib.scrypt` 加盐哈希（标准库，不引依赖）。参数取 N=2^14 是
  「手机上几百毫秒」的常见档位，够挡住离线爆破又不至于让登录卡顿。
- token 是 `secrets.token_urlsafe(32)`，存库带过期时间，服务重启不掉线。
- **IP 白名单在登录和每次请求都校验**：只靠登录时校验不够，
  换网络后旧 token 仍能用的口子必须堵上。
- 首次启动如果没有用户，自动建一个 admin，密码打在日志里 —— 否则没人能登录。
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

from .db import connect, get_settings, now

# scrypt 参数：N 越大越慢越安全。2^14 ≈ 16MB 内存、几十毫秒
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16

SESSION_DAYS = 14


class AuthError(RuntimeError):
    pass


# ---------------- 密码 ----------------

def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N,
                            r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        # 定时安全比较，避免通过响应时间猜密码
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ---------------- 用户 ----------------

def _user_row(r) -> dict:
    d = dict(r)
    d.pop("password_hash", None)
    d["enabled"] = bool(d.get("enabled"))
    return d


def list_users() -> list[dict]:
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT id, username, display_name, role, enabled, created_at "
                "FROM app_user ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return []
    return [_user_row(r) for r in rows]


def get_user(user_id: int) -> dict | None:
    try:
        with connect() as conn:
            r = conn.execute(
                "SELECT id, username, display_name, role, enabled, created_at "
                "FROM app_user WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return _user_row(r) if r else None


def get_user_by_name(username: str) -> dict | None:
    """内部用：含 password_hash。"""
    try:
        with connect() as conn:
            r = conn.execute("SELECT * FROM app_user WHERE username = ?",
                             (username,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(r) if r else None


def create_user(username: str, password: str, display_name: str = "",
                role: str = "user") -> int:
    if not username.strip():
        raise AuthError("用户名不能为空")
    if len(password) < 6:
        raise AuthError("密码至少 6 位")
    if role not in ("admin", "user"):
        raise AuthError("角色只能是 admin 或 user")
    if get_user_by_name(username):
        raise AuthError(f"用户名 {username} 已存在")
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO app_user(username, password_hash, display_name, role, enabled, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (username.strip(), hash_password(password), display_name.strip() or username,
             role, ts, ts))
        return cur.lastrowid


def set_password(user_id: int, password: str) -> None:
    if len(password) < 6:
        raise AuthError("密码至少 6 位")
    with connect() as conn:
        conn.execute("UPDATE app_user SET password_hash = ?, updated_at = ? WHERE id = ?",
                     (hash_password(password), now(), user_id))


def set_enabled(user_id: int, enabled: bool) -> None:
    with connect() as conn:
        conn.execute("UPDATE app_user SET enabled = ?, updated_at = ? WHERE id = ?",
                     (1 if enabled else 0, now(), user_id))


def delete_user(user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM app_user WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM app_session WHERE user_id = ?", (user_id,))


# ---------------- 会话 ----------------

def create_session(user_id: int, ip: str = "") -> dict:
    token = secrets.token_urlsafe(32)
    created = datetime.now()
    expires = created + timedelta(days=SESSION_DAYS)
    fmt = "%Y-%m-%d %H:%M:%S"
    with connect() as conn:
        conn.execute(
            "INSERT INTO app_session(token, user_id, ip, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, user_id, ip, created.strftime(fmt), expires.strftime(fmt)))
    return {"token": token, "expiresAt": expires.strftime(fmt)}


def get_session_user(token: str) -> dict | None:
    """token → 用户。过期或用户被禁用都返回 None。"""
    if not token:
        return None
    try:
        with connect() as conn:
            r = conn.execute(
                "SELECT s.user_id, s.expires_at, u.id, u.username, u.display_name, "
                "u.role, u.enabled FROM app_session s JOIN app_user u ON u.id = s.user_id "
                "WHERE s.token = ?", (token,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not r:
        return None
    if not r["enabled"]:
        return None
    try:
        if datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.now():
            return None
    except ValueError:
        return None
    return {"id": r["id"], "username": r["username"],
            "displayName": r["display_name"], "role": r["role"]}


def delete_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM app_session WHERE token = ?", (token,))


def purge_expired_sessions() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM app_session WHERE expires_at < ?", (now(),))
        return cur.rowcount


# ---------------- IP 白名单 ----------------

def allowed_networks() -> list:
    """设置里的 IP 白名单，一行一个（支持 CIDR 与单个 IP）。空 = 不限制。"""
    raw = (get_settings().get("auth.ip_allowlist") or "").strip()
    nets = []
    for line in raw.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return nets


def ip_allowed(ip: str) -> bool:
    """白名单为空时放行（本地/内网默认可用），非空则必须命中。"""
    nets = allowed_networks()
    if not nets:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


# ---------------- 首次启动引导 ----------------

def ensure_admin() -> str | None:
    """没有用户时建一个 admin，返回初始密码（只打印一次）。

    没有这一步，开启鉴权后所有人都进不去，只能手改数据库。
    """
    try:
        with connect() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM app_user").fetchone()["c"]
    except sqlite3.OperationalError:
        return None
    if n > 0:
        return None
    password = secrets.token_urlsafe(9)
    try:
        create_user("admin", password, "管理员", "admin")
    except AuthError:
        return None
    return password
