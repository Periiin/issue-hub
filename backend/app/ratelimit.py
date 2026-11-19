"""限流与防爆破。

三档防护，各管一件事：

1. **登录尝试限流**（IP 维度）：每 IP 每分钟最多 N 次登录请求。
   挡住「一个 IP 狂刷」，不关心密码对不对。

2. **登录失败锁定**（IP + 用户名）：连续失败 N 次锁 M 分钟。
   挡住「慢慢试密码」，失败才计数，成功清零。

3. **通用 API 限流**（用户/IP 维度）：每分钟请求数上限。
   挡住脚本刷接口（尤其是 `开始修改` 这种烧 token 的）。

为什么用 SQLite 而不是内存：
- 服务可能被重启，内存计数一重启就清零，攻击者能靠重启绕过（虽然不现实）
- 以后加 `--workers` 多进程时，内存计数各自为政会失真
- SQLite 的写入量在这个规模（单人/小团队）完全不是瓶颈

计数用「固定窗口」而不是滑动窗口：实现简单、可预测，对防爆破够用。
滑动窗口要存每次请求的时间戳，表会膨胀得很快，收益不明显。
"""
import sqlite3
from datetime import datetime, timedelta

from .db import connect, get_settings, now

# 默认阈值（可在设置里覆盖）
DEFAULT_LOGIN_PER_IP = 10        # 每 IP 每分钟登录尝试
DEFAULT_FAIL_LIMIT = 5           # 连续失败几次锁定
DEFAULT_FAIL_LOCK_MIN = 15       # 锁多久
DEFAULT_API_PER_MIN = 300        # 每分钟 API 请求
DEFAULT_HEAVY_PER_HOUR = 30      # 重操作（改代码/分析）每小时次数

# 重操作：会跑 AI、烧 token、动代码
HEAVY_PATHS = (
    "/fix/apply", "/fix", "/qualify", "/triage", "/channels/models",
    "/channels/", "/test", "/sync",
)


class RateLimited(RuntimeError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


def _cfg_int(key: str, default: int) -> int:
    raw = (get_settings().get(key) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _window_start(minutes: int = 1) -> str:
    """固定窗口起点：按分钟/小时对齐，避免每次请求都算新窗口。"""
    dt = datetime.now()
    if minutes >= 60:
        dt = dt.replace(minute=0, second=0, microsecond=0)
    else:
        dt = dt.replace(second=0, microsecond=0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 计数 ----------------

def hit(bucket: str, key: str, window_minutes: int = 1) -> int:
    """记一次并返回窗口内的累计次数。

    bucket: 用途分类（login_ip / login_fail / api / heavy）
    key:    维度值（IP、用户名、用户 id）
    """
    window = _window_start(window_minutes)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO rate_counter(bucket, key, window_start, count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(bucket, key, window_start) DO UPDATE SET count = count + 1",
                (bucket, key, window))
            row = conn.execute(
                "SELECT count FROM rate_counter WHERE bucket = ? AND key = ? AND window_start = ?",
                (bucket, key, window)).fetchone()
        return row["count"] if row else 1
    except sqlite3.OperationalError:
        # 表还没建：放行（不能因为限流设施故障把正常用户挡在外面）
        return 0


def peek(bucket: str, key: str, window_minutes: int = 1) -> int:
    """只看不记。"""
    window = _window_start(window_minutes)
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT count FROM rate_counter WHERE bucket = ? AND key = ? AND window_start = ?",
                (bucket, key, window)).fetchone()
        return row["count"] if row else 0
    except sqlite3.OperationalError:
        return 0


def reset(bucket: str, key: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM rate_counter WHERE bucket = ? AND key = ?", (bucket, key))


# ---------------- 锁定 ----------------

def lock_key(ip: str, username: str) -> str:
    """IP + 用户名组合。只按 IP 会误伤同办公室的正常用户；
    只按用户名会让攻击者换名字继续刷。"""
    return f"{ip}|{(username or '').strip().lower()}"


def is_locked(ip: str, username: str) -> tuple[bool, int]:
    """是否被锁。返回 (锁住, 剩余秒数)。"""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT locked_until FROM rate_lock WHERE lock_key = ?",
                (lock_key(ip, username),)).fetchone()
    except sqlite3.OperationalError:
        return False, 0
    if not row:
        return False, 0
    try:
        until = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False, 0
    remain = int((until - datetime.now()).total_seconds())
    return (True, remain) if remain > 0 else (False, 0)


def record_failure(ip: str, username: str) -> dict:
    """记一次登录失败；达到阈值就上锁。返回 {fails, locked, remain}。"""
    limit = _cfg_int("rate.fail_limit", DEFAULT_FAIL_LIMIT)
    lock_min = _cfg_int("rate.fail_lock_minutes", DEFAULT_FAIL_LOCK_MIN)
    key = lock_key(ip, username)
    fails = hit("login_fail", key, window_minutes=60 * 24)   # 24 小时窗口内累计
    if fails >= limit:
        until = (datetime.now() + timedelta(minutes=lock_min)).strftime("%Y-%m-%d %H:%M:%S")
        with connect() as conn:
            conn.execute(
                "INSERT INTO rate_lock(lock_key, locked_until, reason, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(lock_key) DO UPDATE SET locked_until = excluded.locked_until, "
                "reason = excluded.reason",
                (key, until, f"{fails} 次密码错误", now()))
        return {"fails": fails, "locked": True, "remain": lock_min * 60}
    return {"fails": fails, "locked": False, "remain": 0}


def clear_failures(ip: str, username: str) -> None:
    """登录成功后清掉失败计数与锁。"""
    key = lock_key(ip, username)
    with connect() as conn:
        conn.execute("DELETE FROM rate_counter WHERE bucket = 'login_fail' AND key = ?", (key,))
        conn.execute("DELETE FROM rate_lock WHERE lock_key = ?", (key,))


def list_locks() -> list[dict]:
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT lock_key, locked_until, reason, created_at FROM rate_lock "
                "ORDER BY locked_until DESC").fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = dict(r)
        try:
            until = datetime.strptime(d["locked_until"], "%Y-%m-%d %H:%M:%S")
            d["active"] = until > datetime.now()
            d["remainSeconds"] = max(0, int((until - datetime.now()).total_seconds()))
        except ValueError:
            d["active"] = False
            d["remainSeconds"] = 0
        out.append(d)
    return out


def unlock(ip_username: str) -> None:
    """手工解锁（管理员用）。参数是 lock_key 原文（ip|username）。"""
    with connect() as conn:
        conn.execute("DELETE FROM rate_lock WHERE lock_key = ?", (ip_username,))
        conn.execute("DELETE FROM rate_counter WHERE bucket = 'login_fail' AND key = ?", (ip_username,))


# ---------------- 对外校验 ----------------

def check_login(ip: str, username: str) -> None:
    """登录前调用。超限或被锁直接抛 RateLimited。"""
    if (get_settings().get("rate.enabled") or "1").strip() not in ("1", "true", "yes"):
        return

    locked, remain = is_locked(ip, username)
    if locked:
        raise RateLimited(
            f"密码错误次数过多，请 {max(1, remain // 60)} 分钟后再试", retry_after=remain)

    limit = _cfg_int("rate.login_per_ip", DEFAULT_LOGIN_PER_IP)
    count = hit("login_ip", ip, window_minutes=1)
    if count > limit:
        raise RateLimited(
            f"登录请求过于频繁（每分钟 {limit} 次），请稍后再试", retry_after=60)


def is_heavy_path(path: str) -> bool:
    return any(p in path for p in HEAVY_PATHS)


def check_api(user_id: int | None, ip: str, path: str) -> None:
    """通用 API 限流。重操作单独一档（每小时），普通请求按分钟。"""
    if (get_settings().get("rate.enabled") or "1").strip() not in ("1", "true", "yes"):
        return
    # 静态与登录接口不在这里管
    if path.startswith("/api/auth/login"):
        return

    who = f"u{user_id}" if user_id else f"ip:{ip}"

    if is_heavy_path(path):
        limit = _cfg_int("rate.heavy_per_hour", DEFAULT_HEAVY_PER_HOUR)
        count = hit("heavy", who, window_minutes=60)
        if count > limit:
            raise RateLimited(
                f"这类操作每小时最多 {limit} 次（改代码/分析会消耗额度），请稍后再试",
                retry_after=3600)

    limit = _cfg_int("rate.api_per_min", DEFAULT_API_PER_MIN)
    count = hit("api", who, window_minutes=1)
    if count > limit:
        raise RateLimited(f"请求过于频繁（每分钟 {limit} 次）", retry_after=60)


# ---------------- 清理 ----------------

def purge_old(days: int = 2) -> int:
    """删掉过期窗口的计数，避免表无限增长。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        c1 = conn.execute("DELETE FROM rate_counter WHERE window_start < ?", (cutoff,)).rowcount
        c2 = conn.execute("DELETE FROM rate_lock WHERE locked_until < ?", (cutoff,)).rowcount
    return c1 + c2


def status() -> dict:
    """给前端看的当前配置与锁列表。"""
    return {
        "enabled": (get_settings().get("rate.enabled") or "1").strip() in ("1", "true", "yes"),
        "loginPerIpPerMin": _cfg_int("rate.login_per_ip", DEFAULT_LOGIN_PER_IP),
        "failLimit": _cfg_int("rate.fail_limit", DEFAULT_FAIL_LIMIT),
        "failLockMinutes": _cfg_int("rate.fail_lock_minutes", DEFAULT_FAIL_LOCK_MIN),
        "apiPerMin": _cfg_int("rate.api_per_min", DEFAULT_API_PER_MIN),
        "heavyPerHour": _cfg_int("rate.heavy_per_hour", DEFAULT_HEAVY_PER_HOUR),
        "locks": list_locks(),
    }
