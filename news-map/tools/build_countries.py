"""Jednorazowy skrypt: buduje data/countries.json z kształtów Natural Earth (world-atlas)
oraz mapowania kodów FIPS (używanych przez GDELT) na ISO.

Użycie: python tools/build_countries.py world50.geojson data/countries.json [states.geojson]
(world50.geojson = countries-50m.json z pakietu npm world-atlas przekonwertowany topojson-client)
"""
import json
import sys

import geonamescache
from babel import Locale

src, dst = sys.argv[1], sys.argv[2]
geo = json.load(open(src, encoding="utf-8"))
gc = geonamescache.GeonamesCache().get_countries()
by_num = {str(c["isonumeric"]).zfill(3): c for c in gc.values()}
pl = Locale("pl").territories

# Kształty bez kodu numerycznego w Natural Earth -> przypisujemy ręcznie
MANUAL = {"Kosovo": "XK", "Somaliland": "SO", "N. Cyprus": "CY", "Siachen Glacier": "IN", "Indian Ocean Ter.": "AU"}


def simplify(ring, tol=0.12):
    out = []
    for x, y in ring:
        x, y = round(x, 2), round(y, 2)
        if out and abs(out[-1][0] - x) < tol and abs(out[-1][1] - y) < tol:
            continue
        out.append([x, y])
    return out if len(out) >= 4 else None


countries = {}
for f in geo["features"]:
    name = f["properties"]["name"]
    iso = MANUAL.get(name)
    if iso is None:
        c = by_num.get(str(f.get("id")).zfill(3))
        if c is None:
            print("brak kodu dla", name, f.get("id"))
            continue
        iso = c["iso"]
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    rings = []
    for poly in polys:
        r = simplify(poly[0])  # tylko obrys zewnętrzny – dziury są zbędne przy 800 px
        if r:
            rings.append(r)
    entry = countries.setdefault(iso, {"iso": iso, "rings": []})
    entry["rings"].extend(rings)

# Kody FIPS -> ISO. GeoNames ma kolumnę FIPS 10-4, której używa GDELT.
fips_to_iso = {c["fips"]: c["iso"] for c in gc.values() if c.get("fips")}
# Wyjątki znane z GDELT
fips_to_iso.update({"GZ": "PS", "WE": "PS", "KV": "XK", "OD": "SS", "RI": "RS", "MJ": "ME"})

for iso, entry in countries.items():
    c = gc.get(iso)
    entry["name_pl"] = pl.get(iso) or (c["name"] if c else iso)
    entry["name_en"] = c["name"] if c else iso

# ---- stany USA (us-atlas states-10m) – GDELT podaje je jako ADM1 "USCA", "USTX"... ----
US_STATES = {
    "Alabama": ("AL", "Alabama"), "Alaska": ("AK", "Alaska"), "Arizona": ("AZ", "Arizona"),
    "Arkansas": ("AR", "Arkansas"), "California": ("CA", "Kalifornia"), "Colorado": ("CO", "Kolorado"),
    "Connecticut": ("CT", "Connecticut"), "Delaware": ("DE", "Delaware"),
    "District of Columbia": ("DC", "Waszyngton D.C."), "Florida": ("FL", "Floryda"),
    "Georgia": ("GA", "Georgia"), "Hawaii": ("HI", "Hawaje"), "Idaho": ("ID", "Idaho"),
    "Illinois": ("IL", "Illinois"), "Indiana": ("IN", "Indiana"), "Iowa": ("IA", "Iowa"),
    "Kansas": ("KS", "Kansas"), "Kentucky": ("KY", "Kentucky"), "Louisiana": ("LA", "Luizjana"),
    "Maine": ("ME", "Maine"), "Maryland": ("MD", "Maryland"), "Massachusetts": ("MA", "Massachusetts"),
    "Michigan": ("MI", "Michigan"), "Minnesota": ("MN", "Minnesota"), "Mississippi": ("MS", "Missisipi"),
    "Missouri": ("MO", "Missouri"), "Montana": ("MT", "Montana"), "Nebraska": ("NE", "Nebraska"),
    "Nevada": ("NV", "Nevada"), "New Hampshire": ("NH", "New Hampshire"), "New Jersey": ("NJ", "New Jersey"),
    "New Mexico": ("NM", "Nowy Meksyk"), "New York": ("NY", "Nowy Jork"),
    "North Carolina": ("NC", "Karolina Płn."), "North Dakota": ("ND", "Dakota Płn."), "Ohio": ("OH", "Ohio"),
    "Oklahoma": ("OK", "Oklahoma"), "Oregon": ("OR", "Oregon"), "Pennsylvania": ("PA", "Pensylwania"),
    "Rhode Island": ("RI", "Rhode Island"), "South Carolina": ("SC", "Karolina Płd."),
    "South Dakota": ("SD", "Dakota Płd."), "Tennessee": ("TN", "Tennessee"), "Texas": ("TX", "Teksas"),
    "Utah": ("UT", "Utah"), "Vermont": ("VT", "Vermont"), "Virginia": ("VA", "Wirginia"),
    "Washington": ("WA", "Waszyngton"), "West Virginia": ("WV", "Wirginia Zach."),
    "Wisconsin": ("WI", "Wisconsin"), "Wyoming": ("WY", "Wyoming"),
}
subdivisions = {}
if len(sys.argv) > 3:
    st = json.load(open(sys.argv[3], encoding="utf-8"))
    for f in st["features"]:
        name = f["properties"]["name"]
        if name not in US_STATES:
            continue  # terytoria (Portoryko, Guam...) pomijamy
        code, name_pl = US_STATES[name]
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [r for r in (simplify(p[0], tol=0.05) for p in polys) if r]
        subdivisions[f"US-{code}"] = {"iso": f"US-{code}", "parent": "US", "name_pl": name_pl,
                                      "name_en": name, "rings": rings}

json.dump({"countries": countries, "subdivisions": subdivisions, "fips_to_iso": fips_to_iso},
          open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("krajów z kształtem:", len(countries), "stanów USA:", len(subdivisions), "mapowań FIPS:", len(fips_to_iso))
