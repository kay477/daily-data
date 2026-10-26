"""Pobieranie i agregacja danych GDELT 2.0 (Events).

GDELT co 15 minut publikuje plik ZIP z CSV zdarzeń. Każde zdarzenie ma kraj,
w którym się dzieje (ActionGeo_CountryCode, kod FIPS), oraz URL artykułu.
Liczymy unikalne artykuły na kraj w każdej godzinie i trzymamy to w małym
pliku stanu (31 dni historii), żeby nie pobierać wszystkiego od nowa.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE = "http://data.gdeltproject.org/gdeltv2"
LASTUPDATE = f"{BASE}/lastupdate.txt"
HISTORY_DAYS = 31
URL_KEEP_HOURS = 26
URLS_PER_COUNTRY_PER_SLOT = 25

# Kolumny w eksporcie GDELT 2.0 (61 kolumn, bez nagłówka)
COL_NUM_MENTIONS = 31
COL_ACTION_COUNTRY = 53
COL_ACTION_ADM1 = 54
COL_SOURCEURL = 60

# Kraje rozbijane na regiony (klucz w danych: "US-CA"). GDELT: ADM1 = "USCA".
SUBDIVIDED = {"US"}


def unit_keys(iso: str, adm1: str) -> list[str]:
    """Kraj + ewentualnie region, do którego liczymy artykuł."""
    keys = [iso]
    if iso in SUBDIVIDED and len(adm1) == 4 and adm1[:2].isalpha() and adm1[2:].isalpha():
        keys.append(f"{iso}-{adm1[2:]}")
    return keys


def slot_name(t: datetime) -> str:
    return t.strftime("%Y%m%d%H%M%S")


def parse_slot(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def hour_key(slot: str) -> str:
    return slot[:10]  # YYYYMMDDHH


@dataclass
class State:
    """Godzinowe liczniki artykułów per kraj + świeże URL-e do nagłówków."""

    counts: dict[tuple[str, str], int] = field(default_factory=dict)  # (hour, iso) -> artykuły
    totals: dict[str, int] = field(default_factory=dict)  # hour -> wszystkie artykuły
    slots: set[str] = field(default_factory=set)  # przetworzone 15-min pliki
    urls: list[tuple[str, str, str, int]] = field(default_factory=list)  # (slot, iso, url, mentions)

    # ---------- zapis / odczyt ----------
    @classmethod
    def load(cls, folder: Path) -> "State":
        st = cls()
        f = folder / "counts.csv.gz"
        if f.exists():
            with gzip.open(f, "rt", newline="") as fh:
                for hour, iso, n in csv.reader(fh):
                    if iso == "__ALL__":
                        st.totals[hour] = int(n)
                    else:
                        st.counts[(hour, iso)] = int(n)
        f = folder / "slots.txt"
        if f.exists():
            st.slots = {line.strip() for line in f.read_text().splitlines() if line.strip()}
        f = folder / "urls.csv.gz"
        if f.exists():
            with gzip.open(f, "rt", newline="") as fh:
                st.urls = [(s, i, u, int(m)) for s, i, u, m in csv.reader(fh)]
        return st

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / "counts.csv.gz", "wt", newline="") as fh:
            w = csv.writer(fh)
            for hour in sorted(self.totals):
                w.writerow([hour, "__ALL__", self.totals[hour]])
            for (hour, iso), n in sorted(self.counts.items()):
                w.writerow([hour, iso, n])
        (folder / "slots.txt").write_text("\n".join(sorted(self.slots)))
        with gzip.open(folder / "urls.csv.gz", "wt", newline="") as fh:
            csv.writer(fh).writerows(self.urls)

    def prune(self, now: datetime) -> None:
        cut_hour = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d%H")
        self.counts = {k: v for k, v in self.counts.items() if k[0] >= cut_hour}
        self.totals = {k: v for k, v in self.totals.items() if k >= cut_hour}
        cut_slot = slot_name(now - timedelta(days=HISTORY_DAYS))
        self.slots = {s for s in self.slots if s >= cut_slot}
        cut_url = slot_name(now - timedelta(hours=URL_KEEP_HOURS))
        self.urls = [u for u in self.urls if u[0] >= cut_url]

    @property
    def latest_slot(self) -> str | None:
        return max(self.slots) if self.slots else None

    # ---------- dodawanie danych z jednego pliku 15-min ----------
    def add_slot(self, slot: str, rows: list[list[str]], fips_to_iso: dict[str, str]) -> None:
        hour = hour_key(slot)
        per_country: dict[str, set[str]] = {}
        mentions: dict[tuple[str, str], int] = {}
        all_urls: set[str] = set()
        for r in rows:
            if len(r) <= COL_SOURCEURL:
                continue
            url = r[COL_SOURCEURL].strip()
            if not url:
                continue
            all_urls.add(url)
            iso = fips_to_iso.get(r[COL_ACTION_COUNTRY].strip())
            if not iso:
                continue
            try:
                m = int(r[COL_NUM_MENTIONS])
            except ValueError:
                m = 1
            for key in unit_keys(iso, r[COL_ACTION_ADM1].strip()):
                per_country.setdefault(key, set()).add(url)
                mentions[(key, url)] = mentions.get((key, url), 0) + m
        for iso, urls in per_country.items():
            self.counts[(hour, iso)] = self.counts.get((hour, iso), 0) + len(urls)
        self.totals[hour] = self.totals.get(hour, 0) + len(all_urls)
        # zachowaj tylko najczęściej wspominane URL-e per kraj (do nagłówków)
        by_iso: dict[str, list[tuple[str, int]]] = {}
        for (iso, url), m in mentions.items():
            by_iso.setdefault(iso, []).append((url, m))
        for iso, lst in by_iso.items():
            lst.sort(key=lambda x: -x[1])
            for url, m in lst[:URLS_PER_COUNTRY_PER_SLOT]:
                self.urls.append((slot, iso, url, m))
        self.slots.add(slot)


# ---------- sieć ----------
_session = requests.Session()
_session.headers["User-Agent"] = "news-map/1.0 (+https://github.com)"


def latest_available_slot() -> str:
    txt = _session.get(LASTUPDATE, timeout=30).text
    for line in txt.splitlines():
        if ".export.CSV.zip" in line:
            return line.split("/")[-1].split(".")[0]
    raise RuntimeError("Nie znalazłem eksportu w lastupdate.txt")


def fetch_slot(slot: str) -> list[list[str]] | None:
    """Zwraca wiersze CSV albo None, gdy pliku nie ma (GDELT czasem pomija interwał)."""
    url = f"{BASE}/{slot}.export.CSV.zip"
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = z.namelist()[0]
                text = z.read(name).decode("utf-8", errors="replace")
            csv.field_size_limit(10_000_000)
            return list(csv.reader(io.StringIO(text), delimiter="\t"))
        except (requests.RequestException, zipfile.BadZipFile) as e:
            log.warning("Błąd pobierania %s (próba %d): %s", slot, attempt + 1, e)
    return None


def missing_slots(state: State, latest: str, backfill_days: int) -> list[str]:
    end = parse_slot(latest)
    start = end - timedelta(days=backfill_days)
    if state.latest_slot and parse_slot(state.latest_slot) > start:
        # zwykły przebieg: tylko to, czego brakuje od ostatniego razu (+ dziury z ostatnich 3 h)
        start = min(parse_slot(state.latest_slot), end - timedelta(hours=3))
    out, t = [], start
    while t <= end:
        s = slot_name(t)
        if s not in state.slots:
            out.append(s)
        t += timedelta(minutes=15)
    return out


def update(state: State, fips_to_iso: dict[str, str], backfill_days: int, workers: int = 8,
           fetch=fetch_slot, latest: str | None = None) -> int:
    latest = latest or latest_available_slot()
    todo = missing_slots(state, latest, backfill_days)
    log.info("Do pobrania: %d plików (najnowszy %s)", len(todo), latest)
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for slot, rows in zip(todo, ex.map(fetch, todo)):
            if rows is None:
                # brakujący plik: po godzinie uznajemy, że już nie powstanie
                if parse_slot(latest) - parse_slot(slot) > timedelta(hours=1):
                    state.slots.add(slot)
                continue
            state.add_slot(slot, rows, fips_to_iso)
            done += 1
    state.prune(parse_slot(latest))
    return done
