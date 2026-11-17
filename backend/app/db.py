"""SQLite 访问层。单人工具不引 ORM，一张表一条 SQL，查起来直观。"""
import datetime
import sqlite3
from typing import Any

from .config import ALL_STATUS, ATTACH_DIR, DATA_DIR, DB_PATH, DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS issue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    raw_text        TEXT,
    source          TEXT DEFAULT 'wechat',      -- wechat / phone / meeting / manual
    reporter        TEXT,                        -- 谁提的（甲方联系人）
    module          TEXT,                        -- 归属模块，如 会员详情/预约
    status          TEXT NOT NULL DEFAULT '待定性',
    qualify_draft   TEXT,                        -- AI 定性草稿 JSON
    qualify_final   TEXT,                        -- 人工确认后的结构化描述 JSON
    triage          TEXT,                        -- AI 定级 JSON
    severity        TEXT,
    complexity      TEXT,
    priority        TEXT,
    prompt_version  TEXT,
    fix_plan        TEXT,                        -- 「操作解决」生成的方案/差异说明
    code_scopes     TEXT,                        -- JSON 数组：分析用代码目录（可多选）
    target_repo     TEXT,                        -- 单个 git 仓库：改代码用
    fix_state       TEXT,                        -- JSON：worktree/branch/diff 等运行时状态
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    INTEGER NOT NULL,
    filename    TEXT NOT NULL,     -- 原始文件名
    path        TEXT NOT NULL,     -- 相对 data/attachments 的路径
    mime        TEXT,
    size        INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachment_issue ON attachment(issue_id);

CREATE TABLE IF NOT EXISTS ai_run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id      INTEGER NOT NULL,
    kind          TEXT NOT NULL,     -- qualify / triage / fix
    provider      TEXT NOT NULL,
    model         TEXT,
    duration_ms   INTEGER,
    ok            INTEGER NOT NULL,
    error         TEXT,
    output        TEXT,              -- 原始输出（排查用）
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_run_issue ON ai_run(issue_id);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    INTEGER NOT NULL,
    type        TEXT NOT NULL,     -- create / qualify / confirm / triage / status / note
    from_status TEXT,
    to_status   TEXT,
    note        TEXT,
    actor       TEXT DEFAULT 'me',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_issue ON event(issue_id);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # 老库补列：SQLite 没有 IF NOT EXISTS 加列，用 table_info 判断
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(issue)").fetchall()}
        for column, ddl in (
            ("code_scopes", "ALTER TABLE issue ADD COLUMN code_scopes TEXT"),
            ("target_repo", "ALTER TABLE issue ADD COLUMN target_repo TEXT"),
            ("fix_state", "ALTER TABLE issue ADD COLUMN fix_state TEXT"),
        ):
            if column not in existing:
                conn.execute(ddl)
        # 默认配置只补不覆盖，避免每次启动把用户改过的值重置
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO setting(key, value) VALUES (?, ?)", (key, value))


def dict_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def list_rows(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------- settings ----------

def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["value"]


def get_settings() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM setting").fetchall()
    data = dict(DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows})
    return data


def save_settings(values: dict[str, str]) -> None:
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO setting(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def add_event(conn: sqlite3.Connection, issue_id: int, type_: str,
              from_status: str | None = None, to_status: str | None = None,
              note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO event(issue_id, type, from_status, to_status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (issue_id, type_, from_status, to_status, note, now()),
    )


def valid_status(status: str) -> bool:
    return status in ALL_STATUS
