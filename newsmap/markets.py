"""Kursy do paska giełdowego: zmiana względem poprzedniego zamknięcia.

Źródła po kolei: Yahoo Finance (nieoficjalne API wykresów, przez curl_cffi, bo zwykłe
zapytania z serwerów GitHuba dostają 429), dla indeksów USA zapasowo CNBC.
Stooq od 2026 wymaga JavaScriptu, więc odpadł.
Jeśli oba zawiodą, bierzemy ostatnie znane wartości z pliku stanu,
żeby pasek nie znikał przy chwilowej awarii. Bez żadnych danych zwracamy [],
a render pokazuje wtedy starą legendę.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger("newsmap.markets")

# (etykieta na ekranie, symbol Yahoo, symbol CNBC albo None)
TICKERS = [
    ("NASDAQ", "^IXIC", ".IXIC"),
    ("S&P500", "^GSPC", ".SPX"),
    ("WIG20", "WIG20.WA", None),
    ("CDPR", "CDR.WA", None),
]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
TIMEOUT = 15
MAX_CACHE_AGE_H = 72  # starsze dane z pamięci podręcznej nie są już pokazywane


def _get(url: str, params: dict):
    """curl_cffi udaje przeglądarkę (Yahoo blokuje zwykłe biblioteki); bez niego – requests."""
    try:
        from curl_cffi import requests as cr  # noqa: PLC0415
        return cr.get(url, params=params, impersonate="chrome", timeout=TIMEOUT)
    except ImportError:
        return requests.get(url, params=params, headers=UA, timeout=TIMEOUT)


def _yahoo(symbol: str) -> tuple[float, float] | None:
    r = _get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}", {"range": "5d", "interval": "1d"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    stamps = res.get("timestamp") or []
    if price is None or not stamps:
        return None
    # poprzednie zamknięcie = ostatnia sesja przed dniem bieżącego notowania
    tz_off = meta.get("gmtoffset", 0)
    day = lambda ts: datetime.fromtimestamp(ts + tz_off, timezone.utc).date()  # noqa: E731
    last_day = day(meta.get("regularMarketTime", stamps[-1]))
    prev = None
    for ts, c in zip(stamps, closes):
        if c is not None and day(ts) < last_day:
            prev = c
    if prev is None:
        # część indeksów (np. WIG20) ma w danych dziennych dziury – wtedy pytamy o sam bieżący dzień,
        # dla którego chartPreviousClose to zamknięcie poprzedniej sesji
        r1 = _get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}", {"range": "1d", "interval": "1d"})
        r1.raise_for_status()
        prev = r1.json()["chart"]["result"][0]["meta"].get("chartPreviousClose")
    return (float(price), float(prev)) if prev else None


def _cnbc(symbol: str | None) -> tuple[float, float] | None:
    if not symbol:
        return None
    r = requests.get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol",
                     params={"symbols": symbol, "requestMethod": "itv", "noform": "1", "partnerId": "2",
                             "fund": "1", "exthrs": "1", "output": "json"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    q = r.json()["FormattedQuoteResult"]["FormattedQuote"][0]
    if not q.get("last") or not q.get("change_pct"):
        return None
    price = float(q["last"].replace(",", ""))
    pct = float(q["change_pct"].replace("%", "").replace("+", ""))
    return price, price / (1 + pct / 100)


ERRORS: list[str] = []  # ostatnie błędy źródeł – trafiają do news.json, żeby dało się je podejrzeć


def fetch(state_dir: Path | None = None) -> list[dict]:
    ERRORS.clear()
    cache_path = state_dir / "markets.json" if state_dir else None
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}

    now = datetime.now(timezone.utc)
    out = []
    for label, ysym, csym in TICKERS:
        got, src = None, None
        for name, fn, sym in (("yahoo", _yahoo, ysym), ("cnbc", _cnbc, csym)):
            try:
                got = fn(sym)
                if not got and sym:
                    ERRORS.append(f"{label}/{name}: brak danych w odpowiedzi")
            except Exception as e:  # noqa: BLE001 – każda awaria źródła = próbujemy następne
                log.warning("Kurs %s z %s nie przyszedł: %s", label, name, e)
                ERRORS.append(f"{label}/{name}: {type(e).__name__}: {str(e)[:200]}")
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
        {"label": "WIG20", "price": 4213.37, "change_pct": -0.41},
        {"label": "CDPR", "price": 270.00, "change_pct": -2.35},
    ]


def history(state_dir: Path | None = None, days: int = 30) -> dict[str, list[dict]]:
    """Świece dzienne z ostatniego miesiąca dla ekranu RYNKI: {etykieta: [{d, o, h, l, c}]}.

    Przy błędzie źródła zwraca ostatnią zapisaną historię (z pliku stanu)."""
    cache_path = state_dir / "markets_history.json" if state_dir else None
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    out = {}
    for label, ysym, _ in TICKERS:
        try:
            r = _get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}", {"range": "2mo", "interval": "1d"})
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            off = res["meta"].get("gmtoffset", 0)
            q = res["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(res.get("timestamp") or []):
                o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if c is None:
                    continue
                # część indeksów (WIG20) ma w danych dziennych tylko kurs zamknięcia
                if o is None:
                    o = rows[-1]["c"] if rows else c
                h = max(x for x in (h, o, c) if x is not None)
                lo = min(x for x in (lo, o, c) if x is not None)
                day = datetime.fromtimestamp(ts + off, timezone.utc).strftime("%Y-%m-%d")
                if rows and rows[-1]["d"] == day:
                    rows.pop()
                rows.append({"d": day, "o": o, "h": h, "l": lo, "c": c})
            log.info("Historia %s: %d sesji", label, len(rows))
            if len(rows) < 2:
                cache.setdefault("_diag", {})[label] = {"rows": len(rows), "meta": {k: res["meta"].get(k) for k in (
                    "dataGranularity", "range", "validRanges", "regularMarketPrice")},
                    "n_ts": len(res.get("timestamp") or []), "closes": (q.get("close") or [])[:8]}
            if len(rows) >= 2:
                out[label] = rows[-days:]
                cache[label] = out[label]
        except Exception as e:  # noqa: BLE001
            log.warning("Historia %s nie przyszła: %s", label, e)
            cache.setdefault("_diag", {})[label] = f"{type(e).__name__}: {str(e)[:300]}"
        if label not in out and label in cache:
            out[label] = cache[label]
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


def fake_history(days: int = 22) -> dict[str, list[dict]]:
    import random  # noqa: PLC0415
    out = {}
    for m in fake():
        rnd = random.Random(m["label"])
        p = m["price"] / (1 + m["change_pct"] / 100) * (1 + rnd.uniform(-0.06, 0.06))
        rows = []
        for i in range(days):
            o = p
            c = o * (1 + rnd.gauss(0, 0.011))
            if i == days - 1:
                c = m["price"]
            rows.append({"d": f"2026-10-{i + 1:02d}", "o": o, "h": max(o, c) * (1 + abs(rnd.gauss(0, 0.004))),
                         "l": min(o, c) * (1 - abs(rnd.gauss(0, 0.004))), "c": c})
            p = c
        out[m["label"]] = rows
    return out
