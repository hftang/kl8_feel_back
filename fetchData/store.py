#!/usr/bin/env python3
"""SQLite 持久化：历史开奖 + 推荐记录 + 事后命中评估 + 回测运行归档。

设计原则：
- 所有写入都是幂等的（INSERT OR IGNORE / UPSERT）
- 读接口返回与 kl8tool.parse_xml_data 相同形状的 dict 列表，调用方零改动
- 无外部依赖，只用 stdlib sqlite3
"""

import os
import sqlite3
import threading
from datetime import datetime

# 默认与代码同目录；容器环境可通过 KL8_DB_PATH 指向挂载卷实现持久化
_DB_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kl8.db")
DB_PATH = os.environ.get("KL8_DB_PATH", _DB_DEFAULT)

_db_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    period       TEXT PRIMARY KEY,
    draw_date    TEXT NOT NULL,
    draw_time    TEXT,
    numbers_csv  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date);

CREATE TABLE IF NOT EXISTS recommendations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    target_period TEXT,
    strategy_id   TEXT NOT NULL,
    count         INTEGER NOT NULL,
    numbers_csv   TEXT NOT NULL,
    seed          INTEGER,
    source        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_target ON recommendations(target_period, strategy_id);

CREATE TABLE IF NOT EXISTS recommendation_hits (
    recommendation_id INTEGER PRIMARY KEY REFERENCES recommendations(id),
    hits              INTEGER NOT NULL,
    evaluated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT NOT NULL,
    count        INTEGER NOT NULL,
    window       INTEGER NOT NULL,
    n_periods    INTEGER NOT NULL,
    params_json  TEXT,
    summary_json TEXT
);
"""


def _conn(db_path=None):
    return sqlite3.connect(db_path or DB_PATH)


def init_db(db_path=None):
    """幂等启动初始化。"""
    with _db_lock, _conn(db_path) as c:
        c.executescript(SCHEMA)


def upsert_draws(rows, db_path=None):
    """批量插入历史开奖（幂等，主键 period 重复即忽略）。

    rows: iterable of dict, 每个至少含 period/date/numbers（与 parse_xml_data 输出兼容）。
    返回本次实际新增行数。
    """
    inserted = 0
    with _db_lock, _conn(db_path) as c:
        for r in rows:
            period = str(r["period"])
            date = r.get("date") or r.get("draw_date") or ""
            draw_time = r.get("draw_time") or ""
            nums = r.get("numbers") or []
            # 兼容 str/int
            csv = ",".join(str(int(x)) for x in nums)
            cur = c.execute(
                "INSERT OR IGNORE INTO draws (period, draw_date, draw_time, numbers_csv) VALUES (?, ?, ?, ?)",
                (period, date, draw_time, csv),
            )
            inserted += cur.rowcount
        c.commit()
    return inserted


def latest_period(db_path=None):
    with _db_lock, _conn(db_path) as c:
        row = c.execute("SELECT period FROM draws ORDER BY period DESC LIMIT 1").fetchone()
    return row[0] if row else None


def draw_count(db_path=None):
    with _db_lock, _conn(db_path) as c:
        return c.execute("SELECT COUNT(*) FROM draws").fetchone()[0]


def get_periods_set(db_path=None):
    """返回数据库中所有期号的集合，用于快速判断某期是否已存在"""
    with _db_lock, _conn(db_path) as c:
        rows = c.execute("SELECT period FROM draws").fetchall()
    return {row[0] for row in rows}


def all_draws_desc(limit=None, db_path=None):
    """返回与 parse_xml_data 相同形状的 dict 列表（最新在前）。

    numbers 字段仍是 str 列表（老代码期望 [str, ...]）。
    """
    q = "SELECT period, draw_date, numbers_csv FROM draws ORDER BY period DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    with _db_lock, _conn(db_path) as c:
        rows = c.execute(q).fetchall()
    out = []
    for period, date, csv in rows:
        out.append({
            "period": period,
            "date": date,
            "numbers": csv.split(",") if csv else [],
        })
    return out


def record_recommendation(target_period, strategy_id, count, numbers, seed=None,
                          source="live", db_path=None):
    """记录一次推荐。返回新行 id。"""
    csv = ",".join(str(int(x)) for x in numbers)
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _db_lock, _conn(db_path) as c:
        cur = c.execute(
            "INSERT INTO recommendations (created_at, target_period, strategy_id, count, numbers_csv, seed, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, target_period, strategy_id, int(count), csv, seed, source),
        )
        c.commit()
        return cur.lastrowid


def record_recommendations_batch(recs, target_period, source="live", db_path=None):
    """批量记录一次 recommend() 的所有策略输出。

    recs: list of dict, 每个至少含 {id, numbers}。
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _db_lock, _conn(db_path) as c:
        for r in recs:
            csv = ",".join(str(int(x)) for x in r["numbers"])
            c.execute(
                "INSERT INTO recommendations (created_at, target_period, strategy_id, count, numbers_csv, seed, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, target_period, r["id"], len(r["numbers"]), csv, None, source),
            )
        c.commit()


def evaluate_pending_recommendations(db_path=None):
    """对已开奖的 target_period 里、还没有 hits 记录的推荐补算命中数。

    返回本次新评估的行数。
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _db_lock, _conn(db_path) as c:
        rows = c.execute("""
            SELECT r.id, r.numbers_csv, d.numbers_csv
              FROM recommendations r
              JOIN draws d ON d.period = r.target_period
         LEFT JOIN recommendation_hits h ON h.recommendation_id = r.id
             WHERE h.recommendation_id IS NULL
        """).fetchall()
        n = 0
        for rec_id, rec_csv, draw_csv in rows:
            picks = {int(x) for x in rec_csv.split(",") if x}
            wins = {int(x) for x in draw_csv.split(",") if x}
            hits = len(picks & wins)
            c.execute(
                "INSERT INTO recommendation_hits (recommendation_id, hits, evaluated_at) VALUES (?, ?, ?)",
                (rec_id, hits, now),
            )
            n += 1
        c.commit()
    return n


def recommendations_history(limit=100, db_path=None):
    """联合查询：历史推荐 + 对应开奖 + 已评估的命中数。返回最新在前。"""
    q = """
      SELECT r.id, r.created_at, r.target_period, r.strategy_id, r.count,
             r.numbers_csv, r.source,
             d.numbers_csv AS draw_csv,
             h.hits
        FROM recommendations r
   LEFT JOIN draws d ON d.period = r.target_period
   LEFT JOIN recommendation_hits h ON h.recommendation_id = r.id
    ORDER BY r.id DESC
       LIMIT ?
    """
    with _db_lock, _conn(db_path) as c:
        rows = c.execute(q, (int(limit),)).fetchall()
    out = []
    for rid, created, target, sid, cnt, rec_csv, source, draw_csv, hits in rows:
        out.append({
            "id": rid,
            "created_at": created,
            "target_period": target,
            "strategy_id": sid,
            "count": cnt,
            "picks": [int(x) for x in rec_csv.split(",") if x],
            "winning": [int(x) for x in draw_csv.split(",")] if draw_csv else None,
            "hits": hits,
            "source": source,
        })
    return out


def record_backtest_run(count, window, n_periods, params_json, summary_json, db_path=None):
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _db_lock, _conn(db_path) as c:
        c.execute(
            "INSERT INTO backtest_runs (run_at, count, window, n_periods, params_json, summary_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, count, window, n_periods, params_json, summary_json),
        )
        c.commit()
