"""Pogoda dla ekranu BRIEFING – Open-Meteo (darmowe, bez klucza)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger("newsmap.weather")

CITY = "GDAŃSK"
LAT, LON = 54.352, 18.646
TZ = "Europe/Warsaw"

# kody pogody WMO -> krótki opis po polsku
WMO = {
    0: "BEZCHMURNIE", 1: "PRZEWAŻNIE POGODNIE", 2: "CZĘŚCIOWE ZACHMURZENIE", 3: "POCHMURNO",
    45: "MGŁA", 48: "MGŁA SZRONIEJĄCA",
    51: "SŁABA MŻAWKA", 53: "MŻAWKA", 55: "GĘSTA MŻAWKA", 56: "MARZNĄCA MŻAWKA", 57: "MARZNĄCA MŻAWKA",
    61: "SŁABY DESZCZ", 63: "DESZCZ", 65: "ULEWA", 66: "MARZNĄCY DESZCZ", 67: "MARZNĄCY DESZCZ",
    71: "SŁABY ŚNIEG", 73: "ŚNIEG", 75: "ŚNIEŻYCA", 77: "ZIARNA ŚNIEGU",
    80: "PRZELOTNY DESZCZ", 81: "PRZELOTNE OPADY", 82: "GWAŁTOWNE OPADY",
    85: "PRZELOTNY ŚNIEG", 86: "INTENSYWNY ŚNIEG",
    95: "BURZA", 96: "BURZA Z GRADEM", 99: "SILNA BURZA Z GRADEM",
}
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def describe(code) -> str:
    return WMO.get(int(code), "—") if code is not None else "—"


def wind_dir(deg) -> str:
    return DIRS[round(float(deg) / 45) % 8] if deg is not None else ""


def fetch(state_dir: Path | None = None) -> dict | None:
    cache_path = state_dir / "weather.json" if state_dir else None
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
            "latitude": LAT, "longitude": LON, "timezone": TZ, "forecast_days": 2, "wind_speed_unit": "kmh",
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,"
                       "relative_humidity_2m",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                     "sunrise,sunset",
        })
        r.raise_for_status()
        data = r.json()
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("Pogoda nie przyszła: %s", e)
        if cache_path and cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    return None


def fake() -> dict:
    hours = [f"2026-10-28T{h:02d}:00" for h in range(24)] + [f"2026-10-29T{h:02d}:00" for h in range(24)]
    temps = [5 + 5 * max(0, 1 - abs(h % 24 - 14) / 8) for h in range(48)]
    return {
        "current": {"time": "2026-10-28T08:45", "temperature_2m": 6.4, "apparent_temperature": 2.9, "weather_code": 3,
                    "wind_speed_10m": 24.1, "wind_direction_10m": 260, "relative_humidity_2m": 87},
        "hourly": {"time": hours, "temperature_2m": temps, "precipitation_probability": [10, 20, 40, 60] * 12,
                   "weather_code": [3] * 48},
        "daily": {"time": ["2026-10-28", "2026-10-29"], "temperature_2m_max": [10.2, 9.1], "temperature_2m_min": [4.8, 3.9],
                  "precipitation_sum": [2.1, 0.0], "precipitation_probability_max": [65, 15],
                  "sunrise": ["2026-10-28T06:44", "2026-10-29T06:46"], "sunset": ["2026-10-28T16:14", "2026-10-29T16:12"]},
    }
