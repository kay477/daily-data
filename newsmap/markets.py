"""Kursy do paska giełdowego: zmiana względem poprzedniego zamknięcia.

Źródła po kolei: Yahoo Finance (nieoficjalne API wykresów), potem Stooq.
Jeśli oba zawiodą, bierzemy ostatnie znane wartości z pliku stanu,
żeby pasek nie znikał przy chwilowej awarii. Bez żadnych danych zwracamy [],
a render pokazuje wtedy starą legendę.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger("newsmap.markets")

# (etykieta na ekranie, symbol Yahoo, symbol Stooq)
TICKERS = [
    ("NASDAQ", "^IXIC", "^ndq"),
    ("S&P500", "^GSPC", "^spx"),
    ("WIG20", "WIG20.WA", "wig20"),
    ("CDPR", "CDR.WA", "cdr"),
]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
TIMEOUT = 15
MAX_CACHE_AGE_H = 72  # starsze dane z pamięci podręcznej nie są już pokazywane


def _yahoo(symbol: str) -> tuple[float, float] | None:
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params={"range": "5d", "interval": "1d"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or [])]
    stamps = res.get("timestamp") or []
    if price is None or not stamps:
        return None
    # poprzednie zamknięcie = ostatni pełny dzień przed dniem bieżącego notowania
    tz_off = meta.get("gmtoffset", 0)
    last_day = datetime.fromtimestamp(meta.get("regularMarketTime", stamps[-1]) + tz_off, timezone.utc).date()
    prev = None
    for ts, c in zip(stamps, closes):
        if c is not None and datetime.fromtimestamp(ts + tz_off, timezone.utc).date() < last_day:
            prev = c
    if prev is None:
        prev = meta.get("chartPreviousClose")
    return (float(price), float(prev)) if prev else None


def _stooq(symbol: str) -> tuple[float, float] | None:
    r = requests.get("https://stooq.com/q/d/l/", params={"s": symbol, "i": "d"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = [row for row in csv.DictReader(io.StringIO(r.text)) if row.get("Close")]
    if len(rows) < 2:
        return None
    return float(rows[-1]["Close"]), float(rows[-2]["Close"])


def fetch(state_dir: Path | None = None) -> list[dict]:
    cache_path = state_dir / "markets.json" if state_dir else None
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}

    now = datetime.now(timezone.utc)
    out = []
    for label, ysym, ssym in TICKERS:
        got, src = None, None
        for name, fn, sym in (("yahoo", _yahoo, ysym), ("stooq", _stooq, ssym)):
            try:
                got = fn(sym)
            except Exception as e:  # noqa: BLE001 – każda awaria źródła = próbujemy następne
                log.warning("Kurs %s z %s nie przyszedł: %s", label, name, e)
                got = None
            if got:
                src = name
                break
        if got:
            price, prev = got
            item = {"label": label, "price": round(price, 2), "change_pct": round((price / prev - 1) * 100, 2),
                    "source": src, "fetched_utc": now.isoformat(timespec="seconds")}
            cache[label] = item
        else:
            item = cache.get(label)
            if item:
                age_h = (now - datetime.fromisoformat(item["fetched_utc"])).total_seconds() / 3600
                if age_h > MAX_CACHE_AGE_H:
                    item = None
                else:
                    item = dict(item, source="cache")
        if item:
            out.append(item)
        log.info("Kurs %s: %s", label, item and f"{item['price']} ({item['change_pct']:+.2f}%, {item['source']})")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def fake() -> list[dict]:
    return [
        {"label": "NASDAQ", "price": 26169.38, "change_pct": 0.82},
        {"label": "S&P500", "price": 7676.80, "change_pct": 0.70},
        {"label": "WIG20", "price": 2734.15, "change_pct": -0.41},
        {"label": "CDPR", "price": 312.60, "change_pct": -2.35},
    ]
