import json
import os
from typing import Any, Mapping
from psycopg import connect
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)
PG_CONN_STR = os.getenv("PG_CONN_STR")
if not PG_CONN_STR:
    raise RuntimeError("PG_CONN_STR environment variable is not set")

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(PG_CONN_STR, kwargs={"row_factory": dict_row})
    return _pool


def ensure_schema() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        coin TEXT NOT NULL,
        current_price DOUBLE PRECISION,
        ema10 DOUBLE PRECISION,
        ema20 DOUBLE PRECISION,
        funding_rate_latest DOUBLE PRECISION,
        funding_rate_avg DOUBLE PRECISION,
        volatility_24h DOUBLE PRECISION,
        volume_24h DOUBLE PRECISION,
        open_interest DOUBLE PRECISION,
        buy_pressure DOUBLE PRECISION,
        net_volume DOUBLE PRECISION,
        raw_snapshot JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_market_snapshots_coin_time
        ON market_snapshots (coin, captured_at DESC);

    CREATE TABLE IF NOT EXISTS order_attempts (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        coin TEXT NOT NULL,
        is_buy BOOLEAN NOT NULL,
        size DOUBLE PRECISION,
        leverage INTEGER,
        tif TEXT,
        decision_action TEXT NOT NULL,
        decision_confidence DOUBLE PRECISION,
        snapshot_id BIGINT REFERENCES market_snapshots(id) ON DELETE SET NULL,
        account_snapshot_id BIGINT REFERENCES account_snapshots(id) ON DELETE SET NULL,
        order_payload JSONB,
        order_placed BOOL
    );
    CREATE INDEX IF NOT EXISTS idx_order_attempts_coin_time
        ON order_attempts (coin, created_at DESC);
        
    CREATE INDEX IF NOT EXISTS idx_order_attempts_snapshot_id
    ON order_attempts (snapshot_id);

    CREATE TABLE IF NOT EXISTS account_snapshots (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        captured_at TIMESTAMPTZ NOT NULL,
        account_value DOUBLE PRECISION,
        total_ntl_pos DOUBLE PRECISION,
        total_raw_usd DOUBLE PRECISION,
        total_margin_used DOUBLE PRECISION,
        withdrawable DOUBLE PRECISION,
        raw_snapshot JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_account_snapshots_captured_at
        ON account_snapshots (captured_at DESC);
    """
    with get_pool().connection() as conn:
        conn.execute(ddl)
        conn.commit()


def save_snapshot(snapshot: Mapping[str, Any], captured_at) -> int:
    data = dict(snapshot)
    open_interest = data.get("open_interest")
    if isinstance(open_interest, (list, tuple)):
        open_interest = open_interest[0] if open_interest else None
    sql = """
    INSERT INTO market_snapshots (
    captured_at,
        coin, current_price, ema10, ema20, funding_rate_latest,
        funding_rate_avg, volatility_24h, volume_24h,
        open_interest, buy_pressure, net_volume, raw_snapshot
    ) VALUES (%(captured_at)s,%(coin)s, %(current_price)s, %(ema10)s, %(ema20)s, %(funding_rate_latest)s,
              %(funding_rate_avg)s, %(volatility_24h)s, %(volume_24h)s,
              %(open_interest)s, %(buy_pressure)s, %(net_volume)s, %(raw_snapshot)s)
    RETURNING id;
    """
    params = {
        "captured_at": captured_at,
        "coin": data.get("coin"),
        "current_price": data.get("current_price"),
        "ema10": data.get("ema10"),
        "ema20": data.get("ema20"),
        "funding_rate_latest": data.get("funding_rate_latest"),
        "funding_rate_avg": data.get("funding_rate_avg"),
        "volatility_24h": data.get("volatility_24h"),
        "volume_24h": data.get("volume_24h"),
        "open_interest": open_interest,
        "buy_pressure": data.get("buy_pressure"),
        "net_volume": data.get("net_volume"),
        "raw_snapshot": json.dumps(data),
    }
    with get_pool().connection() as conn:
        cur = conn.execute(sql, params)
        snapshot_id = cur.fetchone()["id"]
        conn.commit()
        return snapshot_id


def save_order_attempt(
    *,
    created_at,
    coin: str,
    is_buy: bool,
    size: float | None,
    leverage: int | None,
    tif: str | None,
    decision_action: str,
    decision_confidence: float,
    snapshot_id: int | None,
    account_snapshot_id: int | None = None,
    order_payload: Mapping[str, Any] | None,  # Updated type hint
    order_placed: Any | None = None,
) -> int:
    sql = """
    INSERT INTO order_attempts (
    created_at,
        coin, is_buy, size, leverage, tif,
        decision_action, decision_confidence,
        snapshot_id, account_snapshot_id, order_payload, order_placed
    ) VALUES (%(created_at)s,%(coin)s, %(is_buy)s, %(size)s, %(leverage)s, %(tif)s,
              %(decision_action)s, %(decision_confidence)s,
              %(snapshot_id)s, %(account_snapshot_id)s, %(order_payload)s, %(order_placed)s)
    RETURNING id;
    """
    params = {
        "created_at": created_at,
        "coin": coin,
        "is_buy": is_buy,
        "size": size,
        "leverage": leverage,
        "tif": tif,
        "decision_action": decision_action,
        "decision_confidence": decision_confidence,
        "snapshot_id": snapshot_id,
        "account_snapshot_id": account_snapshot_id,
        "order_payload": json.dumps(order_payload) if order_payload else None,
        "order_placed": order_placed,
    }
    with get_pool().connection() as conn:
        cur = conn.execute(sql, params)
        order_id = cur.fetchone()["id"]
        conn.commit()
        return order_id


def save_account_snapshot(captured_at, snapshot: Mapping[str, Any]) -> int:

    # Extract fields from marginSummary
    margin_summary = snapshot.get("marginSummary", {})
    account_value = margin_summary.get("accountValue")
    total_ntl_pos = margin_summary.get("totalNtlPos")
    total_raw_usd = margin_summary.get("totalRawUsd")
    total_margin_used = margin_summary.get("totalMarginUsed")
    withdrawable = snapshot.get("withdrawable")

    sql = """
    INSERT INTO account_snapshots (
        captured_at, account_value, total_ntl_pos,
        total_raw_usd, total_margin_used, withdrawable, raw_snapshot
    ) VALUES (
        %(captured_at)s, %(account_value)s, %(total_ntl_pos)s,
        %(total_raw_usd)s, %(total_margin_used)s, %(withdrawable)s, %(raw_snapshot)s
    )
    RETURNING id;
    """
    params = {
        "captured_at": captured_at,
        "account_value": account_value,
        "total_ntl_pos": total_ntl_pos,
        "total_raw_usd": total_raw_usd,
        "total_margin_used": total_margin_used,
        "withdrawable": withdrawable,
        "raw_snapshot": json.dumps(snapshot),
    }

    with get_pool().connection() as conn:
        cur = conn.execute(sql, params)
        account_id = cur.fetchone()["id"]
        conn.commit()
        return account_id


def get_recent_decisions(limit: int = 10) -> list[dict]:
    """Fetches the most recent order attempts with their context."""
    sql = """
    SELECT 
        oa.created_at,
        oa.decision_action,
        oa.decision_confidence,
        oa.is_buy,
        oa.size,
        oa.leverage,
        oa.tif,
        ms.raw_snapshot as market_snapshot,
        acs.raw_snapshot as account_snapshot
    FROM order_attempts oa
    LEFT JOIN market_snapshots ms ON oa.snapshot_id = ms.id
    LEFT JOIN account_snapshots acs ON oa.account_snapshot_id = acs.id
    ORDER BY oa.created_at DESC
    LIMIT %(limit)s;
    """
    with get_pool().connection() as conn:
        cur = conn.execute(sql, {"limit": limit})
        rows = cur.fetchall()

        # We need to reverse them to be in chronological order for the LLM
        return list(reversed(rows))
