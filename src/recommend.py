"""
Étape 6 – Orchestration : liste priorisée de nouveaux sites (Citiz, station vélo, arrêt de
bus) sous contrainte de budget, en tenant compte de l'offre existante.

Deux financeurs distincts (recommend_by_funder) : Citiz, qui n'exploite que des stations
d'autopartage (budget C.CITIZ_BUDGET), et la collectivité / AOM, qui finance stations vélo et
arrêts de bus (budget C.PUBLIC_BUDGET). Zone par défaut : le territoire prioritaire choisi par
src/territories.py (outputs/territories_summary.json) ; l'Eurométropole de Strasbourg, où Citiz
est déjà implanté, sert de territoire témoin.

Chaîne :
    1. zone (une intercommunalité « epci:<siren> », l'Eurométropole « ems » = ses 33 communes,
       C.EMS_COMMUNES, ou un département) : carreaux habités + marge de 4 km pour les variables de bassin ;
       variables model.build_features() (mises en cache disque par zone) et propensions
       model.predict_value() par type ;
    2. couverture fine : chaque carreau est représenté par C.COVER_SUBSAMPLE² points (population
       répartie uniformément) ; un point est « déjà desservi » par le type t s'il est à
       ≤ geo.walk_radius_m() d'un point d'offre existant de t (bus : transit/rail ; vélo : bike ;
       Citiz : citiz/carsharing). Cela évite l'artefact de grille (un site couvrant exactement
       5 ou 9 carreaux selon que le rayon est sous ou au-dessus de la diagonale de 282,8 m) ;
    3. candidats = centres des carreaux habités de la zone × type, dont moins de la moitié de la
       surface est déjà desservie par ce type ; bus : uniquement à ≤ C.BUS_DETOUR["max_dist_m"]
       d'un arrêt existant ;
    4. poids d'un point  w = pop_horizon_carreau / S² × (1 + C.EQUITY_SCALE·λ·besoin_carreau),
       mis à 0 pour le type t si le point est déjà desservi par t. Les types ont chacun leur
       copie des points : un arrêt de bus ne rend pas une station Citiz inutile ;
       besoin ∈ [0,1] = Σ poids × rang-percentile (dans la zone) de : taux de pauvreté,
       part de ménages sans voiture, faiblesse de l'accessibilité actuelle (`score` de
       outputs/cells_access.parquet s'il existe) — cf. C.NEED_WEIGHTS. Rangs relatifs à la zone ;
    5. valeur du site v_j = clip(p_j / p_ref, C.VALUE_CLIP) ** C.MODEL_VALUE_EXPONENT ×
       C.KIND_BENEFIT[t] ; candidats écartés si clip(p/p_ref) < C.MODEL_VALUE_MIN ;
    6. coût = C.facility_cost(t, extra) ; bus : extra = exploitation du détour
       2·d/1000 km × passages/jour × 365 × €/km, d = distance à l'arrêt existant le plus proche ;
    7. optimize.optimize() (glouton budgété, garantie (1-1/e)/2) maximise Σ_i w_i·max_j v_j
       (chaque point compte une fois, avec la valeur du meilleur site qui le couvre).

Indicateurs (evaluate / _totals) : population nouvellement desservie par type (somme des types :
un habitant gagnant vélo ET Citiz compte deux fois), personnes DISTINCTES gagnant au moins un
type, personnes passant de 0 option à ≥ 1, CO2 évité, part des nouveaux desservis dans les
3 premiers déciles de revenu de la zone et en zone peu dense.

Comparaisons (résumé json, même budget) : sans pondération d'équité (λ = 0), sans modèle (v = 1,
offre existante prise en compte : la baseline honnête), offre existante ignorée, sans quota,
sans enveloppes, et naïve « population seule ».

Confidentialité : les parts (pauvreté, sans voiture) ne sont publiées que si la zone servie
compte au moins C.PRIVACY_MIN_HOUSEHOLDS ménages.

Enveloppes : au sein d'un même budget, réparti par type (C.BUDGET_SPLIT), le reliquat étant
réalloué globalement ; --no-split laisse l'optimiseur arbitrer seul.

Usage : python -m src.recommend [--area ems | --area epci:<siren> | --dep 54]
        [--citiz-budget 1000000] [--public-budget 1000000] [--lambda 0.5] [--no-split]
"""
import argparse
import inspect
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo, model  # noqa: E402
from src.optimize import optimize  # noqa: E402

BUFFER_DEG = (0.055, 0.037)   # marge lon/lat ≈ 4 km (fenêtre de contexte 3 km + rayon)
AREA_COLS = model.CELL_COLS + ["men_pauv"]
KIND_LABEL = {k: C.COSTS[k]["label"] for k in C.COSTS}
_CTX = {}

STRATEGY_LABELS = {
    "selected": "Recommandée (modèle, λ, enveloppes, quota peu dense)",
    "lambda_0": "Sans pondération d'équité (λ = 0) – maximise Σ pop·v, pas la population",
    "no_model_value_1": "Offre existante prise en compte, sans modèle (v = 1) – baseline honnête",
    "ignore_existing_offer": "Modèle, mais offre existante ignorée",
    "no_low_density_quota": "Sans quota peu dense",
    "global_pool_no_split_no_quota": "Sans enveloppes ni quota",
    "naive_population_only": "Naïve : population seule (sans modèle, sans offre existante, λ = 0)",
    "no_frequency": "Sans la fréquence des lignes (arrêts comptés comme dans la méthode nationale)",
}
FREQ_COLS = ("freq_nearest", "tc_freq_options", "n_options_freq")
EQUITY_LAMBDAS = C.EQUITY_LAMBDAS


def _without_frequency(ctx):
    """Copie du contexte sans les colonnes de src/frequency.py (variante « arrêts comptés »)."""
    return dict(ctx, F=ctx["F"].drop(columns=[c for c in FREQ_COLS if c in ctx["F"]]))


# --------------------------------------------------------------------------- préparation de la zone
def _area_bounds(area):
    """
    area : 'ems' (les 33 communes de l'Eurométropole, C.EMS_COMMUNES), 'epci:<siren>'
    (intercommunalité), code département ('54', '2A'…) ou bbox (o, s, e, n).
    Renvoie (nom, emprise lon/lat, dép., codes communes|None).
    """
    if area in (None, "ems", "strasbourg") or str(area).startswith("epci:"):
        if str(area).startswith("epci:"):
            from src import territories
            code = str(area).split(":", 1)[1]
            name, dep, coms = f"epci{code}", None, territories.epci_communes(code)
        else:
            name, dep, coms = "ems", C.STRASBOURG_DEPT, tuple(C.EMS_COMMUNES)
        d = pd.read_parquet(C.INTERIM / "cells.parquet", columns=["lon", "lat"],
                            filters=[("com", "in", list(coms))])
        return name, (d["lon"].min(), d["lat"].min(), d["lon"].max(), d["lat"].max()), dep, coms
    if isinstance(area, (tuple, list)):
        return "bbox_" + "_".join(f"{v:.3f}" for v in area), tuple(area), None, None
    dep = str(area).zfill(2)
    d = pd.read_parquet(C.INTERIM / "cells.parquet", columns=["lon", "lat"], filters=[("dep", "==", dep)])
    if len(d) == 0:
        raise ValueError(f"aucun carreau pour le département {dep}")
    return f"dep{dep}", (d["lon"].min(), d["lat"].min(), d["lon"].max(), d["lat"].max()), dep, None


def _bike_ref_pop():
    """Population médiane à 5 min des stations vélo existantes (France), repli C.BIKE_REF_POP."""
    try:
        s = pd.read_parquet(C.OUT / "stations_served.parquet", columns=["mode", "pop_served"],
                            filters=[("mode", "==", "bike")])
        v = float(s["pop_served"].median())
        return v if np.isfinite(v) and v > 0 else float(C.BIKE_REF_POP)
    except Exception:
        return float(C.BIKE_REF_POP)


def _predict(F, kind, dep):
    """
    Propension du modèle et p_ref cohérent. Hors pli (le modèle n'a pas vu le département
    de la zone : ses carreaux non desservis ne sont pas des négatifs d'apprentissage) si
    model.predict_value le propose (oof=True, dep=…) ; sinon in-sample.
    """
    b = model.load_bundle(kind)
    if "oof" in inspect.signature(model.predict_value).parameters and "p_ref_insample" in b:
        return model.predict_value(F, kind, oof=True, dep=dep), b["p_ref"], "oof"
    return model.predict_value(F, kind), b.get("p_ref_insample", b["p_ref"]), "in_sample"


PLM_CITY = {"751": ("Paris", 75100), "132": ("Marseille", 13200), "6938": ("Lyon", 69380)}


def plm_label(code):
    """« Lyon 8e », « Paris 1er »… pour un code d'arrondissement municipal, sinon None."""
    code = str(code)
    for prefix, (city, base) in PLM_CITY.items():
        if code.startswith(prefix) and code.isdigit() and 1 <= int(code) - base <= 20:
            n = int(code) - base
            return f"{city} {n}{'er' if n == 1 else 'e'}"
    return None


def _subpoints(cells, F=None, offer=None):
    """
    Points de sous-échantillonnage (S² par carreau) et masques « déjà desservi » par type.
    offer fourni : distance réelle point -> offre existante ; sinon repli sur le statut du carreau (F).
    """
    # échantillonnage stratifié : 1 point tiré uniformément dans chacune des S×S sous-mailles,
    # tirage différent par carreau (graine fixe) -> les distances site-point ne sont plus
    # quantifiées par la grille et la couverture varie continûment avec le rayon
    S = int(C.COVER_SUBSAMPLE)
    n = len(cells)
    gx, gy = [a.ravel() for a in np.meshgrid(np.arange(S), np.arange(S))]
    rng = np.random.default_rng(C.RANDOM_STATE)
    ux, uy = rng.random((n, S * S)), rng.random((n, S * S))
    ox = ((gx[None, :] + ux) / S - 0.5) * C.CELL
    oy = ((gy[None, :] + uy) / S - 0.5) * C.CELL
    cell = np.repeat(np.arange(n), S * S)
    x = (cells["x"].values[:, None] + ox).ravel()
    y = (cells["y"].values[:, None] + oy).ravel()
    crs = np.repeat(cells["crs_id"].values, S * S)
    served, r = {}, geo.walk_radius_m()

    def near(mask_offer):
        o = offer[mask_offer]
        m = np.zeros(len(x), bool)
        if len(o):
            I, _ = geo.pairs_within(crs, x, y, o["crs_id"].values, o["x"].values, o["y"].values, r)
            m[I] = True
        return m

    for k in C.MODEL_KINDS:
        if offer is not None:
            served[k] = near(offer["mode"].isin(C.KIND_TARGET_MODES[k]).values)
        else:
            served[k] = served_mask(F, k)[cell]
    if offer is not None:
        any_opt = near(offer["mode"].isin(list(C.MODES)).values)
    else:
        any_opt = (F["n_options_r5"].values > 0)[cell] if "n_options_r5" in F else np.zeros(len(x), bool)
    return {"S2": S * S, "cell": cell, "x": x, "y": y, "crs": crs, "served": served, "any": any_opt}


def _sub(ctx):
    if "sub" not in ctx:
        ctx["sub"] = _subpoints(ctx["cells"], ctx["F"])
    return ctx["sub"]


def prepare(area="ems", force=False):
    """Carreaux, variables et propensions de la zone (mémoire + cache disque)."""
    name, (w, s, e, n), dep, coms = _area_bounds(area)
    if name in _CTX and not force:
        return _CTX[name]
    t0 = time.time()
    bx, by = BUFFER_DEG
    cells = model.load_cells(AREA_COLS, filters=[("lon", ">=", w - bx), ("lon", "<=", e + bx),
                                                  ("lat", ">=", s - by), ("lat", "<=", n + by)])
    cells = cells.reset_index(drop=True)
    in_area = ((cells["lon"] >= w) & (cells["lon"] <= e) & (cells["lat"] >= s) & (cells["lat"] <= n)).values
    if dep is not None:
        in_area &= (cells["dep"] == dep).values
    if coms is not None:
        in_area &= cells["com"].isin(coms).values
    offer, src = model.load_offer()
    ob = offer[(offer["lon"] >= w - 4 * bx) & (offer["lon"] <= e + 4 * bx)
               & (offer["lat"] >= s - 4 * by) & (offer["lat"] <= n + 4 * by)]
    cache = model.CACHE / f"area_{name}.parquet"
    meta = model.CACHE / f"area_{name}.json"
    if cache.exists() and meta.exists() and not force \
            and json.loads(meta.read_text(encoding="utf-8")) == {"offer_source": src, "n": len(cells),
                                              "radius": geo.walk_radius_m()}:
        F = pd.read_parquet(cache)
    else:
        F = model.build_features(cells, ob)
        F.to_parquet(cache, index=False)
        meta.write_text(json.dumps({"offer_source": src, "n": len(cells), "radius": geo.walk_radius_m()}), encoding="utf-8")
    keep = np.flatnonzero(in_area)
    cells, F = cells.iloc[keep].reset_index(drop=True), F.iloc[keep].reset_index(drop=True)
    # score d'accessibilité 0-100 de l'étape 4 (si disponible) pour le volet « besoin »
    fa = C.OUT / "cells_access.parquet"
    if fa.exists():
        acc = pd.read_parquet(fa, columns=["key", "score"], filters=[("lon", ">=", w), ("lon", "<=", e),
                                                                  ("lat", ">=", s), ("lat", "<=", n)])
        F["access_score"] = cells["key"].map(acc.set_index("key")["score"]).values
    # fréquence des lignes (src/frequency.py), si les GTFS de la zone ont été lus
    freq_summary = None
    ff = C.OUT / f"frequency_cells_{name}.parquet"
    if ff.exists():
        fq = pd.read_parquet(ff).set_index("key")
        for col in ("freq_nearest", "tc_freq_options", "n_options_freq"):
            if col in fq:
                F[col] = cells["key"].map(fq[col]).values
        fs = C.OUT / f"frequency_{name}.json"
        freq_summary = json.loads(fs.read_text(encoding="utf-8")) if fs.exists() else None
    pred, p_ref, extra, pred_kind = {}, {}, {}, set()
    for k in C.MODEL_KINDS:
        pred[k], p_ref[k], how = _predict(F, k, cells["dep"].values)
        pred_kind.add(how)
        b = model.load_bundle(k)
        if "penetration" in b:
            extra["penetration"] = b["penetration"]
    names = model.load_communes()["com_name"]
    for code in cells["com"].unique():          # arrondissements PLM absents de geo.api.gouv.fr
        if code not in names.index:
            lab = plm_label(code)
            if lab:
                names.loc[code] = lab
    ctx = {"name": name, "cells": cells, "F": F, "pred": pred, "p_ref": p_ref,
           "pred_source": "+".join(sorted(pred_kind)),
           "com_name": cells["com"].map(names).fillna(cells["com"]).values,
           "offer_source": src, "penetration": extra.get("penetration", 0.002), "frequency": freq_summary,
           "bike_ref_pop": _bike_ref_pop(),
           "sub": _subpoints(cells, F, ob[ob["crs_id"] >= 0]),
           "prep_s": time.time() - t0}
    _CTX[name] = ctx
    return ctx


# --------------------------------------------------------------------------- briques
def served_mask(F, kind):
    """Carreau déjà desservi (≥ 1 point d'un mode cible du type à 5 min du centre)."""
    return (sum(F[f"n_{m}_r5"].values for m in C.KIND_TARGET_MODES[kind]) > 0)


def _rank(v):
    return pd.Series(v).rank(pct=True, method="average").fillna(0.5).values


def need_index(cells, F):
    """Besoin ∈ [0,1] : rangs-percentiles pondérés (pauvreté, sans voiture, faible accessibilité).
    Faible accessibilité : options pondérées par la fréquence (src/frequency.py) si la zone a ses
    GTFS, sinon score de l'étape 4, sinon nombre d'options."""
    wts = C.NEED_WEIGHTS
    if "n_options_freq" in F and F["n_options_freq"].notna().any():
        access = F["n_options_freq"].fillna(0).values
    elif "access_score" in F:
        access = F["access_score"].fillna(0).values
    else:
        access = F["n_options_r5"].values
    parts = {"poverty_rate": _rank(cells["poverty_rate"].values),
             "carfree_share": _rank(cells["carfree_share"].values),
             "low_access": _rank(-access)}
    return sum(wts[k] * parts[k] for k in wts) / sum(wts.values())


def pop_at(cells, horizon):
    """Population à l'horizon : interpolation linéaire du facteur Omphale 2021 -> GROWTH_HORIZON."""
    t = (horizon - 2021) / (C.GROWTH_HORIZON - 2021)
    return cells["ind"].values * (1 + (cells["growth"].fillna(1).values - 1) * t)


def bus_extra_annual(d):
    """Surcoût annuel d'exploitation du détour (aller-retour 2·d) pour un arrêt à d m de la ligne."""
    b = C.BUS_DETOUR
    return 2 * d / 1000 * b["trips_per_day"] * 365 * b["cost_per_km"]


def bus_service_factor(F, idx):
    """
    Multiplicateur de valeur d'un nouvel arrêt de bus : min(1, départs/h ÷ C.FULL_OPTION_DEP_H) de la
    meilleure ligne de l'arrêt existant le plus proche (le nouvel arrêt est posé sur cette ligne),
    borné en bas par C.FREQ_MIN_FACTOR. 1 si la zone n'a pas de GTFS lu (src/frequency.py).
    """
    if "freq_nearest" not in F:
        return np.ones(len(idx))
    f = F["freq_nearest"].values[idx].astype(float)
    q = np.clip(f / C.FULL_OPTION_DEP_H, C.FREQ_MIN_FACTOR, 1.0)
    return np.where(np.isfinite(q), q, 1.0)


def _coverage(ctx, cand_idx):
    """Liste (par candidat) des indices de sous-points à ≤ rayon de marche du centre du candidat."""
    cells, sub = ctx["cells"], _sub(ctx)
    cx, cy, cc = (cells[c].values for c in ("x", "y", "crs_id"))
    I, J = geo.pairs_within(cc[cand_idx], cx[cand_idx], cy[cand_idx], sub["crs"], sub["x"], sub["y"],
                            geo.walk_radius_m())
    order = np.argsort(I, kind="stable")
    I, J = I[order], J[order]
    bounds = np.searchsorted(I, np.arange(len(cand_idx) + 1))
    return [J[bounds[a]:bounds[a + 1]] for a in range(len(cand_idx))]


def site_value(ctx, kind, idx):
    """v_rel = clip(p/p_ref) (affichée) et v = v_rel ** exposant (objectif)."""
    v_rel = np.clip(ctx["pred"][kind][idx] / ctx["p_ref"][kind], *C.VALUE_CLIP)
    return v_rel, v_rel ** C.MODEL_VALUE_EXPONENT * C.KIND_BENEFIT[kind]


def solve(ctx, budget=C.DEFAULT_BUDGET, equity_lambda=C.EQUITY_LAMBDA, kinds=C.MODEL_KINDS,
          horizon=C.GROWTH_HORIZON, naive=False, max_sites=None, cand_filter=None,
          use_model=True, use_existing=True):
    """
    Sélection gloutonne budgétée (cand_filter : masque booléen des carreaux candidats admis).
    use_model=False : v = 1 pour tous les candidats (population seule, sans modèle) ;
    use_existing=False : offre existante ignorée dans le choix (candidats et poids).
    naive=True : stratégie « population seule » = les deux à False et λ = 0.
    Renvoie le DataFrame des sites choisis (ordonnés) ; `covered` = indices de sous-points.
    """
    if naive:
        use_model, use_existing = False, False
    cells, F, sub = ctx["cells"], ctx["F"], _sub(ctx)
    m, S2 = len(sub["cell"]), sub["S2"]
    pop_h = pop_at(cells, horizon)
    lam = 0.0 if naive else equity_lambda
    w_cell = pop_h * (1 + C.EQUITY_SCALE * lam * need_index(cells, F)) / S2
    w_sub = w_cell[sub["cell"]]
    hab = np.flatnonzero(cells["ind"].values > 0)
    d_bus = F["d_transit"].values.astype(float)

    cand_cells, val, cost, meta, W = [], [], [], [], []
    for t, kind in enumerate(kinds):
        served = sub["served"][kind]
        W.append(np.where(served, 0.0, w_sub) if use_existing else w_sub)
        idx = hab
        if use_existing:   # candidat : moins de la moitié du carreau déjà desservie par ce type
            frac = np.bincount(sub["cell"], weights=served, minlength=len(cells)) / S2
            idx = hab[frac[hab] < 0.5]
        if cand_filter is not None:
            idx = idx[cand_filter[idx]]
        v_rel, v = site_value(ctx, kind, idx)
        if use_model and C.MODEL_VALUE_MIN > 0:
            ok = v_rel >= C.MODEL_VALUE_MIN
            idx, v_rel, v = idx[ok], v_rel[ok], v[ok]
        if not use_model:
            v = np.full(len(idx), float(C.KIND_BENEFIT[kind]))
        ext = np.zeros(len(idx))
        if kind == "bus":
            ok = d_bus[idx] <= C.BUS_DETOUR["max_dist_m"]
            idx, v_rel, v = idx[ok], v_rel[ok], v[ok]
            ext = bus_extra_annual(d_bus[idx])
            if use_existing:   # qualité de service de la ligne rattachée (fréquence GTFS de la zone)
                q = bus_service_factor(F, idx)
                v, v_rel = v * q, v_rel * q
        if len(idx) == 0:
            continue
        cov = _coverage(ctx, idx)
        cand_cells += [c + t * m for c in cov]
        val.append(v)
        cost.append(np.array([C.facility_cost(kind, e) for e in ext]))
        meta.append(pd.DataFrame({"kind": kind, "cell": idx, "p": ctx["pred"][kind][idx],
                                  "v_rel": v_rel, "extra_annual": ext}))
    if not cand_cells:
        return pd.DataFrame()
    val, cost, meta = np.concatenate(val), np.concatenate(cost), pd.concat(meta, ignore_index=True)
    meta["cost"] = cost
    chosen, gains, spent = optimize(cand_cells, val, cost, np.concatenate(W), budget, max_sites)
    out = meta.iloc[chosen].reset_index(drop=True)
    out["objective_gain"] = gains
    out["covered"] = [cand_cells[j] - kinds.index(k) * m for j, k in zip(chosen, out["kind"])]
    return out


def evaluate(ctx, picks, horizon=C.GROWTH_HORIZON):
    """Indicateurs RÉELS d'une sélection (population non déjà desservie, CO2, équité), site par site."""
    cells, F, sub = ctx["cells"], ctx["F"], _sub(ctx)
    if len(picks) == 0:
        return pd.DataFrame()
    S2, pc = sub["S2"], sub["cell"]
    pop_h = pop_at(cells, horizon)[pc] / S2
    ind, men = cells["ind"].values[pc] / S2, cells["men"].fillna(0).values[pc] / S2
    pauv = cells["men_pauv"].fillna(0).values[pc] / S2
    carfree_men = cells["carfree_share"].fillna(0).values[pc] * men
    inc_c, ind_c = cells["income_pc"].values, cells["ind"].values
    ok = np.isfinite(inc_c)
    # 3e décile de revenu (pondéré population) de la zone
    o = np.argsort(inc_c[ok])
    cum = np.cumsum(ind_c[ok][o]) / ind_c[ok].sum()
    d3 = inc_c[ok][o][min(np.searchsorted(cum, 0.3), ok.sum() - 1)]
    low_inc = (ok & (inc_c <= d3))[pc]
    low_dens = (F["dens_1k"].values < C.LOW_DENSITY_HAB_KM2)[pc]
    taken = {k: sub["served"][k].copy() for k in sub["served"]}
    gained_any = np.zeros(len(pc), bool)          # sous-points gagnant ≥ 1 type dans la sélection
    pen, per_car = ctx["penetration"], C.CITIZ_DRIVERS_FR / C.CITIZ_CARS_FR
    bike_ref = ctx.get("bike_ref_pop", C.BIKE_REF_POP)
    rows = []
    for _, s in picks.iterrows():
        k = s["kind"]
        cov = np.asarray(s["covered"], int)
        new = cov[~taken[k][cov]]
        taken[k][new] = True
        distinct = new[~gained_any[new]]
        gained_any[new] = True
        zero = distinct[~sub["any"][distinct]]
        pn, mn = ind[new].sum(), men[new].sum()
        v = min(s["v_rel"], C.USAGE_VALUE_CAP)                     # multiplicateur d'usage borné
        # usage prédit et CO2 évité (t/an), hypothèses de Config (impactco2 / ADEME)
        demand = np.nan
        if k == "citiz":
            demand = pn * pen * v                                  # adhérents potentiels (non bornés)
            usage = min(per_car, demand)                           # bornés par 1 véhicule
            unit = "adhérents"
            co2 = usage * C.CARSHARING_ACTIVE_SHARE * C.CARSHARING_CAR_KM_AVOIDED_PER_USER \
                * C.CO2_G_PER_KM["car"] / 1e6
        elif k == "bike":
            # fréquentation proportionnelle au bassin, plafonnée à celle d'une station typique
            usage = C.BIKE_TRIPS_PER_STATION_DAY * v * min(1.0, pn / bike_ref)
            unit = "trajets/jour"
            co2 = usage * 365 * C.BIKE_KM_PER_TRIP * C.BIKE_CAR_SHIFT \
                * (C.CO2_G_PER_KM["car"] - C.CO2_G_PER_KM["bike"]) / 1e6
        else:
            usage = pn * C.BUS_TRIPS_PER_RESIDENT_DAY * v           # montées / jour
            unit = "montées/jour"
            detour_vkm = 2 * F["d_transit"].values[s["cell"]] / 1000 * C.BUS_DETOUR["trips_per_day"]
            # ligne existante : émission marginale passager ~0, le détour est compté à part
            co2 = usage * 365 * C.BUS_KM_PER_TRIP * C.BUS_CAR_SHIFT \
                * (C.CO2_G_PER_KM["car"] - C.BUS_PASSENGER_MARGINAL_G_PER_KM) / 1e6 \
                - detour_vkm * 365 * C.BUS_KGCO2_PER_VKM / 1e3
        priv = mn >= C.PRIVACY_MIN_HOUSEHOLDS
        rows.append({
            "pop_new": pn, "pop_new_horizon": pop_h[new].sum(), "households_new": mn,
            "pop_new_distinct": ind[distinct].sum(), "pop_new_from_zero_option": ind[zero].sum(),
            "usage_pred": usage, "usage_unit": unit, "co2_avoided_t_yr": co2,
            "demand_potential": demand,
            "vehicles_suggested": max(1, int(np.ceil(demand / per_car))) if k == "citiz" else np.nan,
            "share_poor_households": pauv[new].sum() / mn if priv else np.nan,
            "share_carfree_households": carfree_men[new].sum() / mn if priv else np.nan,
            "pop_new_low_income": ind[new][low_inc[new]].sum(),
            "pop_new_low_density": ind[new][low_dens[new]].sum(),
        })
    return pd.DataFrame(rows)


def _assemble(ctx, picks, ev):
    cells, F = ctx["cells"], ctx["F"]
    i = picks["cell"].values
    df = pd.DataFrame({
        "rank": np.arange(1, len(picks) + 1), "type": picks["kind"].values,
        "equipement": picks["kind"].map(KIND_LABEL).values,
        "stage": picks["stage"].values if "stage" in picks else "",
        "lon": cells["lon"].values[i].round(5), "lat": cells["lat"].values[i].round(5),
        "commune": ctx["com_name"][i], "code_commune": cells["com"].values[i],
        "pop_newly_served": ev["pop_new"].round(0).values,
        f"pop_{C.GROWTH_HORIZON}": ev["pop_new_horizon"].round(0).values,
        "pop_new_distinct": ev["pop_new_distinct"].round(0).values,
        "pop_from_zero_option": ev["pop_new_from_zero_option"].round(0).values,
        "propensity": picks["p"].round(4).values, "value_rel": picks["v_rel"].round(3).values,
        "usage_pred": ev["usage_pred"].round(1).values, "usage_unit": ev["usage_unit"].values,
        "cost_eur": picks["cost"].round(0).values,
    })
    df["cost_cum_eur"] = df["cost_eur"].cumsum()
    df["eur_per_new_resident"] = (df["cost_eur"] / df["pop_newly_served"].replace(0, np.nan)).round(0)
    df["co2_avoided_t_yr"] = ev["co2_avoided_t_yr"].round(2).values
    df["share_poor_households"] = ev["share_poor_households"].round(3).values
    df["share_carfree_households"] = ev["share_carfree_households"].round(3).values
    # Citiz : adhérents potentiels non bornés et nb de véhicules qu'ils justifieraient
    # (information de dimensionnement ; le coût et le CO2 restent ceux d'1 véhicule)
    df["demand_potential"] = ev["demand_potential"].round(1).values
    df["vehicles_suggested"] = ev["vehicles_suggested"].values
    # distance du site au point existant le plus proche du même type (contrôle de cohérence)
    d_exist = np.full(len(df), np.nan)
    for k in df["type"].unique():
        msk = (df["type"] == k).values
        cols = [f"d_{t}" for t in C.KIND_TARGET_MODES[k] if f"d_{t}" in F]
        if cols:
            d_exist[msk] = F[cols].values[i[msk]].min(axis=1)
    df["dist_existing_same_type_m"] = np.round(d_exist, 0)
    return df


def _totals(ev, picks):
    if len(ev) == 0:
        return {"n_sites": 0}
    pn = ev["pop_new"].sum()
    return {
        "n_sites": int(len(picks)), "by_type": picks["kind"].value_counts().to_dict(),
        "cost_eur": float(picks["cost"].sum()),
        # somme sur les types (un habitant gagnant vélo ET Citiz compte deux fois)
        "pop_newly_served": float(pn),
        "pop_newly_served_by_type": {k: float(ev["pop_new"].values[(picks["kind"] == k).values].sum())
                                     for k in picks["kind"].unique()},
        # personnes distinctes gagnant au moins un type / passant de 0 option à >= 1
        "pop_newly_served_distinct": float(ev["pop_new_distinct"].sum()),
        "pop_from_zero_option": float(ev["pop_new_from_zero_option"].sum()),
        "pop_newly_served_horizon": float(ev["pop_new_horizon"].sum()),
        "eur_per_new_resident": float(picks["cost"].sum() / max(pn, 1)),
        "eur_per_new_distinct_resident": float(picks["cost"].sum() / max(ev["pop_new_distinct"].sum(), 1)),
        "co2_avoided_t_yr": float(ev["co2_avoided_t_yr"].sum()),
        "co2_by_type_t_yr": {k: float(ev["co2_avoided_t_yr"].values[(picks["kind"] == k).values].sum())
                             for k in picks["kind"].unique()},
        "share_new_in_income_deciles_1_3": float(ev["pop_new_low_income"].sum() / max(pn, 1)),
        "share_new_in_low_density": float(ev["pop_new_low_density"].sum() / max(pn, 1)),
        "by_stage": ({st: {"n_sites": int(msk.sum()), "cost_eur": float(picks["cost"].values[msk].sum()),
                           "pop_newly_served": float(ev["pop_new"].values[msk].sum())}
                      for st in picks["stage"].unique() for msk in [(picks["stage"] == st).values]}
                     if "stage" in picks else {}),
    }


# --------------------------------------------------------------------------- point d'entrée
def _mark_served(ctx, picks):
    """Copie du contexte où les sous-points couverts par `picks` comptent comme desservis."""
    sub = _sub(ctx)
    served = {k: v.copy() for k, v in sub["served"].items()}
    for k in picks["kind"].unique():
        cov = np.concatenate([np.asarray(c, int) for c in picks.loc[picks["kind"] == k, "covered"]])
        served[k][cov] = True
    return dict(ctx, sub=dict(sub, served=served))


def solve_split(ctx, budget=C.DEFAULT_BUDGET, equity_lambda=C.EQUITY_LAMBDA, kinds=C.MODEL_KINDS,
                horizon=C.GROWTH_HORIZON, split=C.BUDGET_SPLIT, rural_share=C.LOW_DENSITY_BUDGET_SHARE,
                naive=False, use_model=True, use_existing=True):
    """
    Optimisation en étapes successives (chaque étape voit les sites des précédentes comme
    offre existante) :
      1. quota « zones peu denses » : part `rural_share` du budget réservée aux candidats en
         zone peu dense (densité à ~1 km < C.LOW_DENSITY_HAB_KM2), tous types confondus.
         Raison : maximiser la couverture favorise mécaniquement les zones denses (un site
         y couvre 10× plus d'habitants), ce que λ seul ne compense pas ;
      2. enveloppes par type (parts `split`) sur le reste ;
      3. élagage : un site d'étape dont le rendement (gain/coût) est inférieur à
         C.ENVELOPE_MIN_YIELD × le meilleur rendement retenu est retiré (une enveloppe est un
         plafond, pas un montant à dépenser à tout prix : sans cela, dès qu'une enveloppe bus
         atteint le coût d'un arrêt, elle l'achète même s'il dessert 300 habitants, et la
         couverture peut baisser quand le budget augmente) ;
      4. réallocation du reliquat (parts non dépensées ou élaguées) en passage global, même si
         aucune étape n'a pu acheter de site (petit budget découpé en parts trop petites).
    naive=True : enveloppes par type seulement (pas de quota, pas de prise en compte de l'offre).
    use_model / use_existing : cf. solve() (variantes d'ablation du résumé).
    Colonne `stage` : étape d'origine du site (quota_peu_dense, enveloppe_<type>, reliquat).
    La liste finale est triée par gain/coût décroissant.
    """
    kinds = tuple(kinds)
    if naive:
        use_model, use_existing = False, False
    _sub(ctx)
    stages = []
    if rural_share and not naive:
        stages.append(("quota_peu_dense", budget * rural_share, kinds, _low_density_mask(ctx)))
    rest = budget - sum(st[1] for st in stages)
    if split and len(kinds) > 1:
        tot = sum(split.get(k, 0) for k in kinds) or 1.0
        stages += [(f"enveloppe_{k}", rest * split.get(k, 0) / tot, (k,), None) for k in kinds]
    else:
        stages.append(("global", rest, kinds, None))
    kw = dict(naive=naive, use_model=use_model, use_existing=use_existing)
    parts, cur = [], ctx
    for label, b, ks, filt in stages:
        if b <= 0:
            continue
        p = solve(cur, b, equity_lambda, ks, horizon, cand_filter=filt, **kw)
        if len(p):
            parts.append(p.assign(stage=label))
            if use_existing:
                cur = _mark_served(cur, p)
    picks = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(picks) and C.ENVELOPE_MIN_YIELD and len(stages) > 1:
        r = picks["objective_gain"] / picks["cost"]
        keep = (r >= C.ENVELOPE_MIN_YIELD * r.max()).values
        if not keep.all():
            picks = picks[keep].reset_index(drop=True)
            if use_existing:
                cur = _mark_served(ctx, picks) if len(picks) else ctx
    left = budget - (picks["cost"].sum() if len(picks) else 0.0)
    # reliquat (parts non dépensées ou élaguées) : passage global ; nécessite que les sites déjà
    # retenus soient marqués desservis, donc pas pour les variantes qui ignorent l'existant
    if left > 0 and use_existing and len(stages) > 1:
        extra = solve(cur, left, equity_lambda, kinds, horizon, **kw)
        if len(extra):
            picks = pd.concat([picks, extra.assign(stage="reliquat")], ignore_index=True)
    if len(picks):
        picks = picks.assign(_r=picks["objective_gain"] / picks["cost"]).sort_values(
            "_r", ascending=False, kind="stable").drop(columns="_r").reset_index(drop=True)
    return picks


def _low_density_mask(ctx):
    return ctx["F"]["dens_1k"].values < C.LOW_DENSITY_HAB_KM2


def recommend(area="ems", budget=C.DEFAULT_BUDGET, equity_lambda=C.EQUITY_LAMBDA,
              kinds=C.MODEL_KINDS, horizon=C.GROWTH_HORIZON, split=C.BUDGET_SPLIT,
              rural_share=C.LOW_DENSITY_BUDGET_SHARE, compare=True, write=False):
    """
    Liste priorisée de sites pour la zone. Renvoie (DataFrame recommandations, dict résumé).
    compare=True ajoute au résumé les stratégies alternatives (même budget).
    """
    t0 = time.time()
    kinds = tuple(kinds)
    ctx = prepare(area)
    picks = solve_split(ctx, budget, equity_lambda, kinds, horizon, split, rural_share)
    ev = evaluate(ctx, picks, horizon)
    df = _assemble(ctx, picks, ev) if len(picks) else pd.DataFrame()
    cells, sub = ctx["cells"], ctx["sub"]
    ind_sub = cells["ind"].values[sub["cell"]] / sub["S2"]
    summary = {
        "area": ctx["name"], "offer_source": ctx["offer_source"], "prediction": ctx.get("pred_source"),
        "budget_eur": budget, "equity_lambda": equity_lambda, "kinds": list(kinds), "horizon": horizon,
        "budget_split": split, "low_density_budget_share": rural_share,
        "zone": {"cells": int(len(cells)), "population": float(cells["ind"].sum()),
                 "communes": int(cells["com"].nunique()),
                 "pop_without_any_option": float(ind_sub[~sub["any"]].sum()),
                 "already_served_share": {k: float(ind_sub[sub["served"][k]].sum() / ind_sub.sum())
                                          for k in kinds}},
        "selected": dict(_totals(ev, picks), label=STRATEGY_LABELS["selected"]),
    }
    if compare:
        summary["comparison"] = {}
        for label, kw in (("lambda_0", dict(equity_lambda=0.0)),
                          ("no_model_value_1", dict(use_model=False)),
                          ("ignore_existing_offer", dict(use_existing=False)),
                          ("no_low_density_quota", dict(rural_share=0.0)),
                          ("global_pool_no_split_no_quota", dict(split=None, rural_share=0.0)),
                          ("naive_population_only", dict(naive=True))):
            kw = {"equity_lambda": equity_lambda, "split": split, "rural_share": rural_share, **kw}
            pk = solve_split(ctx, budget, kinds=kinds, horizon=horizon, **kw)
            summary["comparison"][label] = dict(_totals(evaluate(ctx, pk, horizon), pk),
                                                label=STRATEGY_LABELS[label])
        if "freq_nearest" in ctx["F"]:   # effet de la fréquence des lignes, à données identiques
            nf = _without_frequency(ctx)
            pk = solve_split(nf, budget, equity_lambda, kinds, horizon, split, rural_share)
            summary["comparison"]["no_frequency"] = dict(_totals(evaluate(nf, pk, horizon), pk),
                                                         label=STRATEGY_LABELS["no_frequency"])
        summary["comparison"]["naive_population_only"]["definition"] = C.NAIVE_LABEL
        sel, comp = summary["selected"], summary["comparison"]
        notes = [
            "lambda_0 n'est pas « l'efficacité pure » : il maximise Σ pop·v (valeur du modèle), "
            "pas la population desservie ; λ > 0 peut donc desservir plus d'habitants.",
            "no_model_value_1 est la baseline honnête : même offre existante, enveloppes et quota, "
            "mais v = 1 (le modèle ne sert pas).",
        ]
        nv = comp["naive_population_only"]
        if nv.get("share_new_in_income_deciles_1_3", 0) > sel.get("share_new_in_income_deciles_1_3", 0):
            notes.append("La stratégie naïve a une part de nouveaux desservis en déciles 1-3 "
                         f"({nv['share_new_in_income_deciles_1_3']:.1%}) supérieure à la recommandée "
                         f"({sel['share_new_in_income_deciles_1_3']:.1%}), mais sur beaucoup moins "
                         "d'habitants (elle place des sites là où l'offre existe déjà).")
        summary["notes"] = notes
    summary["hypotheses"] = {
        "walk_radius_m": geo.walk_radius_m(),
        "coverage": f"{C.COVER_SUBSAMPLE}×{C.COVER_SUBSAMPLE} points par carreau, population uniforme",
        "weight": f"pop_horizon × (1 + {C.EQUITY_SCALE}·λ·besoin), besoin = " + json.dumps(C.NEED_WEIGHTS),
        "value": f"clip(p / p_ref, {C.VALUE_CLIP}) ** {C.MODEL_VALUE_EXPONENT} ; filtre v_rel >= "
                 f"{C.MODEL_VALUE_MIN} ; p_ref = " + json.dumps({k: round(v, 4) for k, v in ctx["p_ref"].items()}),
        "costs": {k: {"capex": C.COSTS[k]["capex"], "opex_per_yr": C.COSTS[k]["opex"],
                      "horizon_years": C.HORIZON_YEARS} for k in C.COSTS},
        "bus_detour": dict(C.BUS_DETOUR, formula="2·d/1000 × passages/j × 365 × €/km"),
        "co2": {
            "citiz": f"min({C.CITIZ_DRIVERS_FR}/{C.CITIZ_CARS_FR} adhérents/véhicule, pop_new × "
                     f"pénétration {ctx['penetration']:.4f} × min(v, {C.USAGE_VALUE_CAP})) × {C.CARSHARING_ACTIVE_SHARE} actifs × "
                     f"{C.CARSHARING_CAR_KM_AVOIDED_PER_USER} km × {C.CO2_G_PER_KM['car']} g/km",
            "bike": f"{C.BIKE_TRIPS_PER_STATION_DAY} trajets/j × min(v, {C.USAGE_VALUE_CAP}) × min(1, pop_new / "
                    f"{ctx.get('bike_ref_pop', C.BIKE_REF_POP):.0f}) × 365 × {C.BIKE_KM_PER_TRIP} km × "
                    f"{C.BIKE_CAR_SHIFT} report × {C.CO2_G_PER_KM['car']} g/km",
            "bus": f"pop_new × {C.BUS_TRIPS_PER_RESIDENT_DAY} montées/j × min(v, {C.USAGE_VALUE_CAP}) × 365 × {C.BUS_KM_PER_TRIP} km × "
                   f"{C.BUS_CAR_SHIFT} report × ({C.CO2_G_PER_KM['car']}-{C.BUS_PASSENGER_MARGINAL_G_PER_KM:g})"
                   f" g/km − détour km-véhicule × {C.BUS_KGCO2_PER_VKM} kg/km",
            "source": "impactco2.fr (ADEME Base Empreinte), enquête nationale autopartage ADEME/6t 2022",
        },
        "privacy": f"parts non publiées si < {C.PRIVACY_MIN_HOUSEHOLDS} ménages dans la zone servie",
        "bus_frequency": (f"valeur d'un arrêt × clip(départs/h de la ligne la plus proche ÷ {C.FULL_OPTION_DEP_H:g}, "
                          f"{C.FREQ_MIN_FACTOR}, 1) ; besoin « faible accessibilité » = options pondérées par la "
                          "fréquence (GTFS de la zone, src/frequency.py)")
                         if "freq_nearest" in ctx["F"] else "GTFS de la zone non lus : arrêts comptés sans fréquence",
    }
    if ctx.get("frequency"):
        summary["frequency"] = ctx["frequency"].get("comparaison")
    summary["runtime_s"] = {"prepare": round(ctx["prep_s"], 2), "total": round(time.time() - t0, 2)}
    if write:
        df.to_csv(C.OUT / "recommendations.csv", index=False)
        (C.OUT / "recommendations_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                                                       default=float), encoding="utf-8")
    return df, summary


FUNDERS = {
    # clé -> (libellé, types d'équipement financés)
    "citiz": ("Citiz (opérateur d'autopartage)", ("citiz",)),
    "collectivite": ("Collectivité / AOM (vélo, bus)", ("bike", "bus")),
}


def area_label(area):
    """Nom lisible d'une zone de recommandation."""
    if area in (None, "ems", "strasbourg"):
        return "Eurométropole de Strasbourg"
    if str(area).startswith("epci:"):
        from src import territories
        return territories.epci_name(str(area).split(":", 1)[1])
    return f"Département {area}"


def recommend_by_funder(area="ems", citiz_budget=C.CITIZ_BUDGET, public_budget=C.PUBLIC_BUDGET,
                        equity_lambda=C.EQUITY_LAMBDA, horizon=C.GROWTH_HORIZON, split=C.BUDGET_SPLIT,
                        rural_share=C.LOW_DENSITY_BUDGET_SHARE, compare=True):
    """
    Deux listes priorisées indépendantes, une par financeur : Citiz (stations d'autopartage, budget
    `citiz_budget`) et la collectivité (stations vélo + arrêts de bus, `public_budget`, réparti
    selon `split`). Chaque type a sa propre couverture (cf. solve) : les deux listes ne se gênent pas.
    Renvoie (DataFrame avec colonne `financeur`, résumé {area, territoire, funders: {clé: résumé}}).
    """
    budgets = {"citiz": citiz_budget, "collectivite": public_budget}
    parts, summ = [], {}
    for key, (label, kinds) in FUNDERS.items():
        if budgets[key] <= 0:
            continue
        df, s = recommend(area, budgets[key], equity_lambda, kinds, horizon, split, rural_share, compare)
        s["label"] = label
        summ[key] = s
        if len(df):
            parts.append(df.assign(financeur=key))
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(df):
        df = df[["financeur"] + [c for c in df.columns if c != "financeur"]]
    any_s = next(iter(summ.values()), {})
    return df, {"area": any_s.get("area"), "territoire": area_label(area), "funders": summ}


def equity_curve(area, citiz_budget=C.CITIZ_BUDGET, public_budget=C.PUBLIC_BUDGET, lambdas=EQUITY_LAMBDAS,
                 horizon=C.GROWTH_HORIZON):
    """
    « Le prix de l'équité » : pour chaque λ, habitants nouvellement desservis et part de ces nouveaux
    desservis dans les 3 premiers déciles de revenu de la zone, par financeur (même budget).
    """
    rows = []
    for lam in lambdas:
        _, s = recommend_by_funder(area, citiz_budget, public_budget, lam, horizon, compare=False)
        for key, fs in s["funders"].items():
            sel = fs.get("selected") or {}
            if sel.get("n_sites"):
                rows.append({"lambda": lam, "financeur": key, "n_sites": sel["n_sites"],
                             "pop_newly_served": sel["pop_newly_served"],
                             "share_new_in_income_deciles_1_3": sel["share_new_in_income_deciles_1_3"],
                             "co2_avoided_t_yr": sel["co2_avoided_t_yr"]})
    return rows


def _area_files(area):
    """Suffixe des fichiers de sortie : '' pour le territoire prioritaire, '_<zone>' sinon."""
    from src import territories
    return "" if area == territories.top_area() else "_" + _area_bounds(area)[0]


def main():
    from src import territories
    ap = argparse.ArgumentParser(description="Recommandation de sites sous budget, par financeur")
    ap.add_argument("--area", default=None,
                    help="'ems', 'epci:<siren>' (défaut : territoire prioritaire de src.territories)")
    ap.add_argument("--dep", default=None, help="code département (remplace --area)")
    ap.add_argument("--citiz-budget", type=float, default=C.CITIZ_BUDGET)
    ap.add_argument("--public-budget", type=float, default=C.PUBLIC_BUDGET)
    ap.add_argument("--lambda", dest="lam", type=float, default=C.EQUITY_LAMBDA)
    ap.add_argument("--horizon", type=int, default=C.GROWTH_HORIZON)
    ap.add_argument("--no-split", action="store_true", help="vélo/bus : budget commun sans enveloppes")
    a = ap.parse_args()
    area = a.dep or a.area or territories.top_area()
    t0 = time.time()
    df, s = recommend_by_funder(area, a.citiz_budget, a.public_budget, a.lam, a.horizon,
                                split=None if a.no_split else C.BUDGET_SPLIT)
    suffix = _area_files(area)
    df.to_csv(C.OUT / f"recommendations{suffix}.csv", index=False)
    (C.OUT / f"recommendations_summary{suffix}.json").write_text(
        json.dumps(s, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    pd.set_option("display.width", 200)
    cols = ["financeur", "rank", "type", "stage", "commune", "pop_newly_served", "usage_pred", "usage_unit",
            "cost_eur", "cost_cum_eur", "co2_avoided_t_yr"]
    print(f"== {s['territoire']} -> recommendations{suffix}.csv")
    print(df[cols].to_string(index=False) if len(df) else "aucun site")
    for key, fs in s["funders"].items():
        print(f"-- {fs['label']}")
        print(json.dumps({k: fs[k] for k in ("zone", "selected") if k in fs}, indent=1, ensure_ascii=False,
                         default=float))
    print(f"temps total (premier appel, chargement compris) : {time.time() - t0:.1f} s")
    t1 = time.time()
    curve = equity_curve(area, a.citiz_budget, a.public_budget, horizon=a.horizon)
    (C.OUT / f"equity_curve{suffix}.json").write_text(
        json.dumps({"territoire": s["territoire"], "citiz_budget": a.citiz_budget, "public_budget": a.public_budget,
                    "points": curve}, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"prix de l'équité ({len(EQUITY_LAMBDAS)} valeurs de λ) -> equity_curve{suffix}.json "
          f"({time.time() - t1:.1f} s)")


if __name__ == "__main__":
    main()
