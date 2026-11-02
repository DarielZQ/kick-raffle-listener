"""Muestra el estado actual de las rondas por secciones ("cajas") del sitio y cuándo se abrieron.

Lee `[trigger].site_url` de `config.toml` (o de `--config`).

Con `--vod-start` (hora de inicio del directo en UTC, ej. 2026-01-01T20:00:00Z) calcula en qué minuto
del VOD se abrió cada ronda, para probar `transcribe_file.py` justo en ese tramo.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raffle_listener.config import is_placeholder, load_config  # noqa: E402
from raffle_listener.triggers.site_poller import SitePoller  # noqa: E402


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vod-start", help="inicio del directo en UTC (ISO 8601)")
    ap.add_argument("--config", default="config.toml", help="ruta a config.toml")
    args = ap.parse_args()

    site_url = load_config(args.config).trigger.site_url
    if is_placeholder(site_url):
        raise SystemExit("Configura [trigger].site_url en config.toml")
    state = SitePoller(site_url, 0, print).fetch()
    rounds = ((state.get("cajas") or {}).get("raffle") or {}).get("rounds") or []
    vod0 = parse(args.vod_start) if args.vod_start else None
    for r in rounds:
        created = parse(r["createdAt"])
        line = f"{r['section']:8} {r['status']:10} abierta {created:%H:%M:%S} UTC"
        if r.get("drawnAt"):
            line += f"  ({(parse(r['drawnAt']) - created).seconds // 60} min)"
        if vod0:
            off = int((created - vod0).total_seconds())
            line += f"  → VOD {off // 3600}:{off % 3600 // 60:02}:{off % 60:02}"
        print(line)
    print(f"Sorteos genéricos abiertos: {len((state.get('raffles') or {}).get('raffles') or [])}")


if __name__ == "__main__":
    main()
