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
    target_repo     TEXT,                        -- 旧字段：单个 git 仓库（保留兼容）
    target_repos    TEXT,                        -- JSON 数组：改代码用的 git 仓库（可多个）
    fix_state       TEXT,                        -- JSON：按仓库分组的 worktree/branch/diff 状态
    project_id      INTEGER,                     -- 所属项目（project 表），决定默认代码范围与仓库
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

-- 修改轮次：每次「开始修改」落一条，记录 agent 实际改的过程与分析方案的出入。
-- 这是历史记录，驳回/重新修改都不删 —— 方案是一回事，实际改出来是另一回事。
CREATE TABLE IF NOT EXISTS fix_attempt (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id          INTEGER NOT NULL,
    seq               INTEGER NOT NULL,   -- 第几次修改（按 issue 递增）
    provider          TEXT,
    status            TEXT,               -- changed / unchanged / failed / partial
    summary           TEXT,               -- 一句话总结
    actual_root_cause TEXT,               -- 实际根因（与分析不一致时尤其重要）
    deviations        TEXT,               -- JSON 数组：与既定修复思路的出入
    found_issues      TEXT,               -- JSON 数组：修改过程中发现的新问题/隐患
    files             TEXT,               -- JSON 数组：实际改动的文件
    risks             TEXT,               -- JSON 数组：遗留风险
    verification      TEXT,               -- 怎么验证的
    repos             TEXT,               -- JSON：本次各仓库的执行结果概要
    raw_report        TEXT,               -- agent 原始输出（JSON 解析失败时人工排查用）
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fix_attempt_issue ON fix_attempt(issue_id);

-- 项目：一组协作开发的仓库（如 gym = java + vue + 两个小程序）。
-- 仓库天然是"一个项目多个 git 仓库"，所以这里是 1:N。
-- ignored=1 表示用户明确不想跟踪（扫描会跳过），保留是为了别每次扫描又冒出来。
CREATE TABLE IF NOT EXISTS project (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    repos       TEXT,                  -- JSON 数组：仓库绝对路径（各自是独立 git 仓库）
    notes       TEXT,                  -- 给 AI 看的项目说明（可选，会拼进提示词）
    ignored     INTEGER NOT NULL DEFAULT 0,
    sort        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- AI 通道：一个可用的模型入口。两种类型：
--   api   —— OpenAI 兼容端点（官方/中转站都行），带工具循环后能读写文件
--   agent —— 本地 CLI agent（claude / dsh），自带文件工具
CREATE TABLE IF NOT EXISTS channel (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'api',   -- api / agent / mock
    base_url    TEXT,
    api_key     TEXT,
    model       TEXT,
    command     TEXT,                          -- agent 类型：可执行命令
    args        TEXT,                          -- agent 类型：额外参数（空格分隔）
    temperature REAL NOT NULL DEFAULT 0.2,
    max_rounds  INTEGER NOT NULL DEFAULT 25,   -- 工具循环最大轮数
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

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
            ("target_repos", "ALTER TABLE issue ADD COLUMN target_repos TEXT"),
            ("fix_state", "ALTER TABLE issue ADD COLUMN fix_state TEXT"),
            ("project_id", "ALTER TABLE issue ADD COLUMN project_id INTEGER"),
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
