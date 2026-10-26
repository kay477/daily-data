"""Wykrywanie krajów, o których nagle pisze się dużo więcej niż zwykle.

Dla każdego kraju liczymy jego UDZIAŁ w globalnym wolumenie artykułów
w ostatnich 24 h i porównujemy z tym samym oknem 24 h z poprzednich dni.
Udział (a nie surowa liczba) sprawia, że USA czy Chiny nie świecą się zawsze,
a weekendowy spadek liczby artykułów nie psuje wyników.

  x = ln((artykuły_kraju + 1) / wszystkie_artykuły)
  z = (x_dziś - średnia(x_historia)) / max(odch_std(x_historia), MIN_STD)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .gdelt import State, parse_slot

MIN_STD = 0.25          # chroni przed dzieleniem przez prawie zero u stabilnych krajów
MIN_ARTICLES = 30       # poniżej tego kraj nie może się "zapalić"
LEVEL1 = (2.0, 1.6)     # (z, krotność względem mediany) -> żółty
LEVEL2 = (3.2, 2.5)     # -> czerwony
MIN_BASELINE_DAYS = 3


@dataclass
class CountryScore:
    iso: str
    articles: int
    z: float
    ratio: float          # ile razy większy udział niż zwykle (mediana)
    level: int            # 0 = normalnie, 1 = podwyższone, 2 = dużo się dzieje


def _window_counts(state: State, end_hour: datetime) -> tuple[dict[str, int], int]:
    hours = {(end_hour - timedelta(hours=h)).strftime("%Y%m%d%H") for h in range(24)}
    counts: dict[str, int] = {}
    for (hour, iso), n in state.counts.items():
        if hour in hours:
            counts[iso] = counts.get(iso, 0) + n
    total = sum(state.totals.get(h, 0) for h in hours)
    return counts, total


def score(state: State, max_days: int = 30) -> tuple[list[CountryScore], int, datetime]:
    """Zwraca listę wyników (posortowaną malejąco po z), liczbę dni historii i czas danych."""
    latest = parse_slot(state.latest_slot)
    end_hour = latest.replace(minute=0, second=0)
    cur, cur_total = _window_counts(state, end_hour)
    if cur_total == 0:
        return [], 0, latest

    history: list[tuple[dict[str, int], int]] = []
    for d in range(1, max_days + 1):
        c, t = _window_counts(state, end_hour - timedelta(days=d))
        if t > cur_total * 0.2:  # pomijamy dni z dziurami w danych
            history.append((c, t))

    results = []
    for iso in set(cur) | {i for c, _ in history for i in c}:
        n = cur.get(iso, 0)
        x0 = math.log((n + 1) / cur_total)
        xs = [math.log((c.get(iso, 0) + 1) / t) for c, t in history]
        if xs:
            mean = sum(xs) / len(xs)
            std = math.sqrt(sum((x - mean) ** 2 for x in xs) / max(len(xs) - 1, 1))
            med = sorted(xs)[len(xs) // 2]
        else:
            mean, std, med = x0, 0.0, x0
        std_floor = MIN_STD if len(history) >= 7 else MIN_STD * 2  # mało historii = ostrożniej
        z = (x0 - mean) / max(std, std_floor)
        ratio = math.exp(x0 - med)
        level = 0
        if n >= MIN_ARTICLES and len(history) >= MIN_BASELINE_DAYS:
            if z >= LEVEL2[0] and ratio >= LEVEL2[1]:
                level = 2
            elif z >= LEVEL1[0] and ratio >= LEVEL1[1]:
                level = 1
        results.append(CountryScore(iso, n, round(z, 2), round(ratio, 2), level))
    results.sort(key=lambda s: (s.level, s.z), reverse=True)
    return results, len(history), latest


def top_stories(scores: list[CountryScore], n: int = 4) -> list[CountryScore]:
    """Kraje do listy pod mapą: najpierw zapalone, a jak ich mało – najwyższe z (> 1.0)."""
    hot = [s for s in scores if s.level > 0]
    if len(hot) < n:
        hot += [s for s in scores if s.level == 0 and s.z > 1.0 and s.articles >= MIN_ARTICLES][: n - len(hot)]
    return dedupe_parents(hot)[:n]


def dedupe_parents(items: list[CountryScore]) -> list[CountryScore]:
    """Jeśli na liście jest stan (US-CA), to samo "US" jest zbędne – region jest konkretniejszy."""
    parents = {s.iso.split("-")[0] for s in items if "-" in s.iso}
    return [s for s in items if s.iso not in parents]
