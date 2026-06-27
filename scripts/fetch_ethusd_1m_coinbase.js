#!/usr/bin/env node
// Copyright (c) 2026 Evolve Quant LLC. All rights reserved.
// Source-available for evaluation under the LICENSE file.
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const HEADER = "unix,date,time,open,high,low,close,ETH_volume,USD_volume\n";
const GRANULARITY = 60;
const MAX_PER_REQUEST = 300;
const WINDOW_SEC = GRANULARITY * MAX_PER_REQUEST;

function parseArgs(argv) {
  const args = {
    product: process.env.COINBASE_PRODUCT_ID || "ETH-USD",
    days: 3,
    out: path.join(process.cwd(), "data", "ethusd_1m.csv"),
    sleepMs: 250,
  };

  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === "--product" && value) {
      args.product = value;
      i += 1;
    } else if (key === "--days" && value) {
      args.days = Math.max(1, Number(value));
      i += 1;
    } else if (key === "--out" && value) {
      args.out = value;
      i += 1;
    } else if (key === "--sleep-ms" && value) {
      args.sleepMs = Math.max(0, Number(value));
      i += 1;
    }
  }

  return args;
}

function ensureCsv(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, HEADER);
    return;
  }
  const current = fs.readFileSync(filePath, "utf8");
  if (!current.startsWith("unix,")) {
    fs.writeFileSync(filePath, HEADER + current);
  }
}

function parseCsvToMap(filePath) {
  const out = new Map();
  if (!fs.existsSync(filePath)) return out;

  const raw = fs.readFileSync(filePath, "utf8").trim();
  if (!raw) return out;

  const lines = raw.split(/\r?\n/);
  lines.shift();

  for (const line of lines) {
    if (!line.trim()) continue;
    const [unix, date, time, open, high, low, close, ethVol, usdVol] = line.split(",");
    const unixNum = Number(unix);
    if (!Number.isFinite(unixNum)) continue;

    out.set(String(unixNum), {
      unix: unixNum,
      date,
      time,
      open: Number(open),
      high: Number(high),
      low: Number(low),
      close: Number(close),
      ETH_volume: Number(ethVol || 0),
      USD_volume: Number(usdVol || 0),
    });
  }

  return out;
}

function rowToCsv(row) {
  const f2 = (x) => Number(x || 0).toFixed(2);
  const f6 = (x) => Number(x || 0).toFixed(6);
  return [
    row.unix,
    row.date,
    row.time,
    f2(row.open),
    f2(row.high),
    f2(row.low),
    f2(row.close),
    f6(row.ETH_volume),
    f2(row.USD_volume),
  ].join(",");
}

function writeMapToCsv(filePath, map) {
  const rows = Array.from(map.values())
    .filter((row) => Number.isFinite(Number(row.unix)))
    .sort((a, b) => Number(b.unix) - Number(a.unix));

  fs.writeFileSync(filePath, HEADER + rows.map(rowToCsv).join("\n") + "\n");
}

function iso(tsSec) {
  return new Date(tsSec * 1000).toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchCandlesRange(product, startSec, endSec) {
  const url = `https://api.exchange.coinbase.com/products/${product}/candles`;
  const { data } = await axios.get(url, {
    params: {
      granularity: GRANULARITY,
      start: iso(startSec),
      end: iso(endSec),
    },
    headers: {
      "User-Agent": "eth-1m-feature-store-demo/0.1",
    },
    timeout: 20000,
  });
  return Array.isArray(data) ? data : [];
}

function candleToRecord(row) {
  const unix = Number(row[0]);
  const low = Number(row[1]);
  const high = Number(row[2]);
  const open = Number(row[3]);
  const close = Number(row[4]);
  const ethVolume = Number(row[5]);

  const dt = new Date(unix * 1000);
  const isoString = dt.toISOString();
  const date = isoString.split("T")[0];
  const time = isoString.split("T")[1].split(".")[0];

  return {
    unix,
    date,
    time,
    open,
    high,
    low,
    close,
    ETH_volume: ethVolume,
    USD_volume: Number((close * ethVolume).toFixed(2)),
  };
}

async function updateRecentCandles(options) {
  const filePath = path.resolve(options.out);
  ensureCsv(filePath);

  const rowsByUnix = parseCsvToMap(filePath);
  const nowRaw = Math.floor(Date.now() / 1000);
  const newestCompleteMinute = nowRaw - (nowRaw % GRANULARITY) - GRANULARITY;
  const start = newestCompleteMinute - Number(options.days) * 24 * 3600;

  let cursor = start;
  let fetched = 0;
  let inserted = 0;
  let updated = 0;

  console.log(`Product: ${options.product}`);
  console.log(`Range: ${iso(start)} -> ${iso(newestCompleteMinute)}`);
  console.log(`Output: ${filePath}`);

  while (cursor < newestCompleteMinute) {
    const chunkEnd = Math.min(cursor + WINDOW_SEC, newestCompleteMinute);
    let candles = [];

    try {
      candles = await fetchCandlesRange(options.product, cursor, chunkEnd);
    } catch (err) {
      console.error(`Fetch failed for ${iso(cursor)} -> ${iso(chunkEnd)}: ${err.message}`);
      await sleep(1500);
      cursor = chunkEnd;
      continue;
    }

    candles.reverse();

    for (const candle of candles) {
      const record = candleToRecord(candle);
      if (!Number.isFinite(record.unix)) continue;
      if (!Number.isFinite(record.open)) continue;
      if (!Number.isFinite(record.high)) continue;
      if (!Number.isFinite(record.low)) continue;
      if (!Number.isFinite(record.close)) continue;

      const key = String(record.unix);
      const existing = rowsByUnix.get(key);
      if (!existing) {
        rowsByUnix.set(key, record);
        inserted += 1;
      } else {
        const needsUpdate =
          !Number.isFinite(existing.open) ||
          !Number.isFinite(existing.high) ||
          !Number.isFinite(existing.low) ||
          !Number.isFinite(existing.close) ||
          !Number.isFinite(existing.ETH_volume) ||
          existing.ETH_volume === 0 ||
          !Number.isFinite(existing.USD_volume) ||
          existing.USD_volume === 0;

        if (needsUpdate) {
          rowsByUnix.set(key, { ...existing, ...record });
          updated += 1;
        }
      }
      fetched += 1;
    }

    await sleep(options.sleepMs);
    cursor = chunkEnd;
  }

  writeMapToCsv(filePath, rowsByUnix);

  const newest = Array.from(rowsByUnix.values()).reduce(
    (best, row) => (Number(row.unix) > Number(best.unix || 0) ? row : best),
    {}
  );

  if (newest && Number.isFinite(newest.close)) {
    console.log(`Latest close: ${Number(newest.close).toFixed(2)} at ${newest.date} ${newest.time} UTC`);
  }
  console.log(`Done. checked=${fetched} inserted=${inserted} updated=${updated} total_rows=${rowsByUnix.size}`);
}

if (require.main === module) {
  updateRecentCandles(parseArgs(process.argv)).catch((err) => {
    console.error(err.stack || err.message);
    process.exitCode = 1;
  });
}

module.exports = updateRecentCandles;

