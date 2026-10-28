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
from .render import (BLUE, GREEN, H, PALETTE_RGB, RED, SCHEMES, W, DNI, dotted_line, fit, fmt_num, font,
                     stripes, ticker, write_bin)

ROOT = Path(__file__).resolve().parent.parent
TABS = ["MAPA", "RYNKI", "BRIEF"]
HEADER_H, FOOTER_H = 32, 22


# ---------------------------------------------------------------- wspólne elementy (styl HUD / cyberpunk)

def canvas(sc: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("P", (W, H), sc["bg"])
    img.putpalette([c for rgb in PALETTE_RGB for c in rgb] + [0] * (256 - len(PALETTE_RGB)) * 3)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    # tło: rzadka siatka punktów jak na papierze radarowym
    for y in range(HEADER_H + 8, H - FOOTER_H, 16):
        for x in range(8, W, 16):
            d.point((x, y), fill=sc["grid"])
    return img, d


def ghost(sc: dict) -> int:
    """Kolor "rozjechanego" duchu przy efekcie glitch."""
    return RED if sc["accent"] != RED else BLUE


def on_accent(sc: dict) -> int:
    return sc["bg"] if sc["bg"] != sc["accent"] else sc["fg"]


def soft(sc: dict) -> int:
    return sc["dim"] if sc["dim"] != sc["bg"] else sc["fg"]


def glitch_text(d, xy, text, f, fill, gcol, dx=3, dy=-1, anchor="la"):
    d.text((xy[0] + dx, xy[1] + dy), text, font=f, fill=gcol, anchor=anchor)
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def glitch_slice(img: Image.Image, box: tuple[int, int, int, int], bands: list[tuple[int, int, int]]) -> None:
    """Przesuwa poziome paski obrazu w bok – efekt "zerwanego sygnału". bands: (y_od_góry, wysokość, przesunięcie)."""
    x0, y0, x1, y1 = box
    for oy, hgt, shift in bands:
        top = y0 + oy
        if top + hgt > y1:
            continue
        band = img.crop((x0, top, x1, top + hgt))
        img.paste(band, (x0 + shift, top))


def hex_code(seed: str) -> str:
    h = 0
    for ch in seed:
        h = (h * 131 + ord(ch)) & 0xFFFF
    return f"0x{h:04X}"


def cut_box(d, box, color, c=10, cut=("tr", "bl"), w=1):
    """Ramka ze ściętymi wybranymi rogami."""
    x0, y0, x1, y1 = box
    tl = [(x0, y0 + c), (x0 + c, y0)] if "tl" in cut else [(x0, y0)]
    tr = [(x1 - c, y0), (x1, y0 + c)] if "tr" in cut else [(x1, y0)]
    br = [(x1, y1 - c), (x1 - c, y1)] if "br" in cut else [(x1, y1)]
    bl = [(x0 + c, y1), (x0, y1 - c)] if "bl" in cut else [(x0, y1)]
    pts = tl + tr + br + bl
    d.line(pts + [pts[0]], fill=color, width=w)


def tab(d, sc, x, y, text, f, fill=None, fg=None, slant=6) -> float:
    """Zakładka-etykieta w kształcie równoległoboku, zwraca prawą krawędź."""
    w = d.textlength(text, font=f)
    hgt = f.size + 6
    fill = sc["accent"] if fill is None else fill
    d.polygon([(x, y + hgt), (x + slant, y), (x + w + 12 + slant, y), (x + w + 12, y + hgt)], fill=fill)
    d.text((x + 6 + slant / 2, y + hgt / 2 + 1), text, font=f, fill=on_accent(sc) if fg is None else fg, anchor="lm")
    return x + w + 12 + slant


def panel(d, sc, box, title: str, idx: int) -> None:
    """Panel HUD: ścięte rogi, zakładka z tytułem, kod hex, podziałka na dole."""
    x0, y0, x1, y1 = box
    col = sc["fg"] if sc["frame"] == "cut" else sc["accent"]
    cut_box(d, box, col, c=12)
    ft = font(13, True, "mono")
    tab(d, sc, x0 - 1, y0 - 9, f"{idx:02d}//{title}", ft)
    fs = font(9, False, "mono")
    hc = hex_code(title)
    hw = d.textlength(hc, font=fs)
    d.rectangle((x1 - 22 - hw, y0 - 5, x1 - 18, y0 + 5), fill=sc["bg"])
    d.text((x1 - 20, y0), hc, font=fs, fill=soft(sc), anchor="rm")
    for k in range(3):  # trzy kwadraciki "statusu"
        d.rectangle((x1 - 14 + 0 * k, y0 + 18 + k * 6, x1 - 10, y0 + 21 + k * 6), fill=col if k < 2 else sc["bg"],
                    outline=col)
    for xx in range(int(x0 + 20), int(x1 - 20), 10):  # podziałka
        d.line((xx, y1 - (4 if (xx - x0) % 50 < 10 else 2), xx, y1), fill=col)


def header(d: ImageDraw.ImageDraw, sc: dict, logo: tuple[str, str], active: int, when: datetime) -> None:
    d.rectangle((0, 0, W, HEADER_H), fill=sc["header_bg"])
    ft = font(20, True, "mono")
    a, b = logo
    lc = sc["accent"] if sc["header_bg"] != sc["accent"] else sc["header_fg"]
    glitch_text(d, (12, 5), a, ft, lc, ghost(sc) if ghost(sc) != sc["header_bg"] else sc["header_fg"], dx=2, dy=1)
    d.text((12 + d.textlength(a, font=ft), 5), b, font=ft, fill=sc["title2"])

    # zakładki = przyciski na obudowie (lewy, środkowy, prawy)
    fz = font(12, True, "mono")
    x = 196
    for i, name in enumerate(TABS):
        if i == active:
            x = tab(d, sc, x, 7, f"{i + 1}:{name}", fz) + 4
        else:
            w = d.textlength(f"{i + 1}:{name}", font=fz)
            oc = soft(sc) if soft(sc) != sc["header_bg"] else sc["header_fg"]
            d.line([(x, 25), (x + 6, 7), (x + w + 18, 7), (x + w + 12, 25), (x, 25)], fill=oc)
            d.text((x + 9, 17), f"{i + 1}:{name}", font=fz, fill=sc["header_fg"], anchor="lm")
            x += w + 22

    stamp = f"{DNI[when.weekday()]} {when:%d.%m.%Y} // {when:%H:%M}"
    fm = font(16, True, "mono")
    sx = W - 12 - d.textlength(stamp, font=fm)
    d.text((sx, 8), stamp, font=fm, fill=sc["header_fg"])
    if sx - 14 - (x + 8) > 30:
        stripes(d, (int(x + 8), 9, int(sx - 14), 23), sc["header_fg"] if sc["stripes"] else soft(sc))
    if sc["frame"] == "cut":
        d.polygon([(W - 18, HEADER_H), (W, HEADER_H - 18), (W, HEADER_H)], fill=sc["bg"])
    d.line((0, HEADER_H, W, HEADER_H), fill=sc["line"])
    d.rectangle((0, HEADER_H, 160, HEADER_H + 3), fill=sc["accent"])
    d.polygon([(160, HEADER_H), (170, HEADER_H), (166, HEADER_H + 3), (160, HEADER_H + 3)], fill=sc["accent"])


def footer_bar(d: ImageDraw.ImageDraw, sc: dict) -> int:
    top = H - FOOTER_H
    d.rectangle((0, top, W, H), fill=sc["footer_bg"])
    d.line((0, top, W, top), fill=sc["line"] if sc["footer_bg"] == sc["bg"] else sc["footer_bg"])
    return top


def barcode(d, x, y, hgt, seed: str, color) -> float:
    """Ozdobny kod kreskowy (szerokości pasków z ziarna)."""
    v = sum(ord(c) * (i + 7) for i, c in enumerate(seed))
    for k in range(18):
        w = 1 + (v >> (k % 12)) % 3
        if k % 2 == 0:
            d.rectangle((x, y, x + w - 1, y + hgt), fill=color)
        x += w + 1
    return x


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

def candles_panel(d: ImageDraw.ImageDraw, sc: dict, box: tuple[int, int, int, int], label: str, idx: int,
                  rows: list[dict], quote: dict | None) -> None:
    x0, y0, x1, y1 = box
    panel(d, sc, box, label, idx)
    fb, fs, fv = font(18, True, "mono"), font(10, False, "mono"), font(18, False, "mono")
    if not rows:
        d.text(((x0 + x1) / 2, (y0 + y1) / 2), "// SYGNAŁ UTRACONY //", font=font(12, True, "mono"),
               fill=soft(sc), anchor="mm")
        return

    last = rows[-1]["c"]
    ch = quote["change_pct"] if quote else (last / rows[-2]["c"] - 1) * 100
    price = quote["price"] if quote else last
    dec = 0 if price >= 1000 else 2

    # kurs i zmiana dnia
    chs = ("▲" if ch > 0.004 else "▼" if ch < -0.004 else "■") + fmt_num(abs(ch), 2) + "%"
    cw = d.textlength(chs, font=fb)
    d.text((x1 - 26 - cw, y0 + 10), chs, font=fb, fill=up_down(sc, ch))
    ps = fmt_num(price, dec)
    d.text((x1 - 26 - cw - 10 - d.textlength(ps, font=fv), y0 + 10), ps, font=fv, fill=sc["fg"])

    hi, lo = max(r["h"] for r in rows), min(r["l"] for r in rows)
    m1 = (last / rows[0]["o"] - 1) * 100
    per = "1M" if len(rows) >= 18 else f"{len(rows)}D"
    info = f"SES:{len(rows):02d}  Δ{per}:{'+' if m1 >= 0 else '−'}{fmt_num(abs(m1), 1)}%"
    if any(r.get("p") for r in rows):
        info += "  *HIST.WG ETF"
    d.text((x0 + 10, y0 + 18), info, font=fs, fill=soft(sc))

    # wykres; z prawej oś z MAX / MIN i znacznik ostatniego kursu
    cx0, cx1, cy0, cy1 = x0 + 10, x1 - 66, y0 + 40, y1 - 14
    span = (hi - lo) or 1
    yv = lambda v: cy1 - (v - lo) / span * (cy1 - cy0)  # noqa: E731
    for frac in (0.0, 0.5, 1.0):
        yy = cy0 + frac * (cy1 - cy0)
        dotted_line(d, [(cx0, yy), (cx1 + 4, yy)], sc["grid"], every=3)
    d.line((cx1 + 4, cy0, cx1 + 4, cy1), fill=soft(sc))
    for v in (hi, lo):
        if abs(yv(v) - yv(last)) > 14:  # nie nachodzi na metkę ostatniego kursu
            d.text((cx1 + 8, yv(v)), fmt_num(v, dec), font=fs, fill=soft(sc), anchor="lm")
    n = len(rows)
    slot = (cx1 - cx0) / max(n, 22)   # przy krótkiej historii świece mają normalną szerokość i stoją od prawej
    body = max(2, int(slot * 0.6))
    start = cx1 - slot * n
    for i, r in enumerate(rows):
        cx = start + slot * (i + 0.5)
        col = GREEN if r["c"] >= r["o"] else RED
        d.line((round(cx), yv(r["h"]), round(cx), yv(r["l"])), fill=col)
        top, bot = sorted((yv(r["o"]), yv(r["c"])))
        if bot - top < 1:
            bot = top + 1
        d.rectangle((round(cx - body / 2), round(top), round(cx - body / 2) + body - 1, round(bot)), fill=col)
    # ostatni kurs: linia + metka na osi
    yl = yv(last)
    dotted_line(d, [(cx0, yl), (cx1, yl)], sc["fg"], every=2)
    ft = font(10, True, "mono")
    t = fmt_num(last, dec)
    tw = d.textlength(t, font=ft)
    yl = min(max(yl, cy0 + 6), cy1 - 6)
    d.polygon([(cx1 + 1, yl), (cx1 + 7, yl - 7), (cx1 + 11 + tw, yl - 7), (cx1 + 11 + tw, yl + 7), (cx1 + 7, yl + 7)],
              fill=sc["accent"])
    d.text((cx1 + 9, yl + 1), t, font=ft, fill=on_accent(sc), anchor="lm")


def render_markets(history: dict[str, list[dict]], quotes: list[dict], when: datetime, out_dir: Path,
                   scheme: str) -> Image.Image:
    sc = SCHEMES[scheme]
    img, d = canvas(sc)
    header(d, sc, ("RYNKI", "//TERM"), 1, when)
    top = footer_bar(d, sc)
    by_label = {q["label"]: q for q in quotes}
    labels = [q["label"] for q in quotes] or list(history)
    gap_x, gap_y = 12, 18
    area = (8, HEADER_H + 18, W - 8, top - 6)
    pw = (area[2] - area[0] - gap_x) / 2
    ph = (area[3] - area[1] - gap_y) / 2
    for i, label in enumerate(labels[:4]):
        cx, cy = i % 2, i // 2
        bx0 = int(area[0] + cx * (pw + gap_x))
        by0 = int(area[1] + cy * (ph + gap_y))
        candles_panel(d, sc, (bx0, by0, int(bx0 + pw), int(by0 + ph)), label, i + 1, history.get(label, []),
                      by_label.get(label))
    fl = font(11, True, "mono")
    x = barcode(d, 10, top + 5, 11, when.strftime("%Y%m%d%H"), sc["footer_fg"]) + 10
    d.text((x, top + FOOTER_H / 2), "FEED//ŚWIECE 1D · Δ OD POPRZ. ZAMKNIĘCIA", font=fl, fill=sc["footer_fg"], anchor="lm")
    d.text((W - 12, top + FOOTER_H / 2), "UPLINK:YAHOO · LAG ~15 MIN", font=fl, fill=sc["status"], anchor="rm")
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


def weather_block(img: Image.Image, d: ImageDraw.ImageDraw, sc: dict, box: tuple[int, int, int, int],
                  w: dict | None, when: datetime) -> None:
    x0, y0, x1, y1 = box
    panel(d, sc, box, f"ENV:{weather.CITY}", 1)
    x0, x1 = x0 + 12, x1 - 12
    y0 += 16
    if not w:
        d.text((x0, y0 + 40), "SYGNAŁ UTRACONY", font=font(18, True, "mono"), fill=soft(sc))
        return
    cur, daily, hourly = w["current"], w["daily"], w["hourly"]

    # duża temperatura z efektem glitch
    t = cur["temperature_2m"]
    big = font(64, True, "mono")
    ts = f"{'−' if round(t) < 0 else ''}{abs(round(t))}°"
    glitch_text(d, (x0 - 2, y0 + 2), ts, big, sc["fg"], ghost(sc), dx=3, dy=0)
    tw = d.textlength(ts, font=big)
    glitch_slice(img, (int(x0 - 4), int(y0 + 4), int(x0 + tw + 8), int(y0 + 76)), [(30, 2, 4), (52, 2, -3)])
    fs, fsb = font(12, False, "mono"), font(12, True, "mono")
    d.text((x0 + tw + 14, y0 + 16), f"FEEL {round(cur['apparent_temperature'])}°", font=fs, fill=sc["fg"])
    d.text((x0 + tw + 14, y0 + 34), f"HUM  {round(cur['relative_humidity_2m'])}%", font=fs, fill=sc["fg"])
    d.text((x0 + tw + 14, y0 + 52), hex_code(cur.get("time", "")), font=font(9, False, "mono"), fill=soft(sc))

    desc = weather.describe(cur.get("weather_code"))
    tab(d, sc, x0 - 2, y0 + 84, fit(d, desc, fsb, x1 - x0 - 30), fsb)

    rows = [
        ("MAX/MIN", f"{round(daily['temperature_2m_max'][0])}° / {round(daily['temperature_2m_min'][0])}°"),
        ("OPADY", f"{daily['precipitation_probability_max'][0] or 0}% · {fmt_num(daily['precipitation_sum'][0] or 0, 1)} mm"),
        ("WIATR", f"{round(cur['wind_speed_10m'])} km/h {weather.wind_dir(cur.get('wind_direction_10m'))}"),
        ("SŁOŃCE", f"{daily['sunrise'][0][-5:]} → {daily['sunset'][0][-5:]}"),
    ]
    y = y0 + 114
    for k, v in rows:
        d.text((x0, y), f"> {k}", font=fs, fill=soft(sc))
        d.text((x0 + 84, y), v, font=fsb, fill=sc["fg"])
        y += 18

    # prognoza: 5 punktów co 3 h, słupki z segmentów
    now_key = when.strftime("%Y-%m-%dT%H:00")
    times = hourly["time"]
    start = times.index(now_key) if now_key in times else 0
    idx = [start + 3 * k for k in range(1, 6) if start + 3 * k < len(times)]
    if not idx:
        return
    y += 6
    dotted_line(d, [(x0, y), (x1, y)], sc["grid"], every=3)
    slot = (x1 - x0) / len(idx)
    temps = [hourly["temperature_2m"][i] for i in idx]
    tmin, tmax = min(temps) - 3, max(temps)
    bar_top, bar_bot = y + 40, y1 - 30
    for k, i in enumerate(idx):
        cx = x0 + slot * (k + 0.5)
        d.text((cx, y + 12), times[i][11:13] + "H", font=fs, fill=soft(sc), anchor="mm")
        tt = hourly["temperature_2m"][i]
        frac = (tt - tmin) / ((tmax - tmin) or 1)
        yy = bar_bot - frac * (bar_bot - bar_top)
        seg = bar_bot
        while seg - 4 >= yy:  # segmenty 4 px co 6 px
            d.rectangle((cx - 9, seg - 4, cx + 9, seg - 1), fill=sc["accent"])
            seg -= 6
        d.text((cx, seg - 8), f"{round(tt)}°", font=fsb, fill=sc["fg"], anchor="mm")
        p = hourly["precipitation_probability"][i]
        d.text((cx, y1 - 16), f"{p or 0}%", font=fs, fill=sc["fg"], anchor="mm")


def render_briefing(w: dict | None, titles: list[str], stories: list[dict], quotes: list[dict],
                    when: datetime, out_dir: Path, scheme: str) -> Image.Image:
    sc = SCHEMES[scheme]
    img, d = canvas(sc)
    header(d, sc, ("BRIEF", "//DNIA"), 2, when)
    top = footer_bar(d, sc)

    split = 296
    body_top, body_bot = HEADER_H + 18, top - 8
    weather_block(img, d, sc, (8, body_top, split - 6, body_bot), w, when)

    box = (split + 6, body_top, W - 8, body_bot)
    if titles:
        head, items = f"INTEL:PRASÓWKA {when:%d.%m}", titles[:6]
    else:
        head, items = "INTEL:MAPA · PRASÓWKA NIE GOTOWA", [f"{s['name']}: {s['text']}" for s in stories[:6]]
    panel(d, sc, box, head, 2)
    x0, x1 = box[0] + 14, box[2] - 24
    fl = font(12, True, "mono")
    fnum, ft = font(13, True, "mono"), font(18, False, "cond")
    map_line = " · ".join(s["name"].upper() for s in stories[:4]) if titles and stories else ""
    list_bot = body_bot - (34 if map_line else 6)
    n = max(len(items), 1)
    y = body_top + 22
    step = min(62, (list_bot - y) / n)
    for i, t in enumerate(items, 1):
        tab(d, sc, x0 - 4, y + 1, f"{i:02d}", fnum)
        lines = wrap(d, t, ft, x1 - x0 - 42, 2 if step >= 44 else 1)
        for k, line in enumerate(lines):
            d.text((x0 + 40, y + k * 21), line, font=ft, fill=sc["fg"])
        y += step
    if map_line:
        dotted_line(d, [(x0, list_bot + 4), (x1, list_bot + 4)], sc["grid"], every=3)
        lbl = "SKAN MAPY >> "
        d.text((x0, list_bot + 12), lbl, font=fl, fill=sc["accent"])
        d.text((x0 + d.textlength(lbl, font=fl), list_bot + 12),
               fit(d, map_line, fl, x1 - x0 - d.textlength(lbl, font=fl)), font=fl, fill=sc["fg"])
    if not items:
        d.text((x0, y), "// CISZA W ETERZE //", font=fnum, fill=soft(sc))

    if quotes:
        ticker(d, quotes, top, sc)
    save(img, out_dir, "briefing")
    return img
