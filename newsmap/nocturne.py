"""Nocny ekran: generatywna panorama neonowego miasta (nocturne.bin).

Urządzenie pobiera ją przy ostatniej aktualizacji przed ciszą nocną i zostawia na noc
(e-papier trzyma obraz bez prądu). Ziarno losowania to data, więc każda noc ma inne miasto.
"""
from __future__ import annotations

import math
import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from .render import BLACK, BLUE, DNI, GREEN, H, PALETTE_RGB, RED, W, WHITE, YELLOW, font, write_bin

HORIZON = 318
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def dither(px, x0, y0, x1, y1, color_of):
    """color_of(x, y) -> (kolor_a, kolor_b, udział_b 0..1); mieszanie progiem Bayera 4x4."""
    for y in range(max(0, y0), min(H, y1)):
        for x in range(max(0, x0), min(W, x1)):
            a, b, t = color_of(x, y)
            px[x, y] = b if t * 16 > BAYER[y % 4][x % 4] + 0.5 else a


def sky(px):
    def col(x, y):
        t = y / HORIZON  # 0 u góry, 1 przy horyzoncie
        if t < 0.45:
            return BLACK, BLUE, max(0.0, (t - 0.2) / 0.25) * 0.5
        if t < 0.8:
            return BLUE, RED, (t - 0.45) / 0.35
        return RED, YELLOW, min(1.0, (t - 0.8) / 0.2) * 0.6
    dither(px, 0, 0, W, HORIZON, col)


def stars(d, rnd):
    for _ in range(70):
        x, y = rnd.randrange(W), rnd.randrange(8, int(HORIZON * 0.4))
        d.point((x, y), fill=WHITE)
        if rnd.random() < 0.12:
            d.point([(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)], fill=WHITE)


def sun(px, d, cx, cy, r):
    """Słońce/księżyc w stylu synthwave: pionowy gradient i coraz grubsze szczeliny u dołu."""
    for y in range(cy - r, min(cy + r, HORIZON)):
        half = int(math.sqrt(max(0, r * r - (y - cy) ** 2)))
        rel = (y - (cy - r)) / (2 * r)
        if rel > 0.45:  # szczeliny
            k = (rel - 0.45) / 0.55
            period = 9
            gap = 1 + int(k * 6)
            if (y - (cy - r)) % period < gap:
                continue
        for x in range(cx - half, cx + half + 1):
            if 0 <= x < W:
                t = rel
                px[x, y] = RED if t * 16 > BAYER[y % 4][x % 4] * 0.9 + 4 else YELLOW


def building(d, rnd, x, w, h, body, windows, lit_p, neon=None):
    top = HORIZON - h
    d.rectangle((x, top, x + w, HORIZON), fill=body)
    # zwieńczenie: antena / schodek / skos
    kind = rnd.random()
    if kind < 0.3:
        ax = x + rnd.randrange(2, max(3, w - 2))
        ah = rnd.randrange(10, 34)
        d.line((ax, top - ah, ax, top), fill=body)
        d.point((ax, top - ah - 1), fill=RED)
    elif kind < 0.55:
        sw = max(4, w // 2)
        sx = x + rnd.randrange(0, max(1, w - sw))
        d.rectangle((sx, top - rnd.randrange(6, 18), sx + sw, top), fill=body)
    elif kind < 0.7:
        d.polygon([(x, top), (x + w, top), (x + w, top - rnd.randrange(6, 16))], fill=body)
    if windows is not None:
        for wy in range(top + 5, HORIZON - 4, 6):
            for wx in range(x + 3, x + w - 3, 5):
                if rnd.random() < lit_p:
                    d.rectangle((wx, wy, wx + 1, wy + 2), fill=windows)
    if neon:
        nx = x + rnd.randrange(1, max(2, w - 6))
        ny = top + rnd.randrange(6, max(7, h // 2))
        nh = rnd.randrange(18, 48)
        d.rectangle((nx, ny, nx + 5, ny + nh), fill=neon)
        for k in range(ny + 3, ny + nh - 2, 6):  # "znaki" na neonie
            d.rectangle((nx + 1, k, nx + 4, k + 2), fill=BLACK)


def skyline(d, rnd, gap: tuple[int, int]):
    """gap: zakres x przed słońcem, gdzie budynki są niższe, żeby było je widać."""
    def in_gap(x, w):
        return x + w > gap[0] and x < gap[1]
    # dalszy plan – granatowe sylwetki
    x = -10
    while x < W:
        w = rnd.randrange(14, 44)
        h = rnd.randrange(30, 70) if in_gap(x, w) else rnd.randrange(70, 190)
        building(d, rnd, x, w, h, BLUE, RED, 0.08)
        x += w + rnd.randrange(-6, 4)
    # pierwszy plan – czarne wieżowce z oknami i neonami
    x = -10
    while x < W:
        w = rnd.randrange(22, 70)
        if in_gap(x, w):
            h = rnd.randrange(18, 45)
        else:
            h = rnd.randrange(40, 150) if rnd.random() < 0.75 else rnd.randrange(170, 250)
        neon = rnd.choice([RED, YELLOW, None, None])
        building(d, rnd, x, w, h, BLACK, YELLOW, 0.22, neon)
        x += w + rnd.randrange(0, 10)


def ground(d):
    d.rectangle((0, HORIZON, W, H), fill=BLACK)
    vx = W // 2
    for k in range(-14, 15):  # linie zbiegające się w punkcie zbiegu
        d.line((vx + k * 12, HORIZON, vx + k * 120, H), fill=RED)
    y, step = HORIZON + 4, 3.0
    while y < H:
        d.line((0, int(y), W, int(y)), fill=RED)
        step *= 1.35
        y += step


def traffic(d, rnd):
    for _ in range(rnd.randrange(3, 6)):
        y = rnd.randrange(60, HORIZON - 120)
        x = rnd.randrange(40, W - 120)
        ln = rnd.randrange(30, 90)
        d.line((x, y, x + ln, y), fill=YELLOW if rnd.random() < 0.6 else RED)
        d.rectangle((x + ln, y - 1, x + ln + 3, y + 1), fill=WHITE)


def rain(d, rnd):
    for _ in range(140):
        x, y = rnd.randrange(W), rnd.randrange(0, H)
        d.line((x, y, x - 3, y + 9), fill=BLUE)


def hud(d, when: datetime, wake: str):
    ft = font(18, True, "mono")
    fs = font(12, True, "mono")
    d.rectangle((0, 0, W, 26), fill=BLACK)
    d.text((14, 13), "GDAŃSK", font=ft, fill=RED, anchor="lm")
    d.text((12, 12), "GDAŃSK", font=ft, fill=YELLOW, anchor="lm")
    d.text((12 + d.textlength("GDAŃSK", font=ft), 12), "//NOC", font=ft, fill=WHITE, anchor="lm")
    d.text((W - 12, 13), f"{DNI[when.weekday()]} {when:%d.%m.%Y} // TRYB CISZY", font=fs, fill=YELLOW, anchor="rm")
    d.rectangle((0, 26, 180, 28), fill=YELLOW)
    d.rectangle((0, H - 22, W, H), fill=BLACK)
    d.line((0, H - 22, W, H - 22), fill=YELLOW)
    d.text((12, H - 11), f"SYS:SLEEP · UPLINK OFF · WAKE {wake}", font=fs, fill=YELLOW, anchor="lm")
    d.text((W - 12, H - 11), "▮▮▮▯ STANDBY", font=fs, fill=GREEN, anchor="rm")


def render_night(when: datetime, out_dir: Path, wake: str = "06:00") -> Image.Image:
    rnd = random.Random(when.strftime("%Y-%m-%d"))
    img = Image.new("P", (W, H), BLACK)
    img.putpalette([c for rgb in PALETTE_RGB for c in rgb] + [0] * (256 - len(PALETTE_RGB)) * 3)
    px = img.load()
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    sky(px)
    stars(d, rnd)
    cx, r = rnd.randrange(200, 600), rnd.randrange(70, 100)
    sun(px, d, cx, HORIZON - rnd.randrange(60, 100), r)
    traffic(d, rnd)
    skyline(d, rnd, (cx - r // 2, cx + r // 2))
    ground(d)
    if rnd.random() < 0.5:
        rain(d, rnd)
    hud(d, when, wake)
    out_dir.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_dir / "nocturne.png")
    write_bin(img, out_dir / "nocturne.bin")
    return img
