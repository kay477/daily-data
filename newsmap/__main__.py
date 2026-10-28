"""Uruchomienie całego potoku:  python -m newsmap --state site/state --out site

Kroki: pobierz brakujące pliki GDELT -> policz anomalie -> nagłówki -> obrazek.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import gdelt, headlines, markets, render, score, screens, weather

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Mapa świata: gdzie dzieje się coś ważnego")
    p.add_argument("--state", type=Path, default=Path("site/state"), help="folder ze stanem (historia)")
    p.add_argument("--out", type=Path, default=Path("site"), help="folder na preview.png / news.bin")
    p.add_argument("--backfill-days", type=int, default=30, help="ile dni historii pobrać przy pierwszym starcie")
    p.add_argument("--scheme", choices=sorted(render.SCHEMES), default=render.DEFAULT_SCHEME)
    p.add_argument("--tz", default="Europe/Warsaw")
    p.add_argument("--stories", type=int, default=4)
    p.add_argument("--fake", action="store_true", help="test na sztucznych danych (bez internetu)")
    p.add_argument("--no-markets", action="store_true", help="bez paska giełdowego (stara legenda)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("newsmap")

    data = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
    countries, fips_to_iso = data["countries"], data["fips_to_iso"]

    state = gdelt.State.load(a.state)
    if a.fake:
        from tools import fake_gdelt  # noqa: PLC0415
        n = gdelt.update(state, fips_to_iso, a.backfill_days, fetch=fake_gdelt.fetch, latest=fake_gdelt.LATEST)
    else:
        n = gdelt.update(state, fips_to_iso, a.backfill_days)
    log.info("Przetworzono %d nowych plików", n)
    state.save(a.state)

    scores, baseline_days, when_utc = score.score(state)
    top = score.top_stories(scores, a.stories)
    log.info("Historia: %d dni. Top: %s", baseline_days,
             ", ".join(f"{s.iso} z={s.z} x{s.ratio} ({s.articles})" for s in top))

    if a.fake:
        titles = {s.iso: fake_gdelt.titles(s.iso) for s in top}
    else:
        titles = headlines.collect(state, [s.iso for s in top])
    names = {s.iso: render.display_name(s.iso, data) for s in top}
    text = headlines.summarize_pl(titles, names, max_chars=70)

    stories = [{"iso": s.iso, "name": names[s.iso], "text": text.get(s.iso) or "brak nagłówków"} for s in top]
    levels = {s.iso: s.level for s in scores if s.level}
    when = when_utc.astimezone(ZoneInfo(a.tz))
    quotes = markets.fake() if a.fake else ([] if a.no_markets else markets.fetch(a.state))
    render.render(levels, stories, when, a.out, baseline_days, a.scheme, quotes)

    # dodatkowe ekrany (przyciski na obudowie) – błąd w nich nie może zepsuć mapy
    now = datetime.now(ZoneInfo(a.tz)) if not a.fake else when
    try:
        hist = markets.fake_history() if a.fake else markets.history(a.state)
        screens.render_markets(hist, quotes, now, a.out, a.scheme)
    except Exception:  # noqa: BLE001
        log.exception("Ekran RYNKI się nie wygenerował")
    try:
        w = weather.fake() if a.fake else weather.fetch(a.state)
        screens.render_briefing(w, screens.digest_titles(now), stories, quotes, now, a.out, a.scheme)
    except Exception:  # noqa: BLE001
        log.exception("Ekran BRIEFING się nie wygenerował")

    meta = {
        "generated_utc": when_utc.astimezone(timezone.utc).isoformat(),
        "baseline_days": baseline_days,
        "stories": stories,
        "titles": titles,
        "markets": quotes,
        "markets_errors": markets.ERRORS,
        "scores": [s.__dict__ for s in scores[:30]],
    }
    (a.out / "news.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Gotowe: %s", a.out.resolve())


if __name__ == "__main__":
    main()
