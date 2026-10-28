"""Własne grafiki na ekran: każdy obrazek z folderu grafika/ w repo -> grafika_0.bin, grafika_1.bin, ...

Obrazek jest kadrowany do 800x480 (środek), lekko podbijany (kontrast, nasycenie) i przerabiany
na 6 kolorów ekranu Spectra 6 z ditheringiem Floyda-Steinberga. Kolejność = alfabetyczna kolejność plików.
Na urządzeniu: przytrzymanie lewego przycisku pokazuje kolejną grafikę.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .render import H, PALETTE_RGB, W, write_bin

log = logging.getLogger("newsmap.gallery")
ROOT = Path(__file__).resolve().parent.parent
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGES = 30


def convert(src: Path) -> Image.Image:
    img = Image.open(src)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.35)  # e-papier gasi kolory, więc trochę je podbijamy
    pal = Image.new("P", (1, 1))
    pal.putpalette([c for rgb in PALETTE_RGB for c in rgb] + list(PALETTE_RGB[0]) * (256 - len(PALETTE_RGB)))
    return img.quantize(palette=pal, dither=Image.FLOYDSTEINBERG)


def render_gallery(out_dir: Path, folder: Path | None = None) -> int:
    folder = folder or ROOT / "grafika"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("grafika_*"):
        old.unlink()
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in EXTS)[:MAX_IMAGES] if folder.exists() else []
    n = 0
    for src in files:
        try:
            img = convert(src)
        except Exception as e:  # noqa: BLE001 – zepsuty plik nie może zatrzymać reszty
            log.warning("Grafika %s pominięta: %s", src.name, e)
            continue
        img.convert("RGB").save(out_dir / f"grafika_{n}.png")
        write_bin(img, out_dir / f"grafika_{n}.bin")
        n += 1
    log.info("Galeria: %d grafik", n)
    return n
