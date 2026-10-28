"""Dodatkowe ekrany urządzenia (ten sam format co mapa: 800x480, 6 kolorów, news.bin-podobna ramka).

  rynki.bin    – RYNKI: cztery wykresy świecowe z ostatniego miesiąca
  briefing.bin – BRIEFING: pogoda w Gdańsku + tematy dzisiejszej prasówki + pasek giełdowy

Ekrany przełącza się przyciskami na obudowie (lewy = mapa, środkowy = rynki, prawy = briefing),
dlatego w nagłówku są trzy zakładki ułożone w tej samej kolejności.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from . import weather
from .render import (GREEN, H, PALETTE_RGB, RED, SCHEMES, W, DNI, cut_frame, dotted_line,
                     fit, fmt_num, font, hud_corners, stripes, ticker, write_bin)

ROOT = Path(__file__).resolve().parent.parent
TABS = ["MAPA", "RYNKI", "BRIEF"]
HEADER_H, FOOTER_H = 32, 22


# ---------------------------------------------------------------- wspólne elementy

def canvas(sc: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("P", (W, H), sc["bg"])
    img.putpalette([c for rgb in PALETTE_RGB for c in rgb] + [0] * (256 - len(PALETTE_RGB)) * 3)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    return img, d


def header(d: ImageDraw.ImageDraw, sc: dict, logo: tuple[str, str], active: int, when: datetime) -> None:
    d.rectangle((0, 0, W, HEADER_H), fill=sc["header_bg"])
    ft = font(20, True, "mono")
    a, b = logo
    d.text((12, 5), a, font=ft, fill=sc["accent"] if sc["header_bg"] != sc["accent"] else sc["header_fg"])
    d.text((12 + d.textlength(a, font=ft), 5), b, font=ft, fill=sc["title2"])

    # zakładki = przyciski na obudowie (lewy, środkowy, prawy)
    fz = font(13, True, "mono")
    x = 190
    for i, name in enumerate(TABS):
        label = f" {name} "
        w = d.textlength(label, font=fz)
        if i == active:
            d.rectangle((x - 1, 7, x + w + 1, 25), fill=sc["accent"])
            d.text((x, 16), label, font=fz, fill=sc["header_bg"], anchor="lm")
        else:
            d.rectangle((x - 1, 7, x + w + 1, 25), outline=sc["dim"] if sc["dim"] != sc["header_bg"] else sc["header_fg"])
            d.text((x, 16), label, font=fz, fill=sc["header_fg"], anchor="lm")
        x += w + 8

    stamp = f"{DNI[when.weekday()]} {when:%d.%m.%Y} // {when:%H:%M}"
    fm = font(16, True, "mono")
    sx = W - 12 - d.textlength(stamp, font=fm)
    d.text((sx, 8), stamp, font=fm, fill=sc["header_fg"])
    if sc["stripes"] and sx - 14 - (x + 6) > 30:
        stripes(d, (int(x + 6), 9, int(sx - 14), 23), sc["header_fg"])
    if sc["frame"] == "cut":
        d.polygon([(W - 18, HEADER_H), (W, HEADER_H - 18), (W, HEADER_H)], fill=sc["bg"])
        d.rectangle((0, HEADER_H, 180, HEADER_H + 3), fill=sc["accent"])
    else:
        d.line((0, HEADER_H, W, HEADER_H), fill=sc["line"])
        for xx in range(0, W, 40):
            d.line((xx, HEADER_H - 3, xx, HEADER_H), fill=sc["line"])


def footer_bar(d: ImageDraw.ImageDraw, sc: dict) -> int:
    top = H - FOOTER_H
    d.rectangle((0, top, W, H), fill=sc["footer_bg"])
    if sc["footer_bg"] == sc["bg"]:
        d.line((0, top, W, top), fill=sc["grid"])
    return top


def frame(d, sc, box):
    if sc["frame"] == "cut":
        cut_frame(d, box, sc["fg"])
    else:
        hud_corners(d, box, sc["accent"], n=10)


def up_down(sc: dict, ch: float) -> int:
    if ch > 0.004:
        return GREEN
    if ch < -0.004:
        return RED
    return sc["fg"]


def save(img: Image.Image, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_dir / f"{name}.png")
    write_bin(img, out_dir / f"{name}.bin")


def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: float, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=f) <= max_w:
            cur = t
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    used = " ".join(lines).split()
    if len(used) < len(words) and lines:
        lines[-1] = fit(d, lines[-1] + " …", f, max_w) if d.textlength(lines[-1] + " …", font=f) > max_w else lines[-1] + " …"
    return lines[:max_lines]


# ---------------------------------------------------------------- RYNKI

def candles_panel(d: ImageDraw.ImageDraw, sc: dict, box: tuple[int, int, int, int], label: str,
                  rows: list[dict], quote: dict | None) -> None:
    x0, y0, x1, y1 = box
    frame(d, sc, box)
    fb, fs, fv = font(18, True, "mono"), font(11, False, "mono"), font(18, False, "mono")
    if not rows:
        d.text((x0 + 12, y0 + 10), label, font=fb, fill=sc["accent"])
        d.text(((x0 + x1) / 2, (y0 + y1) / 2), "// BRAK DANYCH //", font=fs, fill=sc["dim"], anchor="mm")
        return

    last = rows[-1]["c"]
    ch = quote["change_pct"] if quote else (last / rows[-2]["c"] - 1) * 100
    price = quote["price"] if quote else last
    dec = 0 if price >= 1000 else 2

    # wiersz tytułu: NAZWA ........ kurs ▲zmiana
    d.text((x0 + 12, y0 + 8), label, font=fb, fill=sc["accent"])
    chs = ("▲" if ch > 0.004 else "▼" if ch < -0.004 else "■") + fmt_num(abs(ch), 2) + "%"
    cw = d.textlength(chs, font=fb)
    d.text((x1 - 12 - cw, y0 + 8), chs, font=fb, fill=up_down(sc, ch))
    ps = fmt_num(price, dec)
    d.text((x1 - 12 - cw - 10 - d.textlength(ps, font=fv), y0 + 8), ps, font=fv, fill=sc["fg"])

    hi, lo = max(r["h"] for r in rows), min(r["l"] for r in rows)
    m1 = (last / rows[0]["o"] - 1) * 100
    info = f"{len(rows)} SESJI   1M {'+' if m1 >= 0 else '−'}{fmt_num(abs(m1), 1)}%   MAX {fmt_num(hi, dec)}   MIN {fmt_num(lo, dec)}"
    d.text((x0 + 12, y0 + 32), info, font=fs, fill=sc["dim"] if sc["dim"] != sc["bg"] else sc["fg"])

    # obszar wykresu
    cx0, cx1, cy0, cy1 = x0 + 12, x1 - 12, y0 + 52, y1 - 10
    span = (hi - lo) or 1
    yv = lambda v: cy1 - (v - lo) / span * (cy1 - cy0)  # noqa: E731
    for frac in (0.0, 0.5, 1.0):
        yy = cy0 + frac * (cy1 - cy0)
        dotted_line(d, [(cx0, yy), (cx1, yy)], sc["grid"], every=4)
    n = len(rows)
    slot = (cx1 - cx0) / n
    body = max(2, int(slot * 0.6))
    for i, r in enumerate(rows):
        cx = cx0 + slot * (i + 0.5)
        col = GREEN if r["c"] >= r["o"] else RED
        d.line((round(cx), yv(r["h"]), round(cx), yv(r["l"])), fill=col)
        top, bot = sorted((yv(r["o"]), yv(r["c"])))
        if bot - top < 1:
            bot = top + 1
        d.rectangle((round(cx - body / 2), round(top), round(cx - body / 2) + body - 1, round(bot)), fill=col)
    # znacznik ostatniego kursu
    yl = yv(last)
    dotted_line(d, [(cx0, yl), (cx1, yl)], sc["fg"], every=2)


def render_markets(history: dict[str, list[dict]], quotes: list[dict], when: datetime, out_dir: Path,
                   scheme: str) -> Image.Image:
    sc = SCHEMES[scheme]
    img, d = canvas(sc)
    header(d, sc, ("RYNKI", "//TERM"), 1, when)
    top = footer_bar(d, sc)
    by_label = {q["label"]: q for q in quotes}
    labels = [q["label"] for q in quotes] or list(history)
    gap = 8
    area = (6, HEADER_H + 10, W - 6, top - 6)
    pw = (area[2] - area[0] - gap) / 2
    ph = (area[3] - area[1] - gap) / 2
    for i, label in enumerate(labels[:4]):
        cx, cy = i % 2, i // 2
        bx0 = int(area[0] + cx * (pw + gap))
        by0 = int(area[1] + cy * (ph + gap))
        candles_panel(d, sc, (bx0, by0, int(bx0 + pw), int(by0 + ph)), label, history.get(label, []),
                      by_label.get(label))
    fl = font(11, True, "mono")
    left = "ŚWIECE DZIENNE  ·  ZMIANA OD POPRZ. ZAMKNIĘCIA"
    right = "SRC:YAHOO  ·  OPÓŹN. ~15 MIN"
    d.text((12, top + FOOTER_H / 2), left, font=fl, fill=sc["footer_fg"], anchor="lm")
    d.text((W - 12, top + FOOTER_H / 2), right, font=fl, fill=sc["status"], anchor="rm")
    save(img, out_dir, "rynki")
    return img


# ---------------------------------------------------------------- BRIEFING

def digest_titles(day: datetime) -> list[str]:
    """Tytuły tekstów z dzisiejszej prasówki (prasowka/RRRR-MM-DD.html w repo)."""
    path = ROOT / "prasowka" / f"{day:%Y-%m-%d}.html"
    if not path.exists():
        return []
    src = path.read_text(encoding="utf-8")
    out = []
    for raw in re.findall(r"<h2[^>]*>(.*?)</h2>", src, re.S):
        t = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        out.append(re.sub(r"^\d+\.\s*", "", t))
    return out


def weather_block(d: ImageDraw.ImageDraw, sc: dict, box: tuple[int, int, int, int], w: dict | None,
                  when: datetime) -> None:
    x0, y0, x1, y1 = box
    fl = font(12, True, "mono")
    d.text((x0, y0), f"// POGODA · {weather.CITY}", font=fl, fill=sc["accent"])
    if not w:
        d.text((x0, y0 + 40), "BRAK SYGNAŁU", font=font(20, True, "mono"), fill=sc["dim"])
        return
    cur, daily, hourly = w["current"], w["daily"], w["hourly"]

    t = cur["temperature_2m"]
    big = font(64, True, "mono")
    ts = f"{'−' if round(t) < 0 else ''}{abs(round(t))}°"
    d.text((x0 - 2, y0 + 16), ts, font=big, fill=sc["fg"])
    tw = d.textlength(ts, font=big)
    fs, fsb = font(13, False, "mono"), font(13, True, "mono")
    d.text((x0 + tw + 14, y0 + 30), f"ODCZ. {round(cur['apparent_temperature'])}°", font=fs, fill=sc["fg"])
    d.text((x0 + tw + 14, y0 + 50), f"WILG. {round(cur['relative_humidity_2m'])}%", font=fs, fill=sc["fg"])

    desc = weather.describe(cur.get("weather_code"))
    d.text((x0, y0 + 94), fit(d, desc, fsb, x1 - x0), font=fsb, fill=sc["accent"])

    rows = [
        ("MAX/MIN", f"{round(daily['temperature_2m_max'][0])}° / {round(daily['temperature_2m_min'][0])}°"),
        ("OPADY", f"{daily['precipitation_probability_max'][0] or 0}% · {fmt_num(daily['precipitation_sum'][0] or 0, 1)} mm"),
        ("WIATR", f"{round(cur['wind_speed_10m'])} km/h {weather.wind_dir(cur.get('wind_direction_10m'))}"),
        ("SŁOŃCE", f"{daily['sunrise'][0][-5:]} → {daily['sunset'][0][-5:]}"),
    ]
    y = y0 + 122
    for k, v in rows:
        d.text((x0, y), k, font=fs, fill=sc["dim"] if sc["dim"] != sc["bg"] else sc["fg"])
        d.text((x0 + 80, y), v, font=fsb, fill=sc["fg"])
        y += 20

    # prognoza godzinowa: 5 punktów co 3 h od najbliższej pełnej godziny
    now_key = when.strftime("%Y-%m-%dT%H:00")
    times = hourly["time"]
    start = times.index(now_key) if now_key in times else 0
    idx = [start + 3 * k for k in range(1, 6) if start + 3 * k < len(times)]
    if not idx:
        return
    y = y + 12
    dotted_line(d, [(x0, y), (x1, y)], sc["grid"], every=3)
    slot = (x1 - x0) / len(idx)
    temps = [hourly["temperature_2m"][i] for i in idx]
    tmin, tmax = min(temps) - 3, max(temps)  # -3: najzimniejszy słupek też ma wysokość
    bar_top, bar_bot = y + 44, y1 - 34
    for k, i in enumerate(idx):
        cx = x0 + slot * (k + 0.5)
        d.text((cx, y + 14), times[i][11:13], font=fs, fill=sc["dim"] if sc["dim"] != sc["bg"] else sc["fg"], anchor="mm")
        tt = hourly["temperature_2m"][i]
        frac = (tt - tmin) / ((tmax - tmin) or 1)
        yy = bar_bot - frac * (bar_bot - bar_top)
        d.rectangle((cx - 9, yy, cx + 9, bar_bot), fill=sc["accent"])
        d.text((cx, yy - 9), f"{round(tt)}°", font=fsb, fill=sc["fg"], anchor="mm")
        p = hourly["precipitation_probability"][i]
        d.text((cx, y1 - 16), f"{p or 0}%", font=fs, fill=sc["fg"], anchor="mm")


def render_briefing(w: dict | None, titles: list[str], stories: list[dict], quotes: list[dict],
                    when: datetime, out_dir: Path, scheme: str) -> Image.Image:
    sc = SCHEMES[scheme]
    img, d = canvas(sc)
    header(d, sc, ("BRIEF", "//DNIA"), 2, when)
    top = footer_bar(d, sc)

    split = 300
    body_top, body_bot = HEADER_H + 14, top - 10
    weather_block(d, sc, (16, body_top, split - 18, body_bot), w, when)
    dotted_line(d, [(split, body_top), (split, body_bot)], sc["grid"], every=3)

    x0, x1 = split + 18, W - 16
    fl = font(12, True, "mono")
    if titles:
        head, items = f"// TEMATY DNIA · PRASÓWKA {when:%d.%m}", titles[:6]
    else:
        head, items = "// NA MAPIE · PRASÓWKA JESZCZE NIE GOTOWA", [f"{s['name']}: {s['text']}" for s in stories[:6]]
    d.text((x0, body_top), head, font=fl, fill=sc["accent"])
    fnum, ft = font(18, True, "mono"), font(18, False, "cond")
    map_line = " · ".join(s["name"].upper() for s in stories[:4]) if titles and stories else ""
    list_bot = body_bot - (34 if map_line else 0)
    n = max(len(items), 1)
    step = min(64, (list_bot - body_top - 26) / n)
    y = body_top + 26
    for i, t in enumerate(items, 1):
        d.text((x0, y), f"{i:02d}", font=fnum, fill=sc["accent"])
        lines = wrap(d, t, ft, x1 - x0 - 40, 2 if step >= 44 else 1)
        for k, line in enumerate(lines):
            d.text((x0 + 40, y + k * 21), line, font=ft, fill=sc["fg"])
        y += step
    if map_line:
        dotted_line(d, [(x0, list_bot + 6), (x1, list_bot + 6)], sc["grid"], every=3)
        d.text((x0, list_bot + 14), "NA MAPIE //", font=fl, fill=sc["accent"])
        d.text((x0 + d.textlength("NA MAPIE // ", font=fl), list_bot + 14),
               fit(d, map_line, fl, x1 - x0 - d.textlength("NA MAPIE // ", font=fl)), font=fl, fill=sc["fg"])
    if not items:
        d.text((x0, y), "// CISZA W ETERZE //", font=fnum, fill=sc["dim"])

    if quotes:
        ticker(d, quotes, top, sc)
    save(img, out_dir, "briefing")
    return img
