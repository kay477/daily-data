"""Rysuje obrazek 800x480 w 6 kolorach ekranu E Ink Spectra 6 – styl cyberpunk/HUD.

Czarne tło, ląd jako matryca kropek, siatka współrzędnych, a kraje (w USA: stany),
w których coś się dzieje, świecą jednolitym neonowym kolorem z "glitchowym" przesunięciem.

Wyjście:
  preview.png – podgląd do obejrzenia w przeglądarce
  news.bin    – surowa ramka dla ESP32: 800*480/2 = 192 000 bajtów,
                2 piksele na bajt (starszy półbajt = lewy piksel),
                wartość = indeks z PALETTE_RGB poniżej.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 800, 480
ROOT = Path(__file__).resolve().parent.parent

# Indeksy muszą się zgadzać z firmware (tablica COLORS w news_map_display.ino)
BLACK, WHITE, YELLOW, RED, BLUE, GREEN = range(6)
PALETTE_RGB = [(0, 0, 0), (255, 255, 255), (245, 215, 0), (190, 20, 20), (20, 60, 160), (30, 120, 60)]

_BASE = dict(
    bg=BLACK, fg=WHITE, dim=BLUE,             # tło, tekst, tekst drugoplanowy (separatory, podpisy)
    land_dot=BLUE, dot=2, step=4,             # ląd jako matryca kropek
    grid=BLUE, grid_every=4,                  # kropkowana siatka współrzędnych
    accent=YELLOW, title2=WHITE, line=GREEN,  # logo/numery/ramki, druga część logo, linie podziału
    l1=YELLOW, l2=RED, glitch1=WHITE, glitch2=YELLOW,  # poziomy alarmu + kolor "glitchowego" konturu
    header_bg=BLACK, header_fg=WHITE, footer_bg=BLACK, footer_fg=WHITE, status=GREEN,
    frame="hud", stripes=False,
)
SCHEMES = {
    # klasyczny HUD: niebieskie kropki na czerni
    "neon": dict(_BASE),
    # terminal: zielone kropki
    "matrix": dict(_BASE, land_dot=GREEN, grid=GREEN, dim=GREEN),
    # białe, drobniejsze kropki – najbezpieczniejszy kontrast na e-papierze
    "mono": dict(_BASE, land_dot=WHITE, dot=1, step=3, line=BLUE, status=BLUE),
    # Cyberpunk 2077 (UI w dzień): żółte tło, czarne kropki, czerwone/cyjanowe (tu: niebieskie) alerty
    "2077": dict(_BASE, bg=YELLOW, fg=BLACK, dim=RED, land_dot=BLACK, grid=RED, grid_every=6,
                 accent=RED, title2=YELLOW, line=BLACK, l1=BLUE, l2=RED, glitch1=RED, glitch2=BLUE,
                 header_bg=BLACK, header_fg=YELLOW, footer_bg=BLACK, footer_fg=YELLOW, status=YELLOW,
                 frame="cut", stripes=True),
    # Night City: czarne tło, żółte kropki, czerwone akcenty
    "nightcity": dict(_BASE, fg=YELLOW, dim=RED, land_dot=YELLOW, dot=1, step=3, grid=RED, grid_every=5,
                      accent=RED, title2=YELLOW, line=RED, l1=WHITE, l2=RED, glitch1=RED, glitch2=BLUE,
                      header_fg=YELLOW, footer_fg=YELLOW, status=RED, frame="cut", stripes=True),
    # jasny: białe tło jak kartka, drobne czarne kropki – najjaśniejszy wygląd na e-papierze
    "jasny": dict(_BASE, bg=WHITE, fg=BLACK, dim=BLUE, land_dot=BLACK, dot=1, step=3, grid=BLUE, grid_every=5,
                  accent=RED, title2=BLACK, line=BLACK, l1=BLUE, l2=RED, glitch1=BLACK, glitch2=BLACK,
                  header_bg=WHITE, header_fg=BLACK, footer_bg=WHITE, footer_fg=BLACK, status=BLUE),
}
DEFAULT_SCHEME = "neon"

DNI = ["PON", "WT", "ŚR", "CZW", "PT", "SOB", "ND"]
SHORT_NAMES = {"PS": "Palestyna", "CD": "DR Konga", "CG": "Kongo", "GB": "Wlk. Brytania",
               "US": "USA", "AE": "ZEA", "CF": "Rep. Środkowoafr.", "BA": "Bośnia i Herc.",
               "KP": "Korea Płn.", "KR": "Korea Płd."}


def font(size: int, bold: bool = False, kind: str = "sans") -> ImageFont.FreeTypeFont:
    base = {"sans": "DejaVuSans", "cond": "DejaVuSansCondensed", "mono": "DejaVuSansMono"}[kind]
    return ImageFont.truetype(str(ROOT / "fonts" / f"{base}{'-Bold' if bold else ''}.ttf"), size)


# ---------- projekcja Equal Earth ----------
A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2


def equal_earth(lon: float, lat: float) -> tuple[float, float]:
    lam, phi = math.radians(lon), math.radians(lat)
    th = math.asin(M * math.sin(phi))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = lam * math.cos(th) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)))
    y = th * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x, y


class MapBox:
    def __init__(self, left: int, top: int, width: int, height: int, lat_min=-57.0, lat_max=83.0):
        self.lat_min, self.lat_max = lat_min, lat_max
        x_max = equal_earth(180, 0)[0]
        y_top, y_bot = equal_earth(0, lat_max)[1], equal_earth(0, lat_min)[1]
        self.s = min(width / (2 * x_max), height / (y_top - y_bot))
        self.cx = left + width / 2
        self.cy = top + (height - (y_top - y_bot) * self.s) / 2 + y_top * self.s

    def __call__(self, lon, lat):
        x, y = equal_earth(lon, max(min(lat, 89.9), -89.9))
        return self.cx + x * self.s, self.cy - y * self.s


def split_antimeridian(ring):
    """Pierścienie przechodzące przez 180° (Rosja, Fidżi) rozcinamy na kopie,
    inaczej rysowałyby się jako pas przez całą mapę."""
    if all(abs(b[0] - a[0]) < 180 for a, b in zip(ring, ring[1:])):
        return [ring]
    unwrapped, off = [], 0.0
    prev = ring[0][0]
    for lon, lat in ring:
        if lon - prev > 180:
            off -= 360
        elif prev - lon > 180:
            off += 360
        prev = lon
        unwrapped.append((lon + off, lat))
    out = []
    for shift in (0, -360, 360):
        copy = [(max(-180.0, min(180.0, lon + shift)), lat) for lon, lat in unwrapped]
        if any(-180 < lon < 180 for lon, _ in copy):
            out.append(copy)
    return out


def fit(draw: ImageDraw.ImageDraw, text: str, f, max_w: float) -> str:
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text.rstrip(" ,.;:-") + "…"


def dotted_line(d: ImageDraw.ImageDraw, pts, color, every: int = 3):
    """Linia z pojedynczych pikseli co `every` px – wygląda jak siatka na ekranie radaru."""
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        t = (every - acc) / seg if acc else 0.0
        while t <= 1:
            d.point((round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t)), fill=color)
            t += every / seg
        acc = (acc + seg) % every


def hud_corners(d, box, color, n=14, w=2):
    x0, y0, x1, y1 = box
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.rectangle((min(cx, cx + sx * n), min(cy, cy + sy * (w - 1)), max(cx, cx + sx * n), max(cy, cy + sy * (w - 1))), fill=color)
        d.rectangle((min(cx, cx + sx * (w - 1)), min(cy, cy + sy * n), max(cx, cx + sx * (w - 1)), max(cy, cy + sy * n)), fill=color)


def shapes(data: dict, key: str):
    return (data["subdivisions"].get(key) if "-" in key else data["countries"].get(key)) or {"rings": []}


def project_rings(proj, rings):
    out = []
    for raw in rings:
        for ring in split_antimeridian(raw):
            pts = [proj(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                out.append(pts)
    return out


def cut_frame(d, box, color, c=10, w=1):
    """Ramka ze ściętymi rogami (styl Cyberpunk 2077)."""
    x0, y0, x1, y1 = box
    pts = [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c), (x0 + c, y0)]
    d.line(pts, fill=color, width=w)


def stripes(d, box, color, gap=6, width=3):
    """Ukośne pasy ostrzegawcze w prostokącie."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    for x in range(x0 - h, x1, gap):
        for k in range(width):
            pts = [(max(x0, x + k), y1 - max(0, x0 - (x + k))), (min(x1, x + k + h), y0 + max(0, x + k + h - x1))]
            d.line(pts, fill=color)


def render(levels: dict[str, int], stories: list[dict], when: datetime, out_dir: Path,
           baseline_days: int, scheme: str = DEFAULT_SCHEME, markets: list[dict] | None = None) -> Image.Image:
    """levels: klucz (ISO kraju albo "US-CA") -> 0/1/2; stories: [{iso, name, text}];
    markets: [{label, price, change_pct}] do paska na dole (puste = legenda)."""
    data = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
    sc = SCHEMES[scheme]
    img = Image.new("P", (W, H), sc["bg"])
    img.putpalette([c for rgb in PALETTE_RGB for c in rgb] + [0] * (256 - len(PALETTE_RGB)) * 3)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # bez wygładzania – tylko czyste kolory z palety

    # ---------------- nagłówek ----------------
    header_h = 32
    d.rectangle((0, 0, W, header_h), fill=sc["header_bg"])
    ft = font(20, True, "mono")
    d.text((12, 5), "NEWS", font=ft, fill=sc["accent"] if sc["header_bg"] != sc["accent"] else sc["header_fg"])
    d.text((12 + d.textlength("NEWS", font=ft), 5), "//MAP", font=ft, fill=sc["title2"])
    stamp = f"{DNI[when.weekday()]} {when:%d.%m.%Y} // {when:%H:%M}"
    fm = font(16, True, "mono")
    sx = W - 12 - d.textlength(stamp, font=fm)
    d.text((sx, 8), stamp, font=fm, fill=sc["header_fg"])
    n2 = sum(1 for v in levels.values() if v == 2)
    n1 = sum(1 for v in levels.values() if v == 1)
    alert = f"[ {n2} KRYT · {n1} PODW ]" if (n1 or n2) else "[ BRAK ANOMALII ]"
    fa = font(13, True, "mono")
    d.text((140, 10), alert, font=fa, fill=RED if n2 else sc["header_fg"])
    if sc["stripes"]:  # pasy ostrzegawcze między alertem a datą
        x0 = int(140 + d.textlength(alert, font=fa) + 14)
        x1 = int(sx - 14)
        if x1 - x0 > 30:
            stripes(d, (x0, 9, x1, 23), sc["header_fg"])
    if sc["frame"] == "cut":
        d.polygon([(W - 18, header_h), (W, header_h - 18), (W, header_h)], fill=sc["bg"])  # ścięty róg
        d.rectangle((0, header_h, 220, header_h + 3), fill=sc["accent"])                 # akcent pod logo
    else:
        d.line((0, header_h, W, header_h), fill=sc["line"])
        for x in range(0, W, 40):
            d.line((x, header_h - 3, x, header_h), fill=sc["line"])

    # ---------------- układ ----------------
    rows = min(max(len(stories), 1), 4)
    footer_h = 22
    list_h = 8 + 24 * rows + footer_h
    map_top = header_h + 8
    map_bot = H - list_h - 6
    proj = MapBox(10, map_top, W - 20, map_bot - map_top)

    # ---------------- siatka współrzędnych ----------------
    ge = sc["grid_every"]
    for lon in range(-180, 181, 30):
        pts = [proj(lon, lat) for lat in range(int(proj.lat_min), int(proj.lat_max) + 1, 2)]
        dotted_line(d, pts, sc["grid"], every=ge if abs(lon) < 180 else 2)
    for lat in range(-30, 81, 30):
        pts = [proj(lon, lat) for lon in range(-180, 181, 3)]
        dotted_line(d, pts, sc["grid"], every=ge)

    # ---------------- ląd jako matryca kropek ----------------
    mask = Image.new("1", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for iso, c in data["countries"].items():
        if iso == "AQ":
            continue
        for pts in project_rings(proj, c["rings"]):
            md.polygon(pts, fill=1)
    mpx = mask.load()
    step, dot = sc["step"], sc["dot"]
    for y in range(map_top, map_bot, step):
        for x in range(0, W, step):
            if mpx[x, y]:
                d.rectangle((x, y, x + dot - 1, y + dot - 1), fill=sc["land_dot"])

    # ---------------- zapalone regiony ----------------
    has_sub = {k.split("-")[0] for k, v in levels.items() if "-" in k and v > 0}
    hot = [(k, v) for k, v in levels.items() if v > 0 and k not in has_sub]
    hot.sort(key=lambda kv: kv[1])  # czerwone na wierzchu
    small_targets = []
    for key, lvl in hot:
        fill = sc["l2"] if lvl == 2 else sc["l1"]
        glitch = sc["glitch2"] if lvl == 2 else sc["glitch1"]
        polys = project_rings(proj, shapes(data, key)["rings"])
        if not polys:
            continue
        # glitch: kontur przesunięty o 2 px w prawo i 1 px w górę, potem pełne wypełnienie
        for pts in polys:
            d.polygon([(x + 2, y - 1) for x, y in pts], outline=glitch)
        for pts in polys:
            d.polygon(pts, fill=fill, outline=fill)
        xs = [x for p in polys for x, _ in p]
        ys = [y for p in polys for _, y in p]
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 80:  # mały kraj – celownik, żeby było go widać
            small_targets.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, fill))
    for cx, cy, col in small_targets:
        r, n = 9, 4
        for sx_ in (-1, 1):
            for sy_ in (-1, 1):
                x0, y0 = cx + sx_ * r, cy + sy_ * r
                d.line((x0, y0, x0 - sx_ * n, y0), fill=col, width=2)
                d.line((x0, y0, x0, y0 - sy_ * n), fill=col, width=2)

    if sc["frame"] == "cut":
        cut_frame(d, (4, map_top - 3, W - 5, map_bot + 2), sc["fg"])
    else:
        hud_corners(d, (4, map_top - 2, W - 5, map_bot + 2), sc["accent"])
    fs = font(10, False, "mono")
    d.text((12, map_bot - 13), "PROJ:EQUAL-EARTH  SRC:GDELT.2", font=fs, fill=sc["dim"])

    # ---------------- lista ----------------
    y0 = H - list_h
    if sc["frame"] != "cut":
        d.line((0, y0, W, y0), fill=sc["line"])
    fnum, fname, ftxt = font(15, True, "mono"), font(15, True, "mono"), font(15, False, "cond")
    if not stories:
        d.text((W / 2, y0 + 8 + 12), "// NIGDZIE NIC NIE ODSTAJE OD NORMY //", font=fname, fill=sc["accent"], anchor="mm")
    for i, s in enumerate(stories[:4], 1):
        cy = y0 + 8 + (i - 1) * 24 + 10
        lvl = levels.get(s["iso"], 0)
        col = sc["l2"] if lvl == 2 else sc["l1"] if lvl == 1 else sc["fg"]
        d.text((12, cy), f"{i:02d}", font=fnum, fill=sc["accent"], anchor="lm")
        d.rectangle((40, cy - 6, 47, cy + 5), fill=col)  # znacznik poziomu w kolorze regionu
        name = s["name"].upper()
        d.text((56, cy), name, font=fname, fill=col, anchor="lm")
        nx = 56 + d.textlength(name, font=fname)
        d.text((nx + 6, cy), "//", font=fname, fill=sc["dim"], anchor="lm")
        tx = nx + 6 + d.textlength("// ", font=fname)
        d.text((tx, cy), fit(d, s["text"], ftxt, W - tx - 12), font=ftxt, fill=sc["fg"], anchor="lm")

    # ---------------- stopka: pasek giełdowy (albo legenda, gdy brak kursów) ----------------
    fy = H - footer_h + 2
    d.rectangle((0, fy - 3, W, H), fill=sc["footer_bg"])
    if sc["footer_bg"] == sc["bg"]:
        d.line((0, fy - 3, W, fy - 3), fill=sc["grid"])
    if markets:
        ticker(d, markets, fy - 3, sc)
    else:
        fl = font(11, True, "mono")
        x = 12
        for label, colr in (("KRYTYCZNE", sc["l2"]), ("PODWYŻSZONE", sc["l1"])):
            d.rectangle((x, fy + 4, x + 8, fy + 12), fill=colr, outline=sc["footer_fg"] if colr == sc["footer_bg"] else None)
            d.text((x + 13, fy + 2), label, font=fl, fill=sc["footer_fg"])
            x += 13 + d.textlength(label, font=fl) + 16
        status = f"HIST {baseline_days:02d}/30D" + ("  ·  KALIBRACJA" if baseline_days < 14 else "") + "  ·  ŹRÓDŁO GDELT"
        d.text((W - 12 - d.textlength(status, font=fl), fy + 2), status, font=fl,
               fill=RED if baseline_days < 14 else sc["status"])

    out_dir.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_dir / "preview.png")
    write_bin(img, out_dir / "news.bin")
    return img


def fmt_num(x: float, decimals: int) -> str:
    """Polski zapis: spacja jako separator tysięcy, przecinek dziesiętny."""
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")


def ticker(d: ImageDraw.ImageDraw, markets: list[dict], top: int, sc: dict) -> None:
    """Pasek giełdowy: NAZWA kurs ▲zmiana% – pozycje rozłożone równo na całej szerokości."""
    fl, fv = font(14, True, "mono"), font(14, False, "mono")
    cy = top + (H - top) / 2 + 1
    items = []
    for m in markets:
        ch = m["change_pct"]
        arrow, col = ("▲", GREEN) if ch > 0.004 else ("▼", RED) if ch < -0.004 else ("■", sc["footer_fg"])
        price = fmt_num(m["price"], 0 if m["price"] >= 1000 else 2)
        parts = [(m["label"], fl, sc["footer_fg"]), (" " + price + " ", fv, sc["footer_fg"]),
                 (arrow + fmt_num(abs(ch), 2) + "%", fl, col)]
        items.append((parts, sum(d.textlength(t, font=f) for t, f, _ in parts)))
    gap = (W - 24 - sum(w for _, w in items)) / max(len(items) - 1, 1)
    x = 12.0
    for i, (parts, w) in enumerate(items):
        if i:  # separator w połowie odstępu
            sx = x - gap / 2
            d.line((sx, top + 6, sx, H - 5), fill=sc["dim"] if sc["dim"] != sc["footer_bg"] else sc["footer_fg"])
        for t, f, col in parts:
            d.text((x, cy), t, font=f, fill=col, anchor="lm")
            x += d.textlength(t, font=f)
        x += gap


def write_bin(img: Image.Image, path: Path) -> None:
    px = img.tobytes()  # 1 bajt na piksel = indeks palety
    out = bytearray(W * H // 2)
    for i in range(0, len(px), 2):
        out[i // 2] = ((px[i] & 0x0F) << 4) | (px[i + 1] & 0x0F)
    path.write_bytes(bytes(out))


def display_name(key: str, data: dict) -> str:
    if "-" in key:
        sub = data["subdivisions"].get(key)
        return f"{sub['name_pl']} (USA)" if sub else key
    return SHORT_NAMES.get(key) or data["countries"].get(key, {}).get("name_pl", key)
