"""
Chargement, agrégation et mise en forme des données pour l'application Streamlit (app.py).

Principes :
    - jamais 2,3 M points dans le navigateur : vue nationale agrégée sur une grille de
      quelques km, vue « territoire » au carreau 200 m filtrée sur la zone ;
    - confidentialité : aucun agrégat de moins de C.PRIVACY_MIN_HOUSEHOLDS ménages n'est
      affiché. Au carreau 200 m, un carreau sous le seuil prend la valeur moyenne de son
      carré de 1 km (lissage) ; si le carré lui-même est sous le seuil, il est masqué ;
    - dégradation propre : si outputs/cells_access.parquet (ou stations_served.parquet)
      n'existe pas encore, l'accessibilité de la ZONE est recalculée à la volée avec la même
      définition (points d'offre à ≤ geo.walk_radius_m()), le score étant alors un rang
      percentile propre à la zone (signalé comme provisoire dans l'interface).
Toutes les fonctions lourdes sont mises en cache (st.cache_data).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

MODES = list(C.MODES)
F_CELLS = C.INTERIM / "cells.parquet"
F_OFFER = C.INTERIM / "offer.parquet"
F_ACCESS = C.OUT / "cells_access.parquet"
F_STATIONS = C.OUT / "stations_served.parquet"
F_COMMUNE = C.OUT / "commune_access.parquet"
F_SUMMARY = C.OUT / "access_summary.json"
F_CALIB = C.OUT / "walk_calibration.json"
F_METRICS = C.OUT / "model_metrics.json"
F_RECO = C.OUT / "recommendations.csv"
F_RECO_SUM = C.OUT / "recommendations_summary.json"

CELL_COLS = ["key", "crs_id", "x", "y", "lon", "lat", "com", "dep", "ind", "men",
             "income_pc", "poverty_rate", "carfree_share"]
PRIV = C.PRIVACY_MIN_HOUSEHOLDS

# Couleurs des modes (palette catégorielle validée, ordre fixe) – RGB
MODE_COLOR = {
    "transit": (42, 120, 214),     # bleu
    "rail": (98, 80, 214),         # violet
    "bike": (27, 175, 122),        # aqua
    "scooter": (237, 161, 0),      # jaune
    "carsharing": (232, 123, 164),  # magenta
    "citiz": (235, 104, 52),       # orange (Citiz mis en avant)
}
KIND_COLOR = {"citiz": (235, 104, 52), "bike": (27, 175, 122), "bus": (42, 120, 214)}
KIND_LABEL = {"citiz": "Station Citiz", "bike": "Station vélo", "bus": "Arrêt de bus"}

# Rampe froid -> chaud (ColorBrewer RdYlBu inversée, lisible par les daltoniens)
RAMP = np.array([(49, 54, 149), (69, 117, 180), (116, 173, 209), (171, 217, 233),
                 (254, 224, 144), (253, 174, 97), (244, 109, 67), (215, 48, 39), (165, 0, 38)], float)
ZERO_COLOR = (120, 130, 150)       # aucune option à 5 min : gris-bleu neutre

LEVELS = [(0, "Offre à développer (aucune option à 5 min)"), (25, "Offre limitée"),
          (50, "Offre intermédiaire"), (75, "Bonne offre"), (101, "Offre très dense")]

DEP_NAMES = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme",
    "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire",
    "38": "Isère", "39": "Jura", "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne", "53": "Mayenne",
    "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône",
    "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse", "85": "Vendée",
    "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "972": "Martinique", "974": "La Réunion",
}

# Zones prédéfinies : clé -> (libellé, filtre)
ZONES = {
    "ems": "Eurométropole de Strasbourg (étude de cas)",
    "fr": "France métropolitaine (vue nationale agrégée)",
    "972": "Martinique (DROM)",
    "974": "La Réunion (DROM)",
}


# --------------------------------------------------------------------------- utilitaires
def exists(path):
    return Path(path).exists()


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def versions():
    """Signature des fichiers de sortie : invalide les caches quand un module les régénère."""
    models = [C.OUT / f"model_{k}.joblib" for k in C.MODEL_KINDS]
    return tuple(mtime(f) for f in [F_CELLS, F_OFFER, F_ACCESS, F_STATIONS, F_METRICS] + models)


def mtime(path):
    p = Path(path)
    return int(p.stat().st_mtime) if p.exists() else 0


def score_rgb(score):
    """score 0-100 -> tableau (n, 3) uint8 sur la rampe froid -> chaud ; 0 = gris neutre."""
    s = np.clip(np.asarray(score, float), 0, 100) / 100 * (len(RAMP) - 1)
    i = np.clip(np.floor(s).astype(int), 0, len(RAMP) - 2)
    t = (s - i)[:, None]
    rgb = RAMP[i] * (1 - t) + RAMP[i + 1] * t
    rgb[np.asarray(score, float) <= 0] = ZERO_COLOR
    rgb[~np.isfinite(np.asarray(score, float))] = ZERO_COLOR
    return rgb.round().astype(np.uint8)


def level_label(score):
    s = np.asarray(score, float)
    out = np.full(len(s), LEVELS[-1][1], dtype=object)
    out[s < 75] = LEVELS[3][1]
    out[s < 50] = LEVELS[2][1]
    out[s < 25] = LEVELS[1][1]
    out[s <= 0] = LEVELS[0][1]
    return out


def ramp_css():
    stops = ", ".join(f"rgb({r:.0f},{g:.0f},{b:.0f}) {100 * k / (len(RAMP) - 1):.0f}%"
                      for k, (r, g, b) in enumerate(RAMP))
    return f"linear-gradient(to right, {stops})"


def fmt_int(v):
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except Exception:
        return "–"


# --------------------------------------------------------------------------- référentiels
@st.cache_data(show_spinner=False)
def commune_names():
    js = read_json(C.RAW / "communes.json") or []
    return {c["code"]: c["nom"] for c in js}


@st.cache_data(show_spinner=False)
def dep_index(v=None):
    """Départements présents : code, libellé, population, nb de carreaux."""
    d = pd.read_parquet(F_CELLS, columns=["dep", "ind"])
    g = d.groupby("dep")["ind"].agg(["sum", "size"]).reset_index()
    g.columns = ["dep", "pop", "n_cells"]
    g["label"] = g["dep"] + " – " + g["dep"].map(DEP_NAMES).fillna("")
    return g.sort_values("dep").reset_index(drop=True)


def zone_label(zone):
    if zone in ZONES:
        return ZONES[zone]
    return f"{zone} – {DEP_NAMES.get(zone, '')}"


def zone_filters(zone):
    """Filtres pyarrow (lecture parquet) d'une zone."""
    if zone == "ems":
        w, s, e, n = C.STRASBOURG_BBOX
        return [("dep", "==", C.STRASBOURG_DEPT), ("lon", ">=", w), ("lon", "<=", e),
                ("lat", ">=", s), ("lat", "<=", n)]
    if zone == "fr":
        return [("crs_id", "==", 0)]
    return [("dep", "==", zone)]


def reco_area(zone):
    """Paramètre `area` de src.recommend.recommend() ; None si zone trop grande."""
    if zone == "ems":
        return "ems"
    if zone == "fr":
        return None
    return zone


# --------------------------------------------------------------------------- accessibilité par carreau
def access_columns():
    if not exists(F_ACCESS):
        return []
    return pq.ParquetFile(F_ACCESS).schema_arrow.names


@st.cache_data(show_spinner=False)
def load_offer(v=None):
    return pd.read_parquet(F_OFFER, columns=["offer_id", "mode", "name", "lon", "lat", "crs_id", "x", "y",
                                             "operator", "capacity"])


def _fallback_access(cells, offer):
    """Accessibilité de la zone recalculée (même définition que src/accessibility, score zonal)."""
    r = geo.walk_radius_m()
    w, s, e, n = cells["lon"].min(), cells["lat"].min(), cells["lon"].max(), cells["lat"].max()
    o = offer[(offer["lon"] >= w - .02) & (offer["lon"] <= e + .02) & (offer["lat"] >= s - .02)
              & (offer["lat"] <= n + .02) & (offer["crs_id"] >= 0)].reset_index(drop=True)
    cc, cx, cy = cells["crs_id"].values, cells["x"].values, cells["y"].values
    I, J = geo.pairs_within(cc, cx, cy, o["crs_id"].values, o["x"].values, o["y"].values, r)
    out = cells.copy()
    mode_j = o["mode"].values[J]
    n_opt = np.zeros(len(cells))
    n_modes = np.zeros(len(cells))
    for m in MODES:
        k = np.bincount(I[mode_j == m], minlength=len(cells)).astype(float)
        out[f"n_{m}"] = k
        out[f"served_{m}"] = k > 0
        n_opt += k * C.MODE_WEIGHT[m]
        n_modes += k > 0
    out["n_options"] = n_opt
    out["n_modes"] = n_modes
    I2, J2 = geo.pairs_within(cc, cx, cy, cc, cx, cy, r)
    ind = cells["ind"].fillna(0).values
    out["pop_catchment"] = np.bincount(I2, weights=ind[J2], minlength=len(cells))
    out["options_per_1000"] = 1000 * n_opt / np.maximum(out["pop_catchment"].values, 1)
    sc = np.zeros(len(cells))
    srv = n_opt > 0
    if srv.any():
        v = out["options_per_1000"].values[srv]
        o_ = np.argsort(v, kind="stable")
        cum = np.cumsum(ind[srv][o_]) / max(ind[srv].sum(), 1)
        rk = np.empty(len(v))
        rk[o_] = cum
        sc[srv] = C.SCORE_MIN_SERVED + (100 - C.SCORE_MIN_SERVED) * rk
    out["score"] = sc
    # population desservie par chaque point d'offre (pour l'onglet 2)
    men = cells["men"].fillna(0).values
    o["pop_served"] = np.bincount(J, weights=ind[I], minlength=len(o))
    o["households_served"] = np.bincount(J, weights=men[I], minlength=len(o))
    return out, o


@st.cache_data(show_spinner=False, max_entries=8)
def zone_cells(zone, v=None):
    """
    Carreaux d'une zone avec indicateurs d'accessibilité.
    Renvoie (DataFrame, provisoire: bool, offre de la zone avec pop_served ou None).
    """
    flt = zone_filters(zone)
    acols = access_columns()
    if acols and "score" in acols:
        want = [c for c in acols if c in CELL_COLS or c.startswith(("n_", "served_")) or c in
                ("pop_catchment", "options_per_1000", "score", "access_2sfca")]
        df = pd.read_parquet(F_ACCESS, columns=want, filters=flt)
        extra = [c for c in CELL_COLS if c not in df.columns]
        if extra and zone != "fr":   # vue nationale : colonnes socio inutiles (gain de temps)
            cells = pd.read_parquet(F_CELLS, columns=["key"] + extra, filters=flt)
            df = df.merge(cells, on="key", how="left")
        return df, False, None
    cells = pd.read_parquet(F_CELLS, columns=CELL_COLS, filters=flt)
    if zone == "fr":
        return cells, True, None    # pas de recalcul national à la volée
    df, o = _fallback_access(cells, load_offer())
    return df, True, o


# --------------------------------------------------------------------------- agrégation pour la carte
def _tip_cells(score, ind, n_opt, n_modes, com, smoothed):
    lab = level_label(score)
    tips = []
    for s, p, no, nm, c, sm, lb in zip(score, ind, n_opt, n_modes, com, smoothed, lab):
        if sm:
            tips.append(f"<b>{c}</b><br/>{lb}<br/>Score moyen du carré 1 km : {s:.0f}/100"
                        f"<br/><i>Valeur lissée (secret statistique &lt; {PRIV} ménages)</i>")
        else:
            tips.append(f"<b>{c}</b><br/>{lb}<br/>Score : {s:.0f}/100<br/>"
                        f"{no:.0f} option(s) à 5 min · {nm:.0f} mode(s)<br/>≈ {fmt_int(p)} habitants")
    return tips


def _wmean(df, keys, col, w="ind"):
    g = df.assign(_wx=df[col] * df[w]).groupby(keys)
    return g["_wx"].sum() / g[w].sum().replace(0, np.nan)


@st.cache_data(show_spinner=False, max_entries=16)
def map_cells(zone, size_m=200, v=None):
    """
    Données de la carte d'accessibilité (une ligne par carré affiché) :
    lon, lat, r, g, b, tip, + stats. size_m = 200 (carreaux, lissage confidentialité)
    ou agrégation sur une grille de size_m mètres. Renvoie (df, n_masked_pop, provisoire).
    """
    df, prov, _ = zone_cells(zone, v)
    if "score" not in df.columns:
        return None, 0.0, prov
    names = commune_names()
    df = df[df["ind"] > 0].copy()
    df["men"] = df["men"].fillna(0)
    df["no_opt"] = (df["score"] <= 0) * df["ind"]
    if "n_options" not in df.columns:
        df["n_options"] = np.nan
    if "n_modes" not in df.columns:
        df["n_modes"] = np.nan
    if size_m <= C.CELL:
        # lissage : carreaux < seuil -> valeur du carré 1 km
        bx = (df["x"] // 1000).astype(np.int64)
        by = (df["y"] // 1000).astype(np.int64)
        keys = [df["crs_id"], bx, by]
        bmen = df.groupby(keys)["men"].transform("sum")
        bscore = df.assign(_wx=df["score"] * df["ind"]).groupby(keys)["_wx"].transform("sum") \
            / df.groupby(keys)["ind"].transform("sum")
        small = (df["men"] < PRIV).values
        hide = small & (bmen < PRIV).values
        masked_pop = float(df["ind"].values[hide].sum())
        df["disp_score"] = np.where(small, bscore, df["score"])
        df = df[~hide]
        small = small[~hide]
        out = pd.DataFrame({
            "lon": df["lon"].round(5).values, "lat": df["lat"].round(5).values,
            "score": df["disp_score"].round(1).values,
            "tip": _tip_cells(df["disp_score"].values, df["ind"].values, df["n_options"].values,
                              df["n_modes"].values, df["com"].map(names).fillna(df["com"]).values, small),
        })
        out["radius"] = C.CELL / 2 * np.sqrt(2)
    else:
        df = df.sort_values("ind", ascending=False)
        gx = (df["x"] // size_m).astype(np.int64)
        gy = (df["y"] // size_m).astype(np.int64)
        keys = [df["crs_id"].rename("crs"), gx.rename("gx"), gy.rename("gy")]
        g = df.groupby(keys).agg(ind=("ind", "sum"), men=("men", "sum"), no_opt=("no_opt", "sum"),
                                 com=("com", "first"))
        g["score"] = _wmean(df, keys, "score")
        g = g.reset_index()
        hide = g["men"] < PRIV
        masked_pop = float(g.loc[hide, "ind"].sum())
        g = g[~hide]
        lon, lat = geo.unproject((g["gx"].values + .5) * size_m, (g["gy"].values + .5) * size_m,
                                 g["crs"].values)
        share0 = g["no_opt"].values / g["ind"].values
        cname = g["com"].map(names).fillna(g["com"]).values
        lab = level_label(g["score"].values)
        out = pd.DataFrame({
            "lon": np.round(lon, 5), "lat": np.round(lat, 5), "score": g["score"].round(1).values,
            "tip": [f"<b>Secteur de {c}</b> (carré {size_m // 1000} km)<br/>{lb}<br/>Score moyen : {s:.0f}/100"
                    f"<br/>{fmt_int(p)} habitants · {100 * z:.0f} % sans option à 5 min"
                    for c, lb, s, p, z in zip(cname, lab, g["score"].values, g["ind"].values, share0)],
        })
        out["radius"] = size_m / 2 * np.sqrt(2)
    rgb = score_rgb(out["score"].values)
    out["r"], out["g"], out["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    return out, masked_pop, prov


# --------------------------------------------------------------------------- KPIs & équité
@st.cache_data(show_spinner=False, max_entries=16)
def zone_kpis(zone, v=None):
    df, prov, _ = zone_cells(zone, v)
    if "score" not in df.columns:
        return None
    ind = df["ind"].fillna(0).values
    tot = ind.sum()
    res = {"population": tot, "cells": len(df), "provisoire": prov,
           "pop_no_option": float(ind[(df["score"] <= 0).values].sum()),
           "mean_score": float(np.average(df["score"], weights=np.maximum(ind, 1e-9))),
           "by_mode": {}}
    for m in MODES:
        col = f"served_{m}" if f"served_{m}" in df.columns else f"n_{m}"
        if col in df.columns:
            srv = df[col].astype(float).values > 0
            res["by_mode"][m] = float(ind[srv].sum())
    return res


@st.cache_data(show_spinner=False, max_entries=16)
def equity_deciles(zone, v=None):
    """Accès par décile de revenu par habitant (pondéré population, déciles de la zone)."""
    df, _, _ = zone_cells(zone, v)
    if "score" not in df.columns:
        return None
    d = df[np.isfinite(df["income_pc"]) & (df["ind"] > 0)].copy()
    if len(d) < 50:
        return None
    d = d.sort_values("income_pc")
    cum = d["ind"].cumsum() / d["ind"].sum()
    d["decile"] = np.minimum((cum.values * 10 - 1e-9).astype(int) + 1, 10)
    d["no_opt"] = (d["score"] <= 0) * d["ind"]
    g = d.groupby("decile").agg(pop=("ind", "sum"), men=("men", "sum"), no_opt=("no_opt", "sum"),
                                rev_min=("income_pc", "min"), rev_max=("income_pc", "max"))
    g["score_moyen"] = _wmean(d, "decile", "score")
    g["part_sans_option"] = 100 * g["no_opt"] / g["pop"]
    g = g[g["men"] >= PRIV].reset_index()
    g["Décile"] = "D" + g["decile"].astype(str)
    return g


# --------------------------------------------------------------------------- points d'offre
@st.cache_data(show_spinner=False, max_entries=16)
def zone_stations(zone, v=None):
    """Points d'offre de la zone avec population desservie. Renvoie (df, source)."""
    if zone == "fr":
        return None, None
    df, _, o = zone_cells(zone, v)
    w, s, e, n = df["lon"].min(), df["lat"].min(), df["lon"].max(), df["lat"].max()
    if exists(F_STATIONS):
        st_ = pd.read_parquet(F_STATIONS, filters=[("lon", ">=", w), ("lon", "<=", e),
                                                   ("lat", ">=", s), ("lat", "<=", n)])
        src = "stations_served.parquet"
    elif o is not None:
        st_ = o[(o["lon"] >= w) & (o["lon"] <= e) & (o["lat"] >= s) & (o["lat"] <= n)].copy()
        src = "calcul provisoire (zone)"
    else:
        _, o = _fallback_access(df, load_offer())
        st_ = o[(o["lon"] >= w) & (o["lon"] <= e) & (o["lat"] >= s) & (o["lat"] <= n)].copy()
        src = "calcul provisoire (zone)"
    if "pop_served" not in st_.columns:
        st_["pop_served"] = np.nan
    st_ = st_[st_["mode"].isin(MODES)].copy()
    st_["mode_label"] = st_["mode"].map(C.MODES)
    rgb = np.array([MODE_COLOR[m] for m in st_["mode"]], dtype=np.uint8).reshape(-1, 3)
    st_["r"], st_["g"], st_["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    ps = st_["pop_served"].fillna(0).values
    st_["radius"] = 12 + 1.6 * np.sqrt(ps)
    st_["pop_txt"] = [fmt_int(round(p, -1)) if p >= 0 else "–" for p in ps]
    st_["name"] = st_["name"].fillna("").astype(str)
    st_["operator"] = st_["operator"].fillna("").astype(str) if "operator" in st_.columns else ""
    return st_.reset_index(drop=True), src


# --------------------------------------------------------------------------- recommandations
def model_ready(kinds=C.MODEL_KINDS):
    return all(exists(C.OUT / f"model_{k}.joblib") for k in kinds)


@st.cache_resource(show_spinner=False)
def _recommend_module():
    from src import recommend as rec
    return rec


@st.cache_data(show_spinner=False, max_entries=32)
def run_recommend(area, budget, equity_lambda, kinds, v=None):
    rec = _recommend_module()
    df, summary = rec.recommend(area=area, budget=float(budget), equity_lambda=float(equity_lambda),
                                kinds=tuple(kinds), compare=True, write=False)
    return df, json.loads(json.dumps(summary, default=float))


@st.cache_data(show_spinner=False, max_entries=32)
def newly_served_cells(area, sites):
    """
    Carreaux nouvellement desservis par les sites retenus (tuple de (kind, lon, lat)) :
    carreaux de la zone à ≤ rayon de marche, non déjà desservis par ce type.
    """
    rec = _recommend_module()
    ctx = rec.prepare(area)
    cells, F = ctx["cells"], ctx["F"]
    if not sites:
        return pd.DataFrame(columns=["lon", "lat", "kind", "r", "g", "b"])
    kinds = np.array([s[0] for s in sites])
    lon = np.array([s[1] for s in sites], float)
    lat = np.array([s[2] for s in sites], float)
    crs, x, y = geo.project(lon, lat)
    I, J = geo.pairs_within(crs, x, y, cells["crs_id"].values, cells["x"].values, cells["y"].values,
                            geo.walk_radius_m())
    rows = []
    for k in np.unique(kinds):
        served = rec.served_mask(F, k)
        sel = np.unique(J[kinds[I] == k])
        sel = sel[~served[sel]]
        rows.append(pd.DataFrame({"lon": cells["lon"].values[sel], "lat": cells["lat"].values[sel],
                                  "kind": k}))
    out = pd.concat(rows, ignore_index=True).drop_duplicates(["lon", "lat"])
    rgb = np.array([KIND_COLOR[k] for k in out["kind"]], dtype=np.uint8).reshape(-1, 3)
    out["r"], out["g"], out["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    out["radius"] = C.CELL / 2 * np.sqrt(2)
    out["tip"] = "Carreau nouvellement desservi (" + out["kind"].map(KIND_LABEL) + ")"
    return out
