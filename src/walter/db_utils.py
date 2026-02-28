import json
import logging
import sqlite3
import threading
from typing import Any, Mapping
from walter.config import SQLITE_DB_PATH

logger = logging.getLogger(__name__)

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection (created on first call)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
    return conn


def initialize_database() -> None:
    try:
        ddl = """
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL DEFAULT (datetime('now')),
            coin TEXT NOT NULL,
            current_price REAL,
            ema10 REAL,
            ema20 REAL,
            funding_rate_latest REAL,
            funding_rate_avg REAL,
            volatility_24h REAL,
            volume_24h REAL,
            open_interest REAL,
            buy_pressure REAL,
            net_volume REAL,
            raw_snapshot TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_market_snapshots_coin_time ON market_snapshots (coin, captured_at DESC);

        CREATE TABLE IF NOT EXISTS account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            account_value REAL,
            total_ntl_pos REAL,
            total_raw_usd REAL,
            total_margin_used REAL,
            withdrawable REAL,
            raw_snapshot TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_account_snapshots_captured_at ON account_snapshots (captured_at DESC);

        CREATE TABLE IF NOT EXISTS news_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL DEFAULT (datetime('now')),
            summary TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_news_summaries_captured_at ON news_summaries (captured_at DESC);

        CREATE TABLE IF NOT EXISTS order_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            coin TEXT NOT NULL,
            is_buy INTEGER NOT NULL,
            size REAL,
            leverage INTEGER,
            tif TEXT,
            decision_action TEXT NOT NULL,
            thinking TEXT,
            market_snapshot_id INTEGER REFERENCES market_snapshots (id) ON DELETE SET NULL,
            account_snapshot_id INTEGER REFERENCES account_snapshots (id) ON DELETE SET NULL,
            news_snapshot_id INTEGER REFERENCES news_summaries (id) ON DELETE SET NULL,
            order_payload TEXT,
            order_placed INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_order_attempts_coin_time ON order_attempts (coin, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_order_attempts_snapshot_id ON order_attempts (market_snapshot_id);
        """

        conn = _get_conn()
        conn.executescript(ddl)
        conn.commit()
    except Exception as e:
        logger.critical("A database error occurred: %s", e)
        logger.critical("Exiting gracefully")
        exit(1)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN with None for JSON serialization."""
    if isinstance(obj, float):
        return None if obj != obj else obj  # obj != obj covers NaN
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_for_json(v) for v in obj)
    return obj


def save_market_snapshot(snapshot: Mapping[str, Any], captured_at) -> int:
    data = dict(snapshot)

    # Sanitize data for JSON
    sanitized_data = _sanitize_for_json(data)

    sql = """
    INSERT INTO market_snapshots (
    captured_at,
        coin, current_price, ema10, ema20, funding_rate_latest,
        funding_rate_avg, volatility_24h, volume_24h,
        open_interest, buy_pressure, net_volume, raw_snapshot
    ) VALUES (:captured_at,:coin, :current_price, :ema10, :ema20, :funding_rate_latest,
              :funding_rate_avg, :volatility_24h, :volume_24h,
              :open_interest, :buy_pressure, :net_volume, :raw_snapshot);
    """
    params = {
        "captured_at": str(captured_at),
        "coin": data.get("coin"),
        "current_price": data.get("current_price"),
        "ema10": data.get("ema10"),
        "ema20": data.get("ema20"),
        "funding_rate_latest": data.get("funding_rate_latest"),
        "funding_rate_avg": data.get("funding_rate_avg"),
        "volatility_24h": data.get("volatility_24h"),
        "volume_24h": data.get("volume_24h"),
        "open_interest": data.get("open_interest"),
        "buy_pressure": data.get("buy_pressure"),
        "net_volume": data.get("net_volume"),
        "raw_snapshot": json.dumps(sanitized_data),
    }
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def save_order_attempt(
    *,
    created_at,
    coin: str,
    is_buy: bool,
    size: float | None,
    leverage: int | None,
    tif: str | None,
    decision_action: str,
    thinking: str | None = None,
    market_snapshot_id: int | None,
    account_snapshot_id: int | None = None,
    news_snapshot_id: int | None = None,
    order_payload: Mapping[str, Any] | None,  # Updated type hint
    order_placed: Any | None = None,
) -> int:
    sanitized_payload = _sanitize_for_json(order_payload) if order_payload else None

    sql = """
    INSERT INTO order_attempts (
    created_at,
        coin, is_buy, size, leverage, tif,
        decision_action, thinking,
        market_snapshot_id, account_snapshot_id, news_snapshot_id, order_payload, order_placed
    ) VALUES (:created_at,:coin, :is_buy, :size, :leverage, :tif,
              :decision_action, :thinking,
              :market_snapshot_id, :account_snapshot_id, :news_snapshot_id, :order_payload, :order_placed);
    """
    params = {
        "created_at": str(created_at),
        "coin": coin,
        "is_buy": int(is_buy),
        "size": size,
        "leverage": leverage,
        "tif": tif,
        "decision_action": decision_action,
        "thinking": thinking,
        "market_snapshot_id": market_snapshot_id,
        "account_snapshot_id": account_snapshot_id,
        "news_snapshot_id": news_snapshot_id,
        "order_payload": json.dumps(sanitized_payload) if sanitized_payload else None,
        "order_placed": int(order_placed) if order_placed is not None else None,
    }
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def save_account_snapshot(captured_at, snapshot: Mapping[str, Any]) -> int:

    # Extract fields from marginSummary
    margin_summary = snapshot.get("marginSummary", {})
    account_value = margin_summary.get("accountValue")
    total_ntl_pos = margin_summary.get("totalNtlPos")
    total_raw_usd = margin_summary.get("totalRawUsd")
    total_margin_used = margin_summary.get("totalMarginUsed")
    withdrawable = snapshot.get("withdrawable")

    sanitized_snapshot = _sanitize_for_json(snapshot)

    sql = """
    INSERT INTO account_snapshots (
        captured_at, account_value, total_ntl_pos,
        total_raw_usd, total_margin_used, withdrawable, raw_snapshot
    ) VALUES (
        :captured_at, :account_value, :total_ntl_pos,
        :total_raw_usd, :total_margin_used, :withdrawable, :raw_snapshot
    );
    """
    params = {
        "captured_at": str(captured_at),
        "account_value": account_value,
        "total_ntl_pos": total_ntl_pos,
        "total_raw_usd": total_raw_usd,
        "total_margin_used": total_margin_used,
        "withdrawable": withdrawable,
        "raw_snapshot": json.dumps(sanitized_snapshot),
    }

    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def get_recent_decisions(limit: int = 10) -> list[dict]:
    """Fetches the most recent order attempts with their context."""
    sql = """
    SELECT
        oa.created_at,
        oa.decision_action,
        oa.thinking,
        ms.current_price,
        acs.withdrawable
    FROM order_attempts oa
    LEFT JOIN market_snapshots ms ON oa.market_snapshot_id = ms.id
    LEFT JOIN account_snapshots acs ON oa.account_snapshot_id = acs.id
    ORDER BY oa.created_at DESC
    LIMIT :limit;
    """
    conn = _get_conn()
    cur = conn.execute(sql, {"limit": limit})
    rows = [dict(row) for row in cur.fetchall()]

    # We need to reverse them to be in chronological order for the LLM
    return list(reversed(rows))


def save_news_snapshot(summary: Mapping[str, Any], captured_at) -> int:
    sql = """
    INSERT INTO news_summaries (captured_at, summary) VALUES (:captured_at, :summary);
    """
    params = {"summary": json.dumps(summary), "captured_at": str(captured_at)}
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid
