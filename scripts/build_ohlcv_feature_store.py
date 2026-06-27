#!/usr/bin/env python3
# Copyright (c) 2026 Evolve Quant LLC. All rights reserved.
# Source-available for evaluation under the LICENSE file.
"""Build a public-safe 1-minute OHLCV feature store from CSV files."""
from __future__ import annotations

import argparse
import os
import typing as t
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PERIODS = [13, 21, 50, 100, 200]
DEFAULT_DB_URL = "sqlite:///data/eth_features.sqlite"
DEFAULT_TABLE = "ohlcv_features_1m"


def feature_columns(periods: list[int] = PERIODS) -> list[str]:
    cols: list[str] = []
    for n in periods:
        cols.extend(
            [
                f"ma_{n}",
                f"ma_slope_{n}",
                f"ma_slope_of_slope_{n}",
                f"ma_slope_norm_{n}",
                f"ma_slope_of_slope_norm_{n}",
                f"vwap_{n}",
                f"vwap_slope_{n}",
                f"vwap_slope_of_slope_{n}",
                f"vwap_slope_norm_{n}",
                f"vwap_slope_of_slope_norm_{n}",
            ]
        )
    return cols


BASE_COLUMNS = [
    "timestamp",
    "unix",
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "ETH_volume",
    "USD_volume",
    "moving_average",
    "slope",
    "VWAP_slope",
]
ALL_COLUMNS = BASE_COLUMNS + feature_columns()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CSV -> ETH 1m OHLCV feature store.")
    parser.add_argument("--csv", default=os.getenv("PRICE_CSV", "data/sample_ethusd_1m.csv"))
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--table", default=os.getenv("FEATURE_TABLE", DEFAULT_TABLE))
    parser.add_argument("--freq", default=os.getenv("BAR_FREQ", "1min"))
    parser.add_argument("--chunksize", type=int, default=2000)
    return parser.parse_args()


def expand_csv_paths(csv_arg: str) -> list[str]:
    paths: list[str] = []
    for raw_item in str(csv_arg or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        if any(ch in item for ch in "*?[]"):
            paths.extend(str(p) for p in sorted(Path().glob(item)))
        else:
            paths.append(item)

    seen: set[str] = set()
    out: list[str] = []
    for item in paths:
        normalized = str(Path(item).expanduser())
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def find_column(columns: t.Iterable[str], candidates: list[str]) -> str | None:
    lower_to_orig = {c.lower().strip(): c for c in columns}
    for candidate in candidates:
        found = lower_to_orig.get(candidate.lower())
        if found:
            return found
    return None


def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.replace(0, np.nan)


def load_csvs(csv_arg: str, freq: str) -> pd.DataFrame:
    paths = expand_csv_paths(csv_arg)
    if not paths:
        raise FileNotFoundError("No CSV paths matched. Pass --csv or set PRICE_CSV.")

    frames = []
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        frames.append(pd.read_csv(path))

    raw = pd.concat(frames, ignore_index=True)

    unix_col = find_column(raw.columns, ["unix", "timestamp_unix", "time"])
    open_col = find_column(raw.columns, ["open"])
    high_col = find_column(raw.columns, ["high"])
    low_col = find_column(raw.columns, ["low"])
    close_col = find_column(raw.columns, ["close"])
    eth_volume_col = find_column(raw.columns, ["ETH_volume", "volume_eth", "volume (eth)", "volume"])
    usd_volume_col = find_column(raw.columns, ["USD_volume", "volume_usd", "volume_usdt", "volume (usd)", "quote_volume"])

    required = {
        "unix": unix_col,
        "open": open_col,
        "high": high_col,
        "low": low_col,
        "close": close_col,
    }
    missing = [name for name, col in required.items() if col is None]
    if missing:
        raise KeyError(f"Missing required CSV columns: {missing}. Found: {list(raw.columns)}")

    unix_raw = pd.to_numeric(raw[unix_col], errors="coerce")
    unix_seconds = unix_raw.where(unix_raw < 10_000_000_000, unix_raw / 1000.0)
    ts = pd.to_datetime(unix_seconds, unit="s", utc=True, errors="coerce").dt.tz_convert("UTC").dt.tz_localize(None)

    df = pd.DataFrame(
        {
            "timestamp": ts,
            "unix": unix_seconds,
            "open": pd.to_numeric(raw[open_col], errors="coerce"),
            "high": pd.to_numeric(raw[high_col], errors="coerce"),
            "low": pd.to_numeric(raw[low_col], errors="coerce"),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
        }
    )
    df["ETH_volume"] = pd.to_numeric(raw[eth_volume_col], errors="coerce") if eth_volume_col else np.nan
    df["USD_volume"] = pd.to_numeric(raw[usd_volume_col], errors="coerce") if usd_volume_col else np.nan
    df["USD_volume"] = df["USD_volume"].fillna(df["close"] * df["ETH_volume"])

    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    df = df[(df["timestamp"] >= pd.Timestamp("2015-01-01")) & (df["timestamp"] <= pd.Timestamp("2035-01-01"))]
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    df = df.set_index("timestamp").sort_index()

    def vwap_bar(group: pd.DataFrame) -> float:
        volume = group["USD_volume"].sum(skipna=True)
        if not np.isfinite(volume) or volume <= 0:
            return float(group["close"].mean())
        return float((group["close"] * group["USD_volume"]).sum() / volume)

    agg = df.resample(freq).agg(
        {
            "unix": "last",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "ETH_volume": "sum",
            "USD_volume": "sum",
        }
    )
    agg["vwap"] = df.resample(freq).apply(vwap_bar)
    agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index()

    return compute_features(agg)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = pd.to_numeric(out["close"], errors="coerce")
    usd_volume = pd.to_numeric(out["USD_volume"], errors="coerce")
    price_volume = close * usd_volume

    out["moving_average"] = close.rolling(20, min_periods=1).mean()
    out["slope"] = close.diff()
    out["VWAP_slope"] = pd.to_numeric(out["vwap"], errors="coerce").diff()

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
        rolling_vwap = pd.Series(np.where(denom > 0, numer / denom, close), index=out.index)
        vwap_slope = rolling_vwap.diff()
        vwap_sos = vwap_slope.diff()
        out[f"vwap_{n}"] = rolling_vwap
        out[f"vwap_slope_{n}"] = vwap_slope
        out[f"vwap_slope_of_slope_{n}"] = vwap_sos
        out[f"vwap_slope_norm_{n}"] = safe_div(vwap_slope, close)
        out[f"vwap_slope_of_slope_norm_{n}"] = safe_div(vwap_sos, close)

    out["timestamp"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[ALL_COLUMNS]


def sql_type(engine: Engine) -> str:
    return "REAL" if engine.dialect.name == "sqlite" else "DOUBLE"


def ensure_table(engine: Engine, table: str) -> None:
    number_type = sql_type(engine)
    column_defs = ["`timestamp` DATETIME NOT NULL PRIMARY KEY"]
    for col in ALL_COLUMNS:
        if col == "timestamp":
            continue
        column_defs.append(f"`{col}` {number_type} NULL")
    ddl = f"CREATE TABLE IF NOT EXISTS `{table}` ({', '.join(column_defs)})"
    with engine.begin() as conn:
        conn.execute(text(ddl))


def clean_records(df: pd.DataFrame) -> list[dict[str, t.Any]]:
    clean = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return clean.to_dict(orient="records")


def upsert(engine: Engine, table: str, df: pd.DataFrame, chunksize: int) -> int:
    if df.empty:
        return 0

    cols = list(df.columns)
    col_list = ", ".join(f"`{col}`" for col in cols)
    placeholders = ", ".join(f":{col}" for col in cols)

    if engine.dialect.name == "sqlite":
        sql = text(f"INSERT OR REPLACE INTO `{table}` ({col_list}) VALUES ({placeholders})")
    else:
        updates = ", ".join(f"`{col}`=VALUES(`{col}`)" for col in cols if col != "timestamp")
        sql = text(f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}")

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
    ensure_table(engine, args.table)
    frame = load_csvs(args.csv, args.freq)
    wrote = upsert(engine, args.table, frame, args.chunksize)
    print(f"Loaded {len(frame)} feature rows from {args.csv}")
    print(f"Upserted {wrote} rows into {args.table} via {args.db_url}")


if __name__ == "__main__":
    main()

