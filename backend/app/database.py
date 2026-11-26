# -*- coding: utf-8 -*-
"""SQLite 连接与建表。"""
import sqlite3
import threading
from . import config

_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # 写锁竞争时等待最多 5 秒，避免多线程并发写直接抛 database is locked
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS policies (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            level         TEXT NOT NULL,             -- national/provincial/municipal
            source_name   TEXT NOT NULL,
            column_key    TEXT,
            column_name   TEXT,
            title         TEXT NOT NULL,
            doc_no        TEXT,
            url           TEXT NOT NULL UNIQUE,
            publish_date  TEXT,
            summary       TEXT,
            content       TEXT,
            content_hash  TEXT,
            status        TEXT DEFAULT 'active',
            fetched_at    TEXT DEFAULT (datetime('now','localtime')),
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_pol_level    ON policies(level);
        CREATE INDEX IF NOT EXISTS idx_pol_date     ON policies(publish_date DESC);

        CREATE TABLE IF NOT EXISTS analysis (
            policy_id      INTEGER PRIMARY KEY,
            keywords       TEXT,                  -- JSON array
            topic_tags     TEXT,                  -- JSON array
            applicable_to  TEXT,                  -- JSON array
            effective_date TEXT,
            relevance      INTEGER DEFAULT 0,
            relevance_note TEXT,
            key_points     TEXT,                  -- JSON array
            ai_summary     TEXT,
            ai_type        TEXT DEFAULT 'rule',    -- rule / llm
            policy_type    TEXT,                  -- 通知/办法/细则/解读/公示/其他
            validity       TEXT,                  -- 现行有效/试行/征求意见/已废止/未知
            core_elements  TEXT,                  -- JSON array[{label,value}] 核心要素
            actions        TEXT,                  -- JSON array 基层落地动作
            risks          TEXT,                  -- JSON array 合规风险红线
            standards      TEXT,                  -- JSON array 待遇/支付标准
            impact_level   TEXT,                  -- 对基层整体影响：高/中/低/未涉及
            impact_matrix  TEXT,                  -- JSON array[{dimension,level,note}] 分维度影响矩阵
            parent_basis   TEXT,                  -- 上位依据/政策层级衔接
            city_impact    TEXT,                  -- 对市级/经办层面影响
            key_data       TEXT,                  -- JSON array 原文关键数据（数字/比例/日期/数量）
            created_at     TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(policy_id) REFERENCES policies(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS exposures (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            level          TEXT NOT NULL,
            source_name    TEXT NOT NULL,
            kind           TEXT NOT NULL,          -- case=违规案例 / exit=退出协议
            org_name       TEXT,
            org_type       TEXT,                  -- 医疗机构 / 零售药店 / 其他
            region         TEXT,
            problem        TEXT,
            penalty        TEXT,
            exit_status    TEXT,                  -- 解除协议 / 中止协议 / 暂停协议 / 主动退出 / 未退出
            exit_type      TEXT,                  -- 被动 / 主动 / —
            amount         TEXT,
            publish_date   TEXT,
            title          TEXT,
            url            TEXT NOT NULL,
            summary        TEXT,
            fetched_at     TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(url, org_name)
        );
        CREATE INDEX IF NOT EXISTS idx_exp_level ON exposures(level);
        CREATE INDEX IF NOT EXISTS idx_exp_kind  ON exposures(kind);
        CREATE INDEX IF NOT EXISTS idx_exp_date  ON exposures(publish_date DESC);

        CREATE TABLE IF NOT EXISTS crawl_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at      TEXT DEFAULT (datetime('now','localtime')),
            level       TEXT,
            source_name TEXT,
            found       INTEGER DEFAULT 0,
            added       INTEGER DEFAULT 0,
            status      TEXT,
            message     TEXT,
            duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    # 老库迁移：补齐 analysis 新增列
    existing = {r["name"] for r in cur.execute("PRAGMA table_info(analysis)")}
    for col, ddl in (
        ("policy_type", "TEXT"),
        ("validity", "TEXT"),
        ("core_elements", "TEXT"),
        ("actions", "TEXT"),
        ("risks", "TEXT"),
        ("standards", "TEXT"),
        ("impact_level", "TEXT"),
        ("impact_matrix", "TEXT"),
        ("parent_basis", "TEXT"),
        ("city_impact", "TEXT"),
        ("key_data", "TEXT"),
    ):
        if col not in existing:
            cur.execute(f"ALTER TABLE analysis ADD COLUMN {col} {ddl}")
    # 默认设置：LLM 开关以进程环境/显式配置为准；仓库干净库默认规则解读，避免云端 runner 误读本地旧设置。
    defaults = {
        "schedule": config.DEFAULT_SCHEDULE,
        "daily_hour": str(config.DAILY_HOUR),
        "weekly_weekday": str(config.WEEKLY_WEEKDAY),
        "weekly_hour": str(config.WEEKLY_HOUR),
        "llm_enabled": "1" if config.LLM_ENABLED else "0",
        "llm_base_url": config.LLM_BASE_URL,
        "llm_api_key": config.LLM_API_KEY,
        "llm_model": config.LLM_MODEL,
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()
