"""
Étape 1 – Téléchargement des données ouvertes (toutes autorisées, voir SOURCES.md).

Chaque fichier est mis en cache dans data/raw/ : relancer le script ne retélécharge
que ce qui manque. Usage :  python -m src.download [nom_source ...]
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

UA = {"User-Agent": "hackathon-mobility-epitech/1.0 (open data research)"}


def fetch(url, dest, timeout=600, force=False):
    """Télécharge url -> dest via curl (reprise sur coupure, 5 essais), sauf si déjà présent."""
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  [cache] {dest.name}")
        return dest
    print(f"  [get]   {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    for _ in range(5):
        tmp.unlink(missing_ok=True)       # certains serveurs (INSEE) refusent la reprise
        rc = subprocess.call(["curl", "-sSL", "--retry", "5", "--max-time", str(timeout),
                              "-A", UA["User-Agent"], "-o", str(tmp), url])
        if rc == 0:
            break
    else:
        raise RuntimeError(f"échec du téléchargement : {url}")
    tmp.rename(dest)
    print(f"          -> {dest.name} ({dest.stat().st_size / 1e6:.1f} Mo)")
    return dest


# --------------------------------------------------------------------------- sources simples
def dl_static():
    fetch(C.URLS["filosofi"], C.RAW / "filosofi2021_200m_csv.zip")
    fetch(C.URLS["rp_logement"], C.RAW / "rp2021_logement_iris_csv.zip")
    fetch(C.URLS["omphale"], C.RAW / "omphale_scenario_central.xlsx")
    fetch(C.URLS["gbfs_catalog"], C.RAW / "gbfs_systems.csv", force=False)
    fetch(C.URLS["communes"], C.RAW / "communes.json")
    fetch(C.URLS["pan_api"], C.RAW / "pan_datasets.json")


def dl_stops():
    fetch(C.URLS["stops_fr"], C.RAW / "arrets_france.csv", timeout=1800)


# --------------------------------------------------------------------------- GBFS
def _get_json(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _feeds(discovery):
    """Renvoie {nom_flux: url} pour un gbfs.json v1/v2 (par langue) ou v3."""
    data = discovery.get("data", {})
    if "feeds" in data:                                   # v3
        feeds = data["feeds"]
    else:                                                 # v1/v2 : {"fr": {"feeds": [...]}}
        lang = "fr" if "fr" in data else next(iter(data), None)
        feeds = data.get(lang, {}).get("feeds", []) if lang else []
    return {f["name"]: f["url"] for f in feeds if "name" in f and "url" in f}


def _text(v):
    """GBFS v3 : champs localisés [{'text':..,'language':..}] -> str."""
    if isinstance(v, list):
        return v[0].get("text") if v and isinstance(v[0], dict) else None
    return v


def _one_system(row):
    sid, url = row["System ID"], row["Auto-Discovery URL"]
    out = {"system_id": sid, "name": row["Name"], "location": row["Location"], "ok": False}
    try:
        feeds = _feeds(_get_json(url))
        out["feeds"] = list(feeds)
        stations, vtypes = [], []
        if "station_information" in feeds:
            stations = _get_json(feeds["station_information"]).get("data", {}).get("stations", [])
        if "vehicle_types" in feeds:
            vtypes = _get_json(feeds["vehicle_types"]).get("data", {}).get("vehicle_types", [])
        out["form_factors"] = sorted({v.get("form_factor", "?") for v in vtypes})
        out["propulsion"] = sorted({v.get("propulsion_type", "?") for v in vtypes})
        out["stations"] = [
            {
                "station_id": str(s.get("station_id")),
                "name": _text(s.get("name")),
                "lat": s.get("lat"),
                "lon": s.get("lon"),
                "capacity": s.get("capacity"),
            }
            for s in stations
        ]
        out["ok"] = True
    except Exception as e:  # flux hors ligne, auth, format non conforme…
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    return out


def dl_gbfs():
    dest = C.RAW / "gbfs_france.json"
    if dest.exists():
        print(f"  [cache] {dest.name}")
        return
    cat = pd.read_csv(C.RAW / "gbfs_systems.csv")
    fr = cat[(cat["Country Code"] == "FR") & cat["Auto-Discovery URL"].notna()]
    fr = fr[fr["Authentication Type"].isna()]          # uniquement les flux publics
    print(f"  {len(fr)} systèmes GBFS français publics")
    results = []
    with ThreadPoolExecutor(16) as ex:
        futs = [ex.submit(_one_system, r) for _, r in fr.iterrows()]
        for f in as_completed(futs):
            results.append(f.result())
    ok = sum(r["ok"] for r in results)
    n = sum(len(r.get("stations", [])) for r in results)
    print(f"  GBFS : {ok}/{len(results)} flux lus, {n} stations")
    dest.write_text(json.dumps(results, ensure_ascii=False))


# --------------------------------------------------------------------------- étude de cas Strasbourg
def dl_strasbourg():
    fetch(C.URLS["gtfs_cts"], C.RAW / "gtfs_cts.zip")
    # Fluo 67 : URL du GTFS résolue via le catalogue du PAN déjà téléchargé
    pan = json.loads((C.RAW / "pan_datasets.json").read_text())
    ds = next((d for d in pan if d["slug"] == C.FLUO67_SLUG), None)
    gtfs = [r for r in (ds or {}).get("resources", []) if r.get("format") == "GTFS"]
    if gtfs:
        fetch(gtfs[0]["url"], C.RAW / "gtfs_fluo67.zip")
    for key in ("gbfs_citiz_grandest", "gbfs_velhop"):
        dest = C.RAW / f"{key}_station_information.json"
        if dest.exists():
            continue
        feeds = _feeds(_get_json(C.URLS[key]))
        dest.write_text(json.dumps(_get_json(feeds["station_information"]), ensure_ascii=False))


def dl_osm():
    """Réseau piéton OSM de l'Eurométropole (Overpass) pour calibrer le détour."""
    dest = C.RAW / "osm_walk_strasbourg.json"
    if dest.exists():
        print(f"  [cache] {dest.name}")
        return
    w, s, e, n = C.STRASBOURG_BBOX
    q = f"""
    [out:json][timeout:300];
    way["highway"]["highway"!~"motorway|motorway_link|trunk|trunk_link|construction|proposed|raceway|bus_guideway"]
       ["foot"!~"no"]["access"!~"private|no"]({s},{w},{n},{e});
    (._;>;);
    out body;
    """
    # curl plutôt que requests : la pile SSL système (LibreSSL) échoue sur overpass-api.de
    qfile = C.RAW / "overpass_query.txt"
    qfile.write_text(q)
    for attempt in range(3):
        rc = subprocess.call(["curl", "-sS", "--max-time", "900", "-A", UA["User-Agent"],
                              "--data-urlencode", f"data@{qfile}",
                              "-o", str(dest), C.URLS["overpass"]])
        if rc == 0 and dest.exists() and dest.read_bytes()[:1] == b"{":
            print(f"  OSM : {dest.stat().st_size / 1e6:.1f} Mo")
            return
        dest.unlink(missing_ok=True)
        print("  Overpass, nouvel essai")
        time.sleep(30)


STEPS = {"static": dl_static, "stops": dl_stops, "gbfs": dl_gbfs,
         "strasbourg": dl_strasbourg, "osm": dl_osm}

if __name__ == "__main__":
    for name in sys.argv[1:] or STEPS:
        print(f"== {name}")
        STEPS[name]()
