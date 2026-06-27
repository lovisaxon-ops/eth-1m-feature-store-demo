#!/usr/bin/env python3
"""Refresh derived feature columns from an existing OHLCV feature table."""
from __future__ import annotations

import argparse
import os
import typing as t

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from build_ohlcv_feature_store import DEFAULT_DB_URL, DEFAULT_TABLE, PERIODS, feature_columns, safe_div


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh derived feature columns in the feature store.")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--table", default=os.getenv("FEATURE_TABLE", DEFAULT_TABLE))
    parser.add_argument("--since", default=None, help="Optional timestamp lower bound for reads.")
    parser.add_argument("--lookback-bars", type=int, default=max(PERIODS) * 2)
    parser.add_argument("--chunksize", type=int, default=2000)
    return parser.parse_args()


def get_last_feature_ts(engine: Engine, table: str) -> pd.Timestamp | None:
    sql = text(f"SELECT MAX(`timestamp`) AS last_ts FROM `{table}` WHERE `ma_200` IS NOT NULL")
    with engine.connect() as conn:
        row = conn.execute(sql).mappings().first()
    ts = row.get("last_ts") if row else None
    return pd.Timestamp(ts) if ts is not None else None


def read_base_rows(engine: Engine, table: str, since: str | None) -> pd.DataFrame:
    where = "WHERE `timestamp` >= :since" if since else ""
    params = {"since": since} if since else {}
    sql = text(
        f"""
        SELECT `timestamp`, `close`, `vwap`, `USD_volume`
        FROM `{table}`
        {where}
        ORDER BY `timestamp` ASC
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def compute_refresh_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"timestamp": pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")})
    close = pd.to_numeric(df["close"], errors="coerce")
    vwap = pd.to_numeric(df["vwap"], errors="coerce")
    usd_volume = pd.to_numeric(df["USD_volume"], errors="coerce")
    price_volume = close * usd_volume

    for n in PERIODS:
        ma = close.rolling(n, min_periods=1).mean()
        ma_slope = ma.diff()
        ma_sos = ma_slope.diff()
        out[f"ma_{n}"] = ma
        out[f"ma_slope_{n}"] = ma_slope
        out[f"ma_slope_of_slope_{n}"] = ma_sos
        out[f"ma_slope_norm_{n}"] = safe_div(ma_slope, close)
        out[f"ma_slope_of_slope_norm_{n}"] = safe_div(ma_sos, close)

        denom = usd_volume.rolling(n, min_periods=1).sum()
        numer = price_volume.rolling(n, min_periods=1).sum()
        rolling_vwap = pd.Series(np.where(denom > 0, numer / denom, vwap), index=df.index)
        vwap_slope = rolling_vwap.diff()
        vwap_sos = vwap_slope.diff()
        out[f"vwap_{n}"] = rolling_vwap
        out[f"vwap_slope_{n}"] = vwap_slope
        out[f"vwap_slope_of_slope_{n}"] = vwap_sos
        out[f"vwap_slope_norm_{n}"] = safe_div(vwap_slope, close)
        out[f"vwap_slope_of_slope_norm_{n}"] = safe_div(vwap_sos, close)

    return out


def clean_records(df: pd.DataFrame) -> list[dict[str, t.Any]]:
    return df.replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict(orient="records")


def upsert_features(engine: Engine, table: str, df: pd.DataFrame, chunksize: int) -> int:
    cols = ["timestamp"] + feature_columns()
    df = df[cols].copy()
    col_list = ", ".join(f"`{col}`" for col in cols)
    placeholders = ", ".join(f":{col}" for col in cols)
    updates = ", ".join(f"`{col}`=excluded.`{col}`" for col in cols if col != "timestamp")

    if engine.dialect.name == "sqlite":
        sql = text(
            f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(`timestamp`) DO UPDATE SET {updates}"
        )
    else:
        mysql_updates = ", ".join(f"`{col}`=VALUES(`{col}`)" for col in cols if col != "timestamp")
        sql = text(
            f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {mysql_updates}"
        )

    records = clean_records(df)
    total = 0
    with engine.begin() as conn:
        for start in range(0, len(records), chunksize):
            chunk = records[start : start + chunksize]
            conn.execute(sql, chunk)
            total += len(chunk)
    return total


def main() -> None:
    load_dotenv()
    args = parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)

    if args.since:
        since = args.since
    else:
        last_ts = get_last_feature_ts(engine, args.table)
        if last_ts is None:
            since = None
        else:
            since = (last_ts - pd.Timedelta(minutes=args.lookback_bars)).strftime("%Y-%m-%d %H:%M:%S")

    base = read_base_rows(engine, args.table, since)
    if base.empty:
        print("No rows to refresh.")
        return

    features = compute_refresh_features(base)
    wrote = upsert_features(engine, args.table, features, args.chunksize)
    print(f"Refreshed {wrote} rows in {args.table}")


if __name__ == "__main__":
    main()

