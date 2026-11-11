"""SQLite 存储层。

表的分工（盲审的关键在这里）：

- item / variant：评审能间接看到的内容（brief 的公开部分、规整后的文本）。
- variant_source：揭盲表。来源类型、候选 id、skill git hash、模型、参数都只在这里，
  评审接口的任何查询都不 JOIN 这张表。
- task：每个评审、每道题一行。左右位置、展示顺序、对照题类型都在服务端定好并记录。
- judgment：评审作答。
- rater：评审，以及分析脚本回写的校准分、位置偏差、自洽度。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "workbench.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS item (
    id            TEXT PRIMARY KEY,           -- brief id，例如 dlg-001 / vo-001
    line          TEXT NOT NULL CHECK (line IN ('台词', '口播')),
    brief_json    TEXT NOT NULL,              -- 完整 brief（含 source，管理员可见）
    public_json   TEXT NOT NULL,              -- 去掉 source 后给评审看的部分
    is_example    INTEGER NOT NULL DEFAULT 0, -- 1 = 示例 / 假数据
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS variant (
    id            INTEGER PRIMARY KEY,
    item_id       TEXT NOT NULL REFERENCES item(id),
    raw_text      TEXT NOT NULL,
    display_text  TEXT NOT NULL,              -- 统一格式后的文本，评审只看这个
    char_len      INTEGER NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS variant_item ON variant(item_id);

-- 揭盲表：评审接口永远不读这张表。
CREATE TABLE IF NOT EXISTS variant_source (
    variant_id    INTEGER PRIMARY KEY REFERENCES variant(id),
    source_type   TEXT NOT NULL CHECK (source_type IN
                   ('human', 'raw_ai_baseline', 'oneline_baseline', 'candidate', 'gold_bad')),
    source_label  TEXT NOT NULL,              -- 分析时的“系统”名：human / raw_ai_baseline / 候选 id ...
    skill_git_hash TEXT,
    model         TEXT,
    params_json   TEXT,
    sample_idx    INTEGER NOT NULL DEFAULT 0,
    imported_from TEXT
);

CREATE TABLE IF NOT EXISTS rater (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    code          TEXT NOT NULL UNIQUE,       -- 评审登录码（本机用，非密码）
    expertise     TEXT,
    is_simulated  INTEGER NOT NULL DEFAULT 0,
    calibration_score REAL,                   -- 以下由 analyze --write-back 回写
    position_bias REAL,
    self_consistency REAL,
    stats_updated_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batch (
    id            INTEGER PRIMARY KEY,
    rater_id      INTEGER NOT NULL REFERENCES rater(id),
    line          TEXT NOT NULL,
    seed          INTEGER NOT NULL,           -- 随机种子，记下来便于复现
    control_ratio REAL NOT NULL,
    params_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task (
    id            INTEGER PRIMARY KEY,
    public_id     TEXT NOT NULL UNIQUE,       -- 评审看到的不透明 id
    batch_id      INTEGER NOT NULL REFERENCES batch(id),
    rater_id      INTEGER NOT NULL REFERENCES rater(id),
    kind          TEXT NOT NULL CHECK (kind IN ('single_turing', 'pairwise_pref')),
    item_id       TEXT NOT NULL REFERENCES item(id),
    left_variant_id  INTEGER NOT NULL REFERENCES variant(id),   -- 展示在 A 位
    right_variant_id INTEGER REFERENCES variant(id),            -- 展示在 B 位（单篇题为空）
    swapped       INTEGER NOT NULL DEFAULT 0, -- 1 = A 位放的是 id 较大的那篇
    display_order INTEGER NOT NULL,
    control_type  TEXT CHECK (control_type IN ('human_anchor', 'ai_honeypot', 'repeat', 'gold')),
    is_gold       INTEGER NOT NULL DEFAULT 0,
    gold_expected TEXT,                       -- 金标题的正确答案：A / B
    is_repeat_of  INTEGER REFERENCES task(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS task_rater ON task(rater_id, batch_id, display_order);

CREATE TABLE IF NOT EXISTS judgment (
    id            INTEGER PRIMARY KEY,
    task_id       INTEGER NOT NULL UNIQUE REFERENCES task(id),
    rater_id      INTEGER NOT NULL REFERENCES rater(id),
    ai_conf_a     INTEGER CHECK (ai_conf_a BETWEEN 1 AND 5),   -- A 位“像 AI 写的”置信 1–5
    ai_conf_b     INTEGER CHECK (ai_conf_b BETWEEN 1 AND 5),
    preference    TEXT CHECK (preference IN ('A', 'B', 'tie', 'both_bad')),
    tags_json     TEXT NOT NULL DEFAULT '{}', -- {"A": [...], "B": [...]}
    spans_json    TEXT NOT NULL DEFAULT '[]', -- [{side, start, end, text, tag}]
    reason        TEXT NOT NULL DEFAULT '',
    duration_ms   INTEGER NOT NULL,
    too_fast      INTEGER NOT NULL DEFAULT 0,
    revisions     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def db_path() -> Path:
    return Path(os.environ.get("WB_DB", DEFAULT_DB))


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
