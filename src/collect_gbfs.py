"""
Collecte de l'usage réel des stations Citiz : relevé des flux GBFS 3.0 de tous les réseaux Citiz
toutes les C.GBFS_COLLECT_INTERVAL_S secondes (TTL des flux).

Pourquoi : un flux GBFS est une photo instantanée, sans historique. En le relevant toutes les
5 minutes, la part du temps où les voitures d'une station sont réservées (`is_reserved`) donne un
taux d'occupation : le seul signal d'USAGE observé du projet (src/usage.py).

Constat sur les flux Citiz (octobre 2026) : `num_vehicles_available` de station_status compte
presque toutes les voitures comme libres et n'est pas utilisable ; `vehicle_status` expose par
voiture `is_reserved`, qui change d'un relevé à l'autre. Sémantique exacte à confirmer avec Citiz
(réservée en ce moment ? réservation à venir ?).

Vie privée : on ne garde que des TOTAUX par station (voitures, réservées, désactivées). Aucun
identifiant ni position de voiture n'est stocké.

Sortie : C.GBFS_COLLECT/citiz_status_<jour>.csv (ts_utc, provider_id, station_id, n_vehicles,
n_reserved, n_disabled) et citiz_stations_p<réseau>_<jour>.json (station_information, 1 fois/jour).
Usage : python -m src.collect_gbfs [--hours 96] [--once]      (le PC doit rester allumé)
"""
import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

# Réseaux Citiz publiés sur backend.citiz.fr (catalogue MobilityData, octobre 2026)
CITIZ_PROVIDERS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 16, 18, 19, 20, 22, 23)
CITIZ_URL = "https://backend.citiz.fr/public/provider/{}/gbfs/3.0/gbfs.json"
UA = {"User-Agent": "hackathon-mobility-epitech/1.0 (open data research)"}
OUT = C.GBFS_COLLECT


def _get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def _feeds(discovery):
    data = discovery["data"]
    feeds = data["feeds"] if "feeds" in data else next(iter(data.values()))["feeds"]
    return {f["name"]: f["url"] for f in feeds}


def _log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(OUT / "collect.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def aggregate(vehicles):
    """Totaux par station : {station_id: [voitures, réservées, désactivées]} (aucune donnée de véhicule)."""
    agg = defaultdict(lambda: [0, 0, 0])
    for v in vehicles:
        a = agg[str(v.get("station_id") or v.get("home_station_id") or "?")]
        a[0] += 1
        a[1] += bool(v.get("is_reserved"))
        a[2] += bool(v.get("is_disabled"))
    return agg


def snapshot(feeds_cache):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    day = ts[:10]
    rows = []
    for pid in CITIZ_PROVIDERS:
        try:
            if pid not in feeds_cache:
                feeds_cache[pid] = _feeds(_get(CITIZ_URL.format(pid)))
            fm = feeds_cache[pid]
            info = OUT / f"citiz_stations_p{pid}_{day}.json"
            if not info.exists():
                info.write_text(json.dumps(_get(fm["station_information"]), ensure_ascii=False), encoding="utf-8")
            vehicles = _get(fm["vehicle_status"])["data"]["vehicles"]
        except Exception as e:
            feeds_cache.pop(pid, None)
            _log(f"ERREUR réseau {pid} : {e}")
            continue
        rows += [[ts, pid, sid, n, r, d] for sid, (n, r, d) in aggregate(vehicles).items()]
    path = OUT / f"citiz_status_{day}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts_utc", "provider_id", "station_id", "n_vehicles", "n_reserved", "n_disabled"])
        w.writerows(rows)
    _log(f"relevé ok : {len(rows)} stations")


def main():
    ap = argparse.ArgumentParser(description="Collecte GBFS Citiz (usage réel)")
    ap.add_argument("--hours", type=float, default=96)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cache = {}
    if a.once:
        snapshot(cache)
        return
    end = time.time() + a.hours * 3600
    _log(f"début de la collecte pour {a.hours} h")
    while time.time() < end:
        t = time.time()
        try:
            snapshot(cache)
        except Exception as e:
            _log(f"ERREUR relevé : {e}")
        time.sleep(max(5, C.GBFS_COLLECT_INTERVAL_S - (time.time() - t)))


if __name__ == "__main__":
    main()
