# ETH 1-Minute Feature Store Demo

Public portfolio demo for an ETHUSD 1-minute data engineering pipeline.

The project shows how to:

- pull recent ETH-USD 1-minute candles from Coinbase Exchange,
- normalize raw OHLCV CSV files,
- build a SQLite or MySQL feature table,
- compute rolling MA/VWAP slope features,
- refresh derived features incrementally for research workflows.

This is not a trading bot and does not provide investment advice. It is a
research/data infrastructure demo.

## Repository Layout

```text
scripts/fetch_ethusd_1m_coinbase.js   Coinbase 1-minute candle updater
scripts/build_ohlcv_feature_store.py  CSV -> feature-store table
scripts/refresh_features.py           Recompute feature columns from stored OHLCV
scripts/make_sample_data.py           Deterministic synthetic sample generator
scripts/plot_sample_features.py       Demo plot generator
sql/mysql_schema.sql                  Sanitized MySQL schema
sql/sqlite_schema.sql                 Sanitized SQLite schema
data/sample_ethusd_1m.csv             Small synthetic sample dataset
docs/                                Methodology, schema, publishing checklist
```

## Quickstart

From a fresh checkout:

```bash
git clone https://github.com/YOUR_USERNAME/eth-1m-feature-store-demo.git
cd eth-1m-feature-store-demo
cp .env.example .env
```

Create a Python environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install the Node dependency used by the Coinbase updater:

```bash
npm install
```

Build the SQLite feature store from the included synthetic sample:

```bash
python scripts/build_ohlcv_feature_store.py \
  --csv data/sample_ethusd_1m.csv \
  --db-url sqlite:///data/eth_features.sqlite
```

Refresh derived feature columns from the database:

```bash
python scripts/refresh_features.py \
  --db-url sqlite:///data/eth_features.sqlite
```

Expected local outputs:

- `data/eth_features.sqlite`
- console output showing inserted/refreshed row counts

Optional: pull recent live ETH-USD candles into a local CSV:

```bash
npm run fetch:eth
```

The generated SQLite database and live CSV output are intentionally ignored by Git so local research artifacts are not committed by accident.

## Feature Columns

The feature store includes base OHLCV fields plus rolling features for periods
`13, 21, 50, 100, 200`:

- moving average
- moving-average slope
- moving-average slope-of-slope
- normalized moving-average slope
- rolling VWAP
- VWAP slope
- VWAP slope-of-slope
- normalized VWAP slope

See [docs/schema.md](docs/schema.md) for the table shape.

## Public Demo Scope

This repository intentionally excludes:

- private `.env` files,
- API keys or wallet keys,
- live-trading code,
- model weights,
- production strategy thresholds,
- raw full-history datasets,
- trade logs and account state.

For production usage, package this as a private/pro version with installer
scripts, data validation checks, scheduled updates, and support.

