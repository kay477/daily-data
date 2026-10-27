"""Jednorazowa diagnostyka: które źródła kursów działają z serwerów GitHuba."""
import json, re, sys, traceback
import requests
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
out = {}
def probe(name, fn):
    try:
        out[name] = fn()
    except Exception as e:
        out[name] = f"ERR {type(e).__name__}: {str(e)[:200]}"

def yahoo_cffi(sym):
    from curl_cffi import requests as cr
    r = cr.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "5d", "interval": "1d"}, impersonate="chrome", timeout=15)
    if r.status_code != 200: return f"HTTP {r.status_code}"
    m = r.json()["chart"]["result"][0]["meta"]
    return {k: m.get(k) for k in ("regularMarketPrice", "chartPreviousClose", "previousClose", "regularMarketTime")}
for s in ["^IXIC", "^GSPC", "WIG20.WA", "CDR.WA"]:
    probe(f"yahoo_cffi {s}", lambda s=s: yahoo_cffi(s))

def cnbc(syms):
    r = requests.get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol",
                     params={"symbols": "|".join(syms), "requestMethod": "itv", "noform": "1", "partnerId": "2", "fund": "1", "exthrs": "1", "output": "json", "events": "1"},
                     headers=UA, timeout=15)
    if r.status_code != 200: return f"HTTP {r.status_code} {r.text[:120]}"
    q = r.json()["FormattedQuoteResult"]["FormattedQuote"]
    return [{k: x.get(k) for k in ("symbol", "name", "last", "change_pct", "previous_day_closing", "last_time", "code")} for x in q]
probe("cnbc", lambda: cnbc([".IXIC", ".SPX", ".WIG20", "CDR-PL", "CDR-WA", "CDR.WA", "CDR"]))

def google(path):
    r = requests.get(f"https://www.google.com/finance/quote/{path}", headers=UA, timeout=15, cookies={"CONSENT": "YES+"})
    if r.status_code != 200: return f"HTTP {r.status_code}"
    last = re.search(r'data-last-price="([\d.]+)"', r.text)
    prev = re.search(r'Previous close</div>.*?<div class="P6K39c">([^<]+)<', r.text, re.S)
    return {"last": last and last.group(1), "prev": prev and prev.group(1), "len": len(r.text)}
for p in [".IXIC:INDEXNASDAQ", ".INX:INDEXSP", "WIG20:WSE", "CDR:WSE", "CDR:WPW"]:
    probe(f"google {p}", lambda p=p: google(p))

def stooq(url):
    r = requests.get(url, headers=UA, timeout=15)
    return f"HTTP {r.status_code}: {r.text[:200]!r}"
probe("stooq d/l", lambda: stooq("https://stooq.com/q/d/l/?s=cdr&i=d"))
probe("stooq q/l", lambda: stooq("https://stooq.com/q/l/?s=cdr&f=sd2t2ohlcv&h&e=csv"))
probe("stooq.pl q/l", lambda: stooq("https://stooq.pl/q/l/?s=wig20&f=sd2t2ohlcv&h&e=csv"))

def bankier(sym):
    r = requests.get(f"https://www.bankier.pl/inwestowanie/profile/quote.html?symbol={sym}", headers=UA, timeout=15)
    if r.status_code != 200: return f"HTTP {r.status_code}"
    m = re.findall(r'class="profilLast">([^<]+)<', r.text)
    c = re.findall(r'class="change[^"]*">([^<]+)<', r.text)
    return {"last": m[:2], "change": c[:3], "len": len(r.text)}
for s in ["WIG20", "CDPROJEKT"]:
    probe(f"bankier {s}", lambda s=s: bankier(s))

json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
