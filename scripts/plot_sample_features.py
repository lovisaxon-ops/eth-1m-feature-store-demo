#!/usr/bin/env python3
"""Generate a small public plot from the sample CSV."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> None:
    import matplotlib.pyplot as plt

    csv_path = Path("data/sample_ethusd_1m.csv")
    out_path = Path("assets/sample_feature_plot.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)
    ts = pd.to_datetime(df["unix"], unit="s", utc=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    ma_50 = close.rolling(50, min_periods=1).mean()
    ma_200 = close.rolling(200, min_periods=1).mean()

    plt.figure(figsize=(10, 4.5))
    plt.plot(ts, close, label="Close", linewidth=1.1)
    plt.plot(ts, ma_50, label="MA 50", linewidth=1.2)
    plt.plot(ts, ma_200, label="MA 200", linewidth=1.2)
    plt.title("Synthetic ETHUSD 1m Sample: Close vs Rolling Features")
    plt.xlabel("UTC time")
    plt.ylabel("Price")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

