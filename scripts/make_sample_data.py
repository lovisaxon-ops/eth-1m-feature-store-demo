#!/usr/bin/env python3
"""Create a deterministic synthetic ETHUSD 1-minute sample CSV."""
from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--out", default="data/sample_ethusd_1m.csv")
    parser.add_argument("--start", default="2026-01-01T00:00:00Z")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(timezone.utc)
    rng = random.Random(42)
    price = 2400.0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["unix", "date", "time", "open", "high", "low", "close", "ETH_volume", "USD_volume"])
        for i in range(args.rows):
            ts = start + timedelta(minutes=i)
            seasonal = math.sin(i / 37.0) * 2.5
            drift = 0.015 * i / max(args.rows, 1)
            noise = rng.gauss(0, 1.2)
            open_px = price
            close_px = max(100.0, open_px + seasonal * 0.05 + drift + noise)
            high_px = max(open_px, close_px) + abs(rng.gauss(0.8, 0.35))
            low_px = min(open_px, close_px) - abs(rng.gauss(0.8, 0.35))
            eth_volume = max(0.01, rng.lognormvariate(2.2, 0.45))
            usd_volume = close_px * eth_volume
            price = close_px

            writer.writerow(
                [
                    int(ts.timestamp()),
                    ts.strftime("%Y-%m-%d"),
                    ts.strftime("%H:%M:%S"),
                    f"{open_px:.2f}",
                    f"{high_px:.2f}",
                    f"{low_px:.2f}",
                    f"{close_px:.2f}",
                    f"{eth_volume:.6f}",
                    f"{usd_volume:.2f}",
                ]
            )

    print(f"Wrote {args.rows} rows to {out_path}")


if __name__ == "__main__":
    main()

