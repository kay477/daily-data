"""Sztuczne dane w formacie eksportu GDELT 2.0 – do testów bez internetu.

Symuluje 31 dni normalnego szumu, a w ostatnich 24 h "wydarzenia":
Wenezuela (duże), Nepal (duże), Pakistan (średnie), Słowacja (średnie), Kalifornia (duże).
"""
import random
from datetime import datetime, timezone

from newsmap.gdelt import parse_slot

LATEST = datetime(2026, 10, 26, 9, 45, tzinfo=timezone.utc).strftime("%Y%m%d%H%M%S")

# kod FIPS -> typowa liczba zdarzeń na 15 min
BASE = {"US": 400, "UK": 120, "CH": 90, "RS": 110, "UP": 100, "IS": 80, "IN": 90, "GM": 50, "FR": 50,
        "PL": 15, "IR": 40, "CA": 40, "AS": 35, "JA": 30, "BR": 30, "MX": 30, "TU": 30, "SA": 25,
        "EG": 20, "NI": 20, "SF": 20, "PK": 25, "VE": 8, "NP": 4, "LO": 3, "KE": 10, "IZ": 15, "SY": 20}
EVENTS = {"VE": 6.0, "NP": 9.0, "PK": 2.6, "LO": 4.0}
US_STATES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "WA", "DC", "AZ", "MI"]
STATE_EVENTS = {"CA": 5.0}


def fetch(slot: str):
    rnd = random.Random(slot)
    t = parse_slot(slot)
    hot = (parse_slot(LATEST) - t).total_seconds() < 24 * 3600
    rows = []
    for fips, base in BASE.items():
        mult = EVENTS.get(fips, 1.0) if hot else 1.0
        weekday = 0.8 if t.weekday() >= 5 else 1.0
        n = max(0, int(rnd.gauss(base * mult * weekday, base * 0.15)))
        for k in range(n):
            r = [""] * 61
            r[31] = str(rnd.randint(1, 20))
            r[53] = fips
            if fips == "US" and rnd.random() < 0.6:  # 60% zdarzeń w USA ma przypisany stan
                st = rnd.choice(US_STATES)
                r[54] = "US" + st
            r[60] = f"https://news.example/{fips.lower()}/{slot}/{k}"
            rows.append(r)
    if hot:  # dodatkowe zdarzenia w stanach, w których "coś się dzieje"
        for st, mult in STATE_EVENTS.items():
            base = BASE["US"] * 0.6 / len(US_STATES)
            for k in range(int(rnd.gauss(base * (mult - 1), base * 0.2))):
                r = [""] * 61
                r[31], r[53], r[54] = "5", "US", "US" + st
                r[60] = f"https://news.example/us-{st.lower()}/{slot}/{k}"
                rows.append(r)
    return rows


def titles(iso: str):
    return {
        "VE": ["Venezuela opposition calls mass protests after disputed vote count"],
        "NP": ["Magnitude 7.1 earthquake strikes central Nepal, dozens killed"],
        "PK": ["Pakistan and Afghanistan exchange fire along border crossing"],
        "US-CA": ["Wildfire forces evacuation of 40,000 near Los Angeles as winds intensify"],
        "SK": ["Slovak government survives no-confidence vote amid protests in Bratislava"],
    }.get(iso, ["Test headline"])
