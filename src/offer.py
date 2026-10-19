"""
Étape 3 – Offre de mobilité : arrêts GTFS (agrégat national) + stations GBFS
(vélos, trottinettes, autopartage, Citiz), classés par mode et dédoublonnés.

Sortie : data/interim/offer.parquet, une ligne par point d'offre (schéma CONTRACTS.md).

Méthode
-------
1. Arrêts de transport en commun (data/raw/arrets_france.csv, agrégat national
   transport.data.gouv.fr, NON dédoublonné : un même arrêt peut y figurer 2-3 fois,
   via le jeu du réseau, l'agrégat régional et parfois le jeu SNCF).
   - On ne garde que location_type 0 (ou vide) = quais / points d'arrêt ; les zones
     d'arrêt (1) et les entrées de station (2) feraient double compte.
   - Jeux exclus (pas une offre « de proximité » ouverte à tous au quotidien) :
     cars longue distance FlixBus / BlaBlaCar Bus (réservation, 1-3 départs/jour ;
     FlixTrain est dans le même jeu mais ses gares sont déjà des gares SNCF),
     ferries Corsica / Brittany, vols, lignes de covoiturage, transport à la demande
     zonal (« TAD » : points virtuels sur réservation) et réseaux purement scolaires.
     Les réseaux « urbains et scolaires » et les agrégats régionaux, eux, sont gardés
     (on ne peut pas y isoler les arrêts scolaires : légère surestimation rurale).
   - Classification rail / transit (le fichier n'a pas de route_type) :
       * jeux ferroviaires (SNCF TGV-Intercités-TER, SNCF Transilien, Trains régionaux
         ZOU! / Hauts-de-France, BreizhGo TER, Eurostar, Trenitalia, AVE) -> rail,
         sauf les arrêts « OCECar » / « OCENavette » (autocars TER) -> transit ;
       * autres jeux (urbains, interurbains, agrégats) : le stop_id SNCF est
         normalisé (« StopPoint:OCETrain TER-87… », « SNCF:OCETGVINOUI… ») ; un arrêt
         dont l'identifiant contient OCE + Train/TGV/INTERCITES/OUIGO/TramTrain/ICE/Lyria
         est classé rail, sinon transit ;
       * IDFM : les identifiants « IDFM:… » des quais présents dans le jeu SNCF
         Transilien (Transilien + RER + TER francilien) sont classés rail ; le reste
         (bus, tram, métro RATP) est transit.
     Limites : le métro et le tram sont dans « transit » (conforme à C.MODES) ; quelques
     gares publiées dans des agrégats avec un identifiant local (ex. TER des Pays de la
     Loire via Aléop) restent en transit — elles fusionnent alors le plus souvent avec
     l'arrêt de bus « Gare » voisin.
2. Stations GBFS (data/raw/gbfs_france.json, catalogue MobilityData, flux publics) :
   - nom contenant « Citiz » -> citiz (Yélo La Rochelle n'expose aucune station dans
     son flux ; son autopartage est déjà publié par « Citiz La Rochelle ») ;
   - autre système avec form_factor car -> carsharing (Clem, Marguerite, Optymo ALS…) ;
     Getaround (voitures entre particuliers) n'expose pas de stations -> ignoré ;
   - opérateurs free-floating (Bird, Dott, Lime, Voi, Pony, Yego…) -> scooter, quelle
     que soit la flotte (trottinettes ou vélos) : leurs « stations » sont des zones de
     stationnement virtuelles, pas des stations équipées. On les garde (c'est une
     offre réellement disponible à pied) mais on les isole du mode bike pour que
     « bike » reste le vélo en libre-service à stations, objet des recommandations ;
   - autres systèmes vélo (y compris mixtes bicycle + scooter_standing des opérateurs
     de VLS publics type Fifteen / Ecovélo, dont les stations sont physiques) -> bike ;
     systèmes « scooter » seuls -> scooter.
3. Coordonnées : on écarte les points NaN, (0,0) ou hors des emprises de la France
   (C.FRANCE_BBOXES) ; projection via geo.project() (crs_id = -1 hors territoires
   Filosofi : Guadeloupe, Guyane, Mayotte, gares frontalières étrangères conservées
   car elles servent les carreaux frontaliers).
4. Dédoublonnage par mode : deux points du même mode à moins de C.DEDUP_RADIUS_M
   (C.DEDUP_RADIUS_RAIL_M pour les gares, C.DEDUP_RADIUS_FREEFLOAT_M pour les zones
   free-floating, très denses et partagées entre opérateurs) sont reliés (KD-tree) et chaque composante
   connexe devient un seul point : centroïde, nom le plus fréquent, source/identifiant
   d'un membre représentatif (jeu du réseau de préférence à l'agrégat), capacité
   GBFS sommée. Le chaînage (single linkage) peut fusionner des points plus éloignés
   que le rayon : l'extension maximale des groupes est affichée pour contrôle.
"""
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

OUT_FILE = C.INTERIM / "offer.parquet"
TERR = {-1: "Hors Filosofi", 0: "Métropole", 1: "Martinique", 2: "La Réunion"}

# --- classification des jeux GTFS par leur titre
EXCLUDED_DATASETS = re.compile(
    r"FlixBus|BlaBlaCar Bus|Corsica Ferries|Brittany Ferries|vols |covoiturage|^TAD |^Réseau scolaire")
RAIL_DATASETS = re.compile(
    r"^Réseau SNCF|^SNCF Transilien|^Trains régionaux|BreizhGo TER|Trenitalia|Eurostar|AVE Renfe")
AGGREGATE = re.compile(r"^Agrégat")
# --- classification des arrêts par identifiant SNCF normalisé (OCE = référentiel SNCF)
RAIL_ID = re.compile(r"OCE[ x]?(?:Train|TGV|INTERCITES|OUIGO|TramTrain|ICE|Lyria)")
COACH_ID = re.compile(r"OCE[ x]?(?:Car|Navette)")

# --- classification des systèmes GBFS
FREE_FLOATING = re.compile(r"^(Bird|Dott|Lime|Voi|Pony|YEGO|Tier|Cooltra)\b", re.I)


# =========================================================================== GTFS
def load_stops():
    """Quais / arrêts (location_type 0) de l'agrégat national, colonnes utiles seulement."""
    cols = ["dataset_custom_title", "dataset_organisation", "dataset_id", "stop_id",
            "stop_name", "stop_lat", "stop_lon", "location_type"]
    df = pd.read_csv(C.RAW / "arrets_france.csv", usecols=cols, dtype=str)
    print(f"  arrets_france : {len(df):,} lignes, {df['dataset_id'].nunique()} jeux")
    df = df[df["location_type"].fillna("0").isin(["0", ""])]
    print(f"  location_type 0 : {len(df):,} quais / arrêts")
    return df


def classify_stops(df):
    """Ajoute la colonne mode (rail / transit) ; supprime les jeux exclus."""
    title = df["dataset_custom_title"].fillna("")
    excl = title.str.contains(EXCLUDED_DATASETS)
    print(f"  jeux exclus : {excl.sum():,} arrêts "
          f"({', '.join(sorted(title[excl].unique())[:8])}…)")
    df, title = df[~excl].copy(), title[~excl]

    sid = df["stop_id"].fillna("")
    rail_ds = title.str.contains(RAIL_DATASETS)
    coach = sid.str.contains(COACH_ID)
    rail_id = sid.str.contains(RAIL_ID)
    # quais IDFM présents dans le jeu SNCF Transilien = Transilien / RER / TER
    transilien_ids = set(sid[title == "SNCF Transilien"])
    idfm_rail = title.str.contains("IDFM") & sid.isin(transilien_ids)

    is_rail = (rail_ds & ~coach) | rail_id | idfm_rail
    df["mode"] = np.where(is_rail, "rail", "transit")
    print(f"  rail : {is_rail.sum():,} (dont {(rail_id & ~rail_ds).sum():,} repérés par "
          f"identifiant SNCF dans un jeu mixte, {idfm_rail.sum():,} IDFM-Transilien) ; "
          f"transit : {(~is_rail).sum():,} (dont {(rail_ds & coach).sum():,} autocars TER)")
    return df


def stops_to_points(df):
    """Format commun des points bruts avant dédoublonnage."""
    return pd.DataFrame({
        "mode": df["mode"].values,
        "name": df["stop_name"].fillna("").str.strip().values,
        "lon": pd.to_numeric(df["stop_lon"], errors="coerce").values,
        "lat": pd.to_numeric(df["stop_lat"], errors="coerce").values,
        "source": df["dataset_custom_title"].values,
        "operator": df["dataset_organisation"].fillna(df["dataset_custom_title"]).values,
        "capacity": np.nan,
        "src_key": ("gtfs" + df["dataset_id"].astype(str)).values,
        "raw_id": df["stop_id"].astype(str).values,
        "prio": df["dataset_custom_title"].str.contains(AGGREGATE).astype(int).values,
    })


# =========================================================================== GBFS
def gbfs_mode(system):
    """Mode d'un système GBFS selon son nom et ses form_factors (cf. docstring)."""
    name = system.get("name") or ""
    ff = set(system.get("form_factors") or [])
    if "citiz" in name.lower():
        return "citiz"
    if "car" in ff:
        return "carsharing"
    if FREE_FLOATING.search(name):
        return "scooter"
    if ff and ff <= {"scooter", "scooter_standing", "moped"}:
        return "scooter"
    return "bike"          # bicycle, cargo_bicycle, mixte vélo + trottinette, ou non renseigné


def gbfs_operator(name):
    m = FREE_FLOATING.search(name)
    if m:
        return m.group(1).capitalize()
    return "Citiz" if "citiz" in name.lower() else name


def load_gbfs():
    systems = json.loads((C.RAW / "gbfs_france.json").read_text())
    rows, per_mode = [], {}
    for s in systems:
        stations = s.get("stations") or []
        if not s.get("ok") or not stations:
            continue
        mode = gbfs_mode(s)
        per_mode[mode] = per_mode.get(mode, 0) + 1
        for st in stations:
            rows.append({
                "mode": mode, "name": (st.get("name") or s["name"]).strip(),
                "lon": st.get("lon"), "lat": st.get("lat"),
                "source": s["name"], "operator": gbfs_operator(s["name"]),
                "capacity": st.get("capacity"),
                "src_key": "gbfs-" + s["system_id"], "raw_id": str(st.get("station_id")),
                "prio": 0,
            })
    df = pd.DataFrame(rows)
    df[["lon", "lat", "capacity"]] = df[["lon", "lat", "capacity"]].apply(pd.to_numeric, errors="coerce")
    n0 = len(df)
    df = df.drop_duplicates(["src_key", "raw_id"])
    print(f"  GBFS : {len(systems)} systèmes, {sum(per_mode.values())} avec stations "
          f"({per_mode}) ; {len(df):,} stations ({n0 - len(df)} doublons d'identifiant)")
    return df


# =========================================================================== nettoyage géographique
def in_france(lon, lat):
    ok = np.zeros(len(lon), bool)
    for w, s, e, n in C.FRANCE_BBOXES:
        ok |= (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    return ok


def clean_coords(pts):
    lon, lat = pts["lon"].values, pts["lat"].values
    bad_nan = np.isnan(lon) | np.isnan(lat)
    bad_zero = (np.abs(lon) < 1e-6) & (np.abs(lat) < 1e-6)
    keep = ~bad_nan & ~bad_zero & in_france(np.nan_to_num(lon), np.nan_to_num(lat))
    print(f"  coordonnées écartées : {(~keep).sum():,} (NaN {bad_nan.sum()}, (0,0) {bad_zero.sum()}, "
          f"hors France {(~keep & ~bad_nan & ~bad_zero).sum()})")
    return pts[keep].reset_index(drop=True)


def metric_xy(lon, lat):
    """Coordonnées métriques pour le voisinage : CRS Filosofi, sinon équirectangulaire local."""
    crs, x, y = geo.project(lon, lat)
    m = crs == -1
    x[m] = lon[m] * 111_320 * np.cos(np.radians(lat[m]))
    y[m] = lat[m] * 110_540
    return crs, x, y


# =========================================================================== dédoublonnage
def cluster_labels(x, y, radius):
    """Composantes connexes du graphe « distance < radius » (single linkage)."""
    n = len(x)
    if n == 0:
        return np.array([], int)
    pairs = cKDTree(np.c_[x, y]).query_pairs(radius, output_type="ndarray")
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return connected_components(g, directed=False)[1]


def dedup_radius(mode):
    return {"rail": C.DEDUP_RADIUS_RAIL_M, "scooter": C.DEDUP_RADIUS_FREEFLOAT_M}.get(mode, C.DEDUP_RADIUS_M)


def assign_clusters(pts):
    """Identifiant de groupe global, calculé par (mode, territoire)."""
    crs, x, y = metric_xy(pts["lon"].values, pts["lat"].values)
    pts["_crs"], pts["_x"], pts["_y"] = crs, x, y
    pts["cl"] = -1
    offset = 0
    for (mode, _), idx in pts.groupby(["mode", "_crs"]).groups.items():
        radius = dedup_radius(mode)
        lab = cluster_labels(pts.loc[idx, "_x"].values, pts.loc[idx, "_y"].values, radius)
        pts.loc[idx, "cl"] = lab + offset
        offset += lab.max() + 1
    return pts


def merge_clusters(pts):
    """Un point par groupe : centroïde, nom le plus fréquent, membre représentatif."""
    agg = pts.groupby("cl").agg(lon=("lon", "mean"), lat=("lat", "mean"),
                                cx=("_x", "mean"), cy=("_y", "mean"),
                                capacity=("capacity", lambda s: s.sum(min_count=1)),
                                n=("lon", "size"))
    # extension du groupe (contrôle du chaînage)
    d = np.hypot(pts["_x"] - pts["cl"].map(agg["cx"]), pts["_y"] - pts["cl"].map(agg["cy"]))
    agg["extent"] = d.groupby(pts["cl"]).max()

    names = (pts.groupby(["cl", "name"]).size().rename("k").reset_index()
             .sort_values(["cl", "k", "name"], ascending=[True, False, True])
             .drop_duplicates("cl").set_index("cl")["name"])
    rep = (pts[pts["name"].values == pts["cl"].map(names).values]
           .sort_values(["cl", "prio", "src_key", "raw_id"]).drop_duplicates("cl").set_index("cl"))
    out = rep[["mode", "name", "source", "operator", "src_key", "raw_id"]].join(agg)
    return out.reset_index(drop=True)


def dedup(pts):
    before = pts["mode"].value_counts()
    pts = assign_clusters(pts)
    out = merge_clusters(pts)
    after = out["mode"].value_counts()
    stats = pd.DataFrame({"avant": before, "après": after})
    stats["réduction %"] = (100 * (1 - stats["après"] / stats["avant"])).round(1)
    stats["taille max groupe"] = out.groupby("mode")["n"].max()
    stats["extension max (m)"] = out.groupby("mode")["extent"].max().round(0)
    stats["groupes > 150 m"] = out[out["extent"] > 150].groupby("mode").size()
    print("  Dédoublonnage :\n" + stats.fillna(0).to_string())
    return out


# =========================================================================== mise au schéma
def finalize(out):
    crs_id, x, y = geo.project(out["lon"].values, out["lat"].values)
    oid = out["mode"] + ":" + out["src_key"] + ":" + out["raw_id"]
    dup = oid.duplicated(keep=False)
    if dup.any():                                       # même stop_id dans 2 groupes distincts
        oid[dup] = oid[dup] + "#" + oid[dup].groupby(oid[dup]).cumcount().astype(str)
    df = pd.DataFrame({
        "offer_id": oid.astype(str),
        "mode": out["mode"].astype(str),
        "name": out["name"].astype(str),
        "lon": out["lon"].astype(float), "lat": out["lat"].astype(float),
        "crs_id": crs_id.astype(np.int8), "x": x, "y": y,
        "source": out["source"].astype(str),
        "operator": out["operator"].astype(str),
        "capacity": out["capacity"].astype(float),
    })
    assert df["offer_id"].is_unique and df["mode"].isin(list(C.MODES)).all()
    return df.sort_values(["mode", "offer_id"]).reset_index(drop=True)


# =========================================================================== contrôles
def in_strasbourg(lon, lat):
    w, s, e, n = C.STRASBOURG_BBOX
    return (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)


def summary(df):
    t = pd.crosstab(df["mode"], df["crs_id"].map(TERR))
    t["Total"] = t.sum(axis=1)
    t["Strasbourg (bbox)"] = df[in_strasbourg(df["lon"], df["lat"])]["mode"].value_counts()
    print("  Points d'offre par mode et territoire :\n" + t.fillna(0).astype(int).to_string())


def cts_gtfs_stops():
    """Arrêts du GTFS CTS (+ type tram/bus via stop_times -> trips -> routes)."""
    z = zipfile.ZipFile(C.RAW / "gtfs_cts.zip")
    stops = pd.read_csv(z.open("stops.txt"), dtype={"stop_id": str})
    routes = pd.read_csv(z.open("routes.txt"), dtype={"route_id": str})
    trips = pd.read_csv(z.open("trips.txt"), usecols=["route_id", "trip_id"], dtype=str)
    st = pd.read_csv(z.open("stop_times.txt"), usecols=["trip_id", "stop_id"], dtype=str).drop_duplicates()
    rt = trips.merge(routes[["route_id", "route_type"]], on="route_id")[["trip_id", "route_type"]]
    st = st.merge(rt.drop_duplicates("trip_id"), on="trip_id")
    tram_ids = set(st.loc[st["route_type"] == 0, "stop_id"])
    served = set(st["stop_id"])
    stops = stops[stops["stop_id"].isin(served)].copy()
    stops["tram"] = stops["stop_id"].isin(tram_ids)
    return stops


def n_dedup(lon, lat, radius=None):
    _, x, y = geo.project(np.asarray(lon, float), np.asarray(lat, float))
    lab = cluster_labels(x, y, radius or C.DEDUP_RADIUS_M)
    return len(np.unique(lab)), x, y


def check_strasbourg(df):
    print("  Contrôle Strasbourg :")
    stra = df[in_strasbourg(df["lon"], df["lat"])]
    tr = stra[stra["mode"] == "transit"]
    # 1) arrêts CTS
    cts = cts_gtfs_stops()
    n_cts, cx, cy = n_dedup(cts["stop_lon"], cts["stop_lat"])
    n_tram, _, _ = n_dedup(cts.loc[cts["tram"], "stop_lon"], cts.loc[cts["tram"], "stop_lat"])
    d, _ = cKDTree(np.c_[tr["x"], tr["y"]]).query(np.c_[cx, cy])
    print(f"    GTFS CTS : {len(cts)} quais desservis -> {n_cts} arrêts dédoublonnés "
          f"(dont {n_tram} arrêts tram) ; offre transit dans la bbox : {len(tr)} points "
          f"(dont {(tr['source'] == 'Réseau urbain CTS').sum()} représentés par le jeu CTS)")
    print(f"    quais CTS à < {C.DEDUP_RADIUS_M} m d'un point transit de l'offre : "
          f"{(d < C.DEDUP_RADIUS_M).mean():.1%} (médiane {np.median(d):.0f} m)")
    # 2) Fluo 67 (cars interurbains)
    z = zipfile.ZipFile(C.RAW / "gtfs_fluo67.zip")
    fl = pd.read_csv(z.open("stops.txt"), dtype=str)
    if "location_type" in fl:
        fl = fl[fl["location_type"].fillna("0").isin(["0", ""])]
    fl[["stop_lon", "stop_lat"]] = fl[["stop_lon", "stop_lat"]].astype(float)
    fl = fl[in_strasbourg(fl["stop_lon"], fl["stop_lat"])]
    if len(fl):
        _, fx, fy = geo.project(fl["stop_lon"].values, fl["stop_lat"].values)
        d, _ = cKDTree(np.c_[tr["x"], tr["y"]]).query(np.c_[fx, fy])
        print(f"    GTFS Fluo 67 : {len(fl)} quais dans la bbox, {(d < C.DEDUP_RADIUS_M).mean():.1%} "
              f"couverts par l'offre transit")
    # 3) Citiz Grand Est et Vélhop : flux directs vs offre
    for key, mode, label in (("gbfs_citiz_grandest", "citiz", "Citiz Grand Est"),
                             ("gbfs_velhop", "bike", "Vélhop")):
        f = C.RAW / f"{key}_station_information.json"
        if not f.exists():
            continue
        st = pd.DataFrame(json.loads(f.read_text())["data"]["stations"])
        n_in = in_strasbourg(st["lon"], st["lat"]).sum()
        n_off = (stra["mode"] == mode).sum()
        print(f"    {label} : flux direct {len(st)} stations ({n_in} dans la bbox) ; "
              f"offre {mode} dans la bbox : {n_off} points")


# =========================================================================== main
def main():
    t0 = time.time()
    print("[offer] arrêts GTFS")
    stops = classify_stops(load_stops())
    pts_gtfs = stops_to_points(stops)
    print("[offer] stations GBFS")
    pts_gbfs = load_gbfs()
    pts = pd.concat([pts_gtfs, pts_gbfs], ignore_index=True)
    print(f"[offer] {len(pts):,} points bruts")
    pts = clean_coords(pts)
    out = dedup(pts)
    df = finalize(out)
    df.to_parquet(OUT_FILE, index=False)
    summary(df)
    check_strasbourg(df)
    print(f"[offer] {len(df):,} points -> {OUT_FILE} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
