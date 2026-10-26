"""Nagłówki dla najgorętszych krajów.

1. Bierzemy najczęściej wspominane URL-e z ostatnich 24 h dla danego kraju.
2. Pobieramy tytuły stron (og:title / <title>); jak się nie da – tytuł z adresu URL.
3. Jeśli ustawiono ANTHROPIC_API_KEY, Claude streszcza każdy kraj w jednym
   zdaniu po polsku. Bez klucza pokazujemy po prostu najlepszy tytuł.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from .gdelt import State

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
TITLE_RE = [
    re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', re.I),
    re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S),
]
SUFFIX_RE = re.compile(r"\s+[|\-–—:]\s+[^|\-–—:]{2,40}$")  # " - BBC News", " | Reuters"
BAD_TITLES = {"access denied", "just a moment...", "403 forbidden", "attention required", "page not found"}

ANTHROPIC_MODEL = os.environ.get("NEWSMAP_MODEL", "claude-haiku-5-5")


def candidate_urls(state: State, iso: str, k: int = 8) -> list[str]:
    scores: dict[str, int] = {}
    for _slot, i, url, m in state.urls:
        if i == iso:
            scores[url] = scores.get(url, 0) + m
    out, domains = [], set()
    for url, _ in sorted(scores.items(), key=lambda x: -x[1]):
        d = urlparse(url).netloc.removeprefix("www.")
        if d in domains:
            continue
        domains.add(d)
        out.append(url)
        if len(out) >= k:
            break
    return out


def title_from_slug(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/").split("/")
    for part in reversed(path):
        part = re.sub(r"\.(html?|php|aspx?)$", "", part)
        words = [w for w in re.split(r"[-_]+", part) if w and not w.isdigit()]
        if len(words) >= 4 and not re.fullmatch(r"[0-9a-f]{8,}", part):
            return " ".join(words).capitalize()
    return None


def fetch_title(url: str) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8, stream=True)
        if r.status_code >= 400:
            raise requests.RequestException(r.status_code)
        chunk = r.raw.read(200_000, decode_content=True).decode(r.encoding or "utf-8", errors="replace")
        for rx in TITLE_RE:
            m = rx.search(chunk)
            if m:
                t = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
                t = SUFFIX_RE.sub("", t).strip()
                if len(t) > 15 and t.lower() not in BAD_TITLES:
                    return t
    except Exception as e:  # noqa: BLE001 – strony padają na tysiąc sposobów
        log.debug("tytuł %s: %s", url, e)
    return title_from_slug(url)


def collect(state: State, isos: list[str], per_country: int = 4) -> dict[str, list[str]]:
    jobs = {iso: candidate_urls(state, iso) for iso in isos}
    flat = [(iso, u) for iso, urls in jobs.items() for u in urls]
    with ThreadPoolExecutor(12) as ex:
        titles = list(ex.map(lambda x: fetch_title(x[1]), flat))
    out: dict[str, list[str]] = {iso: [] for iso in isos}
    for (iso, _), t in zip(flat, titles):
        if t and t not in out[iso] and len(out[iso]) < per_country:
            out[iso].append(t)
    return out


def summarize_pl(titles: dict[str, list[str]], names_pl: dict[str, str], max_chars: int) -> dict[str, str]:
    """Jedno zdanie po polsku na kraj. Bez klucza API – pierwszy tytuł."""
    fallback = {iso: (t[0] if t else "") for iso, t in titles.items()}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not any(titles.values()):
        return fallback
    listing = "\n".join(
        f"{iso} ({names_pl.get(iso, iso)}):\n" + "\n".join(f"- {t}" for t in ts)
        for iso, ts in titles.items() if ts
    )
    prompt = (
        "Poniżej są nagłówki artykułów z ostatnich 24 godzin pogrupowane po krajach, "
        "w których coś się dzieje. Dla każdego kraju napisz JEDNO krótkie zdanie po polsku "
        f"(maksymalnie {max_chars} znaków), co się dzieje. Rzeczowo, bez ocen, bez nazwy kraju "
        "na początku. Jeśli nagłówki są o różnych rzeczach, wybierz najważniejszą. "
        'Odpowiedz wyłącznie JSON-em w postaci {"KOD": "zdanie", ...}.\n\n' + listing
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": ANTHROPIC_MODEL, "max_tokens": 600,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"])
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return {iso: (str(data.get(iso)) if data.get(iso) else fallback[iso]) for iso in titles}
    except Exception as e:  # noqa: BLE001
        log.warning("Streszczenie przez Claude nie wyszło (%s) – pokazuję tytuły", e)
        return fallback
