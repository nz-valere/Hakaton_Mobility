"""
Étape 4b – Fréquence des lignes de bus, tram et métro dans une zone d'étude (GTFS).

Pourquoi : l'agrégat national des arrêts (src/offer.py) n'a pas d'horaires. Un arrêt desservi
2 fois par jour y compte autant qu'une station de tram toutes les 5 minutes. Dans les zones où
l'on recommande des sites (territoire prioritaire, Strasbourg), on lit les GTFS des réseaux
(C.FREQ_FEEDS) pour mesurer le service réellement offert.

Méthode
-------
1. Jour de référence : C.FREQ_REF_DATE (mardi hors vacances scolaires) s'il est couvert par le
   GTFS, sinon le mardi qui a le plus de services actifs (calendar + calendar_dates).
2. Départs entre C.FREQ_HOURS[0] et [1] par (arrêt, ligne, sens) -> départs/heure.
   Les lignes scolaires (C.FREQ_EXCLUDE_AGENCIES) et le transport à la demande
   (C.FREQ_EXCLUDE_ROUTE_TYPES) sont écartés, comme dans l'offre nationale (src/offer.py).
3. Pour chaque carreau habité de la zone, lignes ayant au moins un arrêt à
   ≤ geo.walk_radius_m() (même rayon que src/accessibility.py) :
     - une ligne compte UNE fois, avec la meilleure fréquence (départs/h dans un sens) parmi
       ses arrêts proches : la même ligne qui passe à 3 arrêts autour de chez soi, ou dont on
       atteint les deux quais (aller et retour), n'est pas 3 ou 2 options ;
     - tc_freq_options = Σ_lignes min(1, départs/h / C.FULL_OPTION_DEP_H)
       (une ligne toutes les 15 min ou mieux dans un sens = 1 option pleine) ;
     - tc_lines = nombre de lignes distinctes ; tc_dep_h = départs/h cumulés ;
     - freq_nearest = départs/h de la meilleure ligne de l'arrêt le plus proche (sert à la
       qualité de service d'un nouvel arrêt de bus posé sur cette ligne, src/recommend.py).
4. n_options_freq = tc_freq_options + points des autres modes de outputs/cells_access.parquet
   (rail, vélo, free-floating, autopartage, Citiz) : même indice, mais le bus/tram/métro est
   pondéré par le service au lieu d'être compté par arrêt.

Sorties : outputs/frequency_cells_<zone>.parquet (une ligne par carreau : key, colonnes ci-dessus),
outputs/frequency_<zone>.json (jour retenu, réseaux, comparaison comptage vs fréquence).
Usage : python -m src.frequency [--area ems | --area epci:<siren>]   (défaut : toutes les zones de C.FREQ_FEEDS)
"""
import argparse
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

OTHER_MODES = ("rail", "bike", "scooter", "carsharing", "citiz")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


# --------------------------------------------------------------------------- GTFS
def _read(z, name, **kw):
    return pd.read_csv(z.open(name), dtype=str, **kw) if name in z.namelist() else None


def active_services(z, date):
    """service_id actifs à la date AAAAMMJJ (calendar + exceptions de calendar_dates)."""
    wd = WEEKDAYS[datetime.strptime(date, "%Y%m%d").weekday()]   # indépendant de la locale
    on = set()
    cal = _read(z, "calendar.txt")
    if cal is not None:
        on = set(cal.loc[(cal[wd] == "1") & (cal["start_date"] <= date) & (cal["end_date"] >= date), "service_id"])
    cd = _read(z, "calendar_dates.txt")
    if cd is not None:
        cd = cd[cd["date"] == date]
        on |= set(cd.loc[cd["exception_type"] == "1", "service_id"])
        on -= set(cd.loc[cd["exception_type"] == "2", "service_id"])
    return on


def reference_date(z, wanted=None):
    """C.FREQ_REF_DATE s'il a des services, sinon le mardi le plus chargé couvert par le GTFS."""
    wanted = wanted or C.FREQ_REF_DATE
    if active_services(z, wanted):
        return wanted
    dates = set()
    for name, cols in (("calendar.txt", ("start_date", "end_date")), ("calendar_dates.txt", ("date", "date"))):
        t = _read(z, name)
        if t is not None and len(t):
            dates |= {t[cols[0]].min(), t[cols[1]].max()}
    dates.discard(np.nan)
    if not dates:
        raise ValueError(f"{getattr(z, 'filename', z)} : GTFS sans calendrier exploitable")
    lo, hi = min(dates), max(dates)
    d = datetime.strptime(lo, "%Y%m%d")
    best, n_best = None, -1
    while d.strftime("%Y%m%d") <= hi:
        if d.weekday() == 1:
            s = d.strftime("%Y%m%d")
            n = len(active_services(z, s))
            if n > n_best:
                best, n_best = s, n
        d += timedelta(days=1)
    if best is None:
        raise ValueError(f"{getattr(z, 'filename', z)} : aucun mardi dans la période du GTFS")
    return best


def line_frequencies(path, date=None):
    """
    Départs/heure par (arrêt, ligne, sens) sur la plage C.FREQ_HOURS du jour de référence.
    Renvoie (DataFrame [stop_id, lon, lat, line, direction_id, route_name, route_type, dep_h], jour retenu) ;
    `line` = <feed>:<route_id> (sans le sens : une ligne est une option, cf. cell_frequency).
    """
    z = zipfile.ZipFile(path)
    day = reference_date(z, date)
    on = active_services(z, day)
    trips = _read(z, "trips.txt")
    if "direction_id" not in trips:
        trips["direction_id"] = "0"
    trips = trips[trips["service_id"].isin(on)][["trip_id", "route_id", "direction_id"]]
    st = pd.read_csv(z.open("stop_times.txt"), usecols=["trip_id", "stop_id", "departure_time"], dtype=str)
    st = st[st["trip_id"].isin(set(trips["trip_id"]))].dropna(subset=["departure_time"])
    h = pd.to_numeric(st["departure_time"].str.split(":").str[0], errors="coerce")
    h0, h1 = C.FREQ_HOURS
    st = st[(h >= h0) & (h < h1)].merge(trips, on="trip_id")
    dep = st.groupby(["stop_id", "route_id", "direction_id"]).size().rename("dep").reset_index()
    dep["dep_h"] = dep["dep"] / (h1 - h0)
    stops = _read(z, "stops.txt")[["stop_id", "stop_lat", "stop_lon"]]
    routes = _read(z, "routes.txt")
    routes["route_name"] = routes.get("route_short_name", routes["route_id"]).fillna(routes["route_id"])
    drop = routes["route_type"].isin(C.FREQ_EXCLUDE_ROUTE_TYPES)
    if "agency_id" in routes:
        drop |= routes["agency_id"].isin(C.FREQ_EXCLUDE_AGENCIES)
    routes = routes[~drop]
    out = dep.merge(stops, on="stop_id").merge(routes[["route_id", "route_name", "route_type"]], on="route_id")
    feed = Path(path).stem
    out["line"] = feed + ":" + out["route_id"]
    out["direction_id"] = out["direction_id"].fillna("0")
    out["lon"] = pd.to_numeric(out["stop_lon"], errors="coerce")
    out["lat"] = pd.to_numeric(out["stop_lat"], errors="coerce")
    out["stop_id"] = feed + ":" + out["stop_id"]
    out = out.dropna(subset=["lon", "lat"])
    return out[["stop_id", "lon", "lat", "line", "direction_id", "route_name", "route_type", "dep_h"]], day


# --------------------------------------------------------------------------- indicateurs par carreau
def cell_frequency(cells, lines, radius=None, full=None):
    """
    cells : DataFrame avec crs_id, x, y ; lines : sortie de line_frequencies (concaténée).
    Renvoie un DataFrame aligné sur cells : tc_freq_options, tc_lines, tc_dep_h, freq_nearest.
    """
    radius = geo.walk_radius_m() if radius is None else radius
    full = C.FULL_OPTION_DEP_H if full is None else full
    crs, x, y = geo.project(lines["lon"].values, lines["lat"].values)
    keep = crs >= 0
    lines = lines[keep].reset_index(drop=True)
    crs, x, y = crs[keep], x[keep], y[keep]
    n = len(cells)
    opts, nl, deph = np.zeros(n), np.zeros(n, int), np.zeros(n)
    I, J = geo.pairs_within(cells["crs_id"].values, cells["x"].values, cells["y"].values, crs, x, y, radius)
    best = defaultdict(dict)      # carreau -> {ligne : meilleure fréquence dans un sens}
    line_arr, f_arr = lines["line"].values, lines["dep_h"].values
    for i, j in zip(I, J):
        d = best[i]
        if f_arr[j] > d.get(line_arr[j], 0.0):
            d[line_arr[j]] = f_arr[j]
    for i, d in best.items():
        f = np.fromiter(d.values(), float)
        opts[i] = np.minimum(1.0, f / full).sum()
        nl[i] = len(d)
        deph[i] = f.sum()
    # arrêt le plus proche (toutes distances) et sa meilleure ligne (meilleur sens)
    stop_best = lines.groupby("stop_id")["dep_h"].max()
    sp = lines.drop_duplicates("stop_id").set_index("stop_id")
    s_crs, s_x, s_y = geo.project(sp["lon"].values, sp["lat"].values)
    near = np.full(n, np.nan)
    from scipy.spatial import cKDTree
    for cid in np.unique(cells["crs_id"].values):
        mc = cells["crs_id"].values == cid
        ms = s_crs == cid
        if not ms.any():
            continue
        _, k = cKDTree(np.c_[s_x[ms], s_y[ms]]).query(np.c_[cells["x"].values[mc], cells["y"].values[mc]])
        near[mc] = stop_best.reindex(sp.index[ms][k]).values
    return pd.DataFrame({"tc_freq_options": opts, "tc_lines": nl, "tc_dep_h": deph, "freq_nearest": near})


# --------------------------------------------------------------------------- zone
def zone_cells(area):
    """Carreaux habités de la zone (mêmes règles que src/recommend._area_bounds)."""
    from src import recommend
    name, (w, s, e, n), dep, coms = recommend._area_bounds(area)
    filt = [("lon", ">=", w), ("lon", "<=", e), ("lat", ">=", s), ("lat", "<=", n)]
    cells = pd.read_parquet(C.INTERIM / "cells.parquet",
                            columns=["key", "crs_id", "x", "y", "lon", "lat", "com", "dep", "ind", "men"], filters=filt)
    if dep is not None:
        cells = cells[cells["dep"] == dep]
    if coms is not None:
        cells = cells[cells["com"].isin(coms)]
    return name, cells.reset_index(drop=True)


def area_of_name(name):
    """Nom de zone (clé de C.FREQ_FEEDS) -> paramètre `area` de recommend."""
    return "ems" if name == "ems" else ("epci:" + name[4:] if name.startswith("epci") else name)


def frequency_file(name):
    return C.OUT / f"frequency_cells_{name}.parquet"


def run(area):
    name, cells = zone_cells(area)
    feeds = [C.RAW / f for f in C.FREQ_FEEDS.get(name, ()) if (C.RAW / f).exists()]
    if not feeds:
        print(f"  [{name}] aucun GTFS disponible ({C.FREQ_FEEDS.get(name)}) : lancer python -m src.download frequency")
        return None
    parts, days = [], {}
    for f in feeds:
        lf, day = line_frequencies(f)
        parts.append(lf)
        days[f.name] = {"jour": day, "lignes_sens": int(lf["line"].nunique()), "arrets": int(lf["stop_id"].nunique())}
        print(f"  {f.name} : jour {day}, {lf['line'].nunique()} lignes, {lf['stop_id'].nunique()} arrêts")
    lines = pd.concat(parts, ignore_index=True)
    fq = cell_frequency(cells, lines)
    out = pd.concat([cells[["key"]], fq], axis=1)
    # même indice que src/accessibility.py, bus/tram/métro pondérés par le service
    acc_f = C.OUT / "cells_access.parquet"
    pop = cells["ind"].values
    summary = {"zone": name, "jour_reference": days, "plage_horaire": list(C.FREQ_HOURS),
               "option_pleine_departs_h": C.FULL_OPTION_DEP_H, "rayon_m": round(geo.walk_radius_m(), 1),
               "population": float(pop.sum())}
    if acc_f.exists():
        acc = pd.read_parquet(acc_f, columns=["key", "n_options"] + [f"n_{m}" for m in ("transit",) + OTHER_MODES],
                              filters=[("key", "in", cells["key"].tolist())]).set_index("key")
        acc = acc.reindex(cells["key"]).fillna(0)
        other = sum(acc[f"n_{m}"].values for m in OTHER_MODES)
        out["n_options_count"] = acc["n_options"].values
        out["n_transit_count"] = acc["n_transit"].values
        out["n_options_freq"] = fq["tc_freq_options"].values + other
        has_stop = acc["n_transit"].values > 0
        weak = has_stop & (fq["tc_freq_options"].values < 1)
        summary["comparaison"] = {
            "part_pop_arret_tc_5min": float(pop[has_stop].sum() / pop.sum()),
            "part_pop_au_moins_1_option_tc_pleine": float(pop[fq["tc_freq_options"].values >= 1].sum() / pop.sum()),
            "part_pop_arret_mais_service_faible": float(pop[weak].sum() / pop.sum()),
            "arrets_moyens_5min": float((acc["n_transit"].values * pop).sum() / pop.sum()),
            "options_tc_pleines_moyennes_5min": float((fq["tc_freq_options"].values * pop).sum() / pop.sum()),
            "lecture": "« service faible » = au moins un arrêt à 5 min, mais moins d'une ligne toutes les 15 min "
                       "en cumulé (somme des min(1, départs/h ÷ 4)).",
        }
        print("  " + json.dumps(summary["comparaison"], ensure_ascii=False))
    out.to_parquet(frequency_file(name), index=False)
    (C.OUT / f"frequency_{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {frequency_file(name).name} ({len(out):,} carreaux)")
    return out, summary


def main():
    ap = argparse.ArgumentParser(description="Fréquence des lignes TC dans les zones d'étude")
    ap.add_argument("--area", default=None, help="'ems' ou 'epci:<siren>' (défaut : toutes les zones configurées)")
    a = ap.parse_args()
    areas = [a.area] if a.area else [area_of_name(n) for n in C.FREQ_FEEDS]
    for area in areas:
        print(f"== {area}")
        run(area)


if __name__ == "__main__":
    main()
