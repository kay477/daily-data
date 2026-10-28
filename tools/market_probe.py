"""Jednorazowa diagnostyka: skąd wziąć historię WIG20."""
import json, sys, time
import requests
from curl_cffi import requests as cr
out = {}
def probe(name, fn):
    try: out[name] = fn()
    except Exception as e: out[name] = f"ERR {type(e).__name__}: {str(e)[:200]}"
now = int(time.time()); p1 = now - 70 * 86400
def y(sym, **params):
    r = cr.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}", params=params, impersonate="chrome", timeout=15)
    if r.status_code != 200: return f"HTTP {r.status_code}"
    res = r.json()["chart"]["result"][0]
    c = res["indicators"]["quote"][0].get("close") or []
    return {"n": len(res.get("timestamp") or []), "nonnull": sum(x is not None for x in c), "last": c[-3:], "valid": res["meta"].get("validRanges")}
probe("y WIG20.WA period", lambda: y("WIG20.WA", period1=p1, period2=now, interval="1d"))
probe("y WIG20.WA 1h 5d", lambda: y("WIG20.WA", range="5d", interval="1h"))
probe("y ^WIG20", lambda: y("^WIG20", range="2mo", interval="1d"))
probe("y WIG20TR.WA", lambda: y("WIG20TR.WA", range="2mo", interval="1d"))
probe("y ETFBW20TR.WA", lambda: y("ETFBW20TR.WA", range="2mo", interval="1d"))
probe("y FW20Z2620.WA", lambda: y("FW20Z2620.WA", range="2mo", interval="1d"))
def bankier(params):
    r = cr.get("https://www.bankier.pl/new-charts/get-data", params=params, impersonate="chrome", timeout=15)
    t = r.text
    return f"HTTP {r.status_code} len={len(t)} {t[:300]!r}"
probe("bankier ohlc", lambda: bankier({"symbol": "WIG20", "intraday": "false", "type": "ohlc", "max_period": "false", "date_from": (p1)*1000, "date_to": now*1000}))
probe("bankier area", lambda: bankier({"symbol": "WIG20", "intraday": "false", "type": "area", "max_period": "false", "date_from": (p1)*1000, "date_to": now*1000}))
def gpwb():
    r = cr.get("https://gpwbenchmark.pl/chart-json.php", params={"req": json.dumps([{"isin": "PL9999999987", "mode": "RANGE", "from": time.strftime("%Y-%m-%d", time.gmtime(p1)), "to": time.strftime("%Y-%m-%d", time.gmtime(now))}])}, impersonate="chrome", timeout=15)
    return f"HTTP {r.status_code} {r.text[:300]!r}"
probe("gpwbenchmark", gpwb)
def gpw():
    r = cr.get("https://www.gpw.pl/chart-json.php", params={"req": json.dumps([{"isin": "PL9999999987", "mode": "RANGE", "from": time.strftime("%Y-%m-%d", time.gmtime(p1)), "to": time.strftime("%Y-%m-%d", time.gmtime(now))}])}, impersonate="chrome", timeout=15)
    return f"HTTP {r.status_code} {r.text[:300]!r}"
probe("gpw chart-json", gpw)
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
