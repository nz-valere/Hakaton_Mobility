"""
Étape 6 – Orchestration : liste priorisée de nouveaux sites (Citiz, station vélo, arrêt de
bus) sous contrainte de budget, en tenant compte de l'offre existante.

Chaîne :
    1. zone (Eurométropole de Strasbourg par défaut, ou un département) : carreaux habités
       + marge de 4 km pour les variables de bassin ; variables model.build_features()
       (mises en cache disque par zone) et propensions model.predict_value() par type ;
    2. candidats = centres des carreaux habités de la zone × type, non déjà desservis par ce
       type ; bus : uniquement à ≤ C.BUS_DETOUR["max_dist_m"] d'un arrêt existant ;
    3. couverture = carreaux de la zone à ≤ geo.walk_radius_m() du candidat ;
    4. poids d'un carreau  w_i = pop_horizon_i × (1 + C.EQUITY_SCALE·λ·besoin_i), mis à 0 pour le type t
       si le carreau est déjà desservi par t (bus : transit/rail ; vélo : bike ;
       Citiz : citiz/carsharing). Les types ont chacun leur copie des carreaux : un arrêt de
       bus ne rend pas une station Citiz inutile ;
       besoin_i ∈ [0,1] = Σ poids × rang-percentile (dans la zone) de : taux de pauvreté,
       part de ménages sans voiture, faiblesse de l'accessibilité actuelle (nb d'options à
       5 min, tous modes ; `score` de outputs/cells_access.parquet s'il existe) — cf. C.NEED_WEIGHTS. Rangs relatifs à la zone : l'outil compare
       des quartiers d'un même territoire, sans étiqueter de quartier « pauvre » ;
    5. valeur du site v_j = clip(p_j / p_ref, C.VALUE_CLIP) × C.KIND_BENEFIT[t] : 1 signifie
       « aussi favorable qu'un site existant typique » selon le modèle ;
    6. coût = C.facility_cost(t, extra) ; bus : extra = exploitation du détour
       2·d/1000 km × passages/jour × 365 × €/km, d = distance à l'arrêt existant le plus proche ;
    7. optimize.optimize() (glouton budgété, garantie (1-1/e)/2) maximise Σ v_j·w_i couverts.

Comparaisons (résumé json) : même budget avec λ = 0 (efficacité pure) et stratégie naïve
« population seule » (sans modèle, sans tenir compte de l'offre existante, λ = 0), évaluées
sur les mêmes indicateurs : population réellement nouvellement desservie, CO2 évité, part
des nouveaux desservis dans les 3 premiers déciles de revenu de la zone et en zone peu dense.

Confidentialité : les parts (pauvreté, sans voiture) ne sont publiées que si la zone servie
compte au moins C.PRIVACY_MIN_HOUSEHOLDS ménages.

Enveloppes : par défaut le budget est réparti par type (C.BUDGET_SPLIT, financeurs distincts),
le reliquat étant réalloué globalement ; --no-split laisse l'optimiseur arbitrer seul.

Usage : python -m src.recommend [--dep 54] [--budget 2000000] [--lambda 0.5] [--no-split]
"""
import argparse
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


# --------------------------------------------------------------------------- préparation de la zone
def _area_bounds(area):
    """area : 'ems' (bbox Eurométropole), code département ('54', '2A'…) ou bbox (o, s, e, n)."""
    if area in (None, "ems", "strasbourg"):
        return "ems", C.STRASBOURG_BBOX, C.STRASBOURG_DEPT
    if isinstance(area, (tuple, list)):
        return "bbox_" + "_".join(f"{v:.3f}" for v in area), tuple(area), None
    dep = str(area).zfill(2)
    d = pd.read_parquet(C.INTERIM / "cells.parquet", columns=["lon", "lat"], filters=[("dep", "==", dep)])
    if len(d) == 0:
        raise ValueError(f"aucun carreau pour le département {dep}")
    return f"dep{dep}", (d["lon"].min(), d["lat"].min(), d["lon"].max(), d["lat"].max()), dep


def prepare(area="ems", force=False):
    """Carreaux, variables et propensions de la zone (mémoire + cache disque)."""
    name, (w, s, e, n), dep = _area_bounds(area)
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
    offer, src = model.load_offer()
    cache = model.CACHE / f"area_{name}.parquet"
    meta = model.CACHE / f"area_{name}.json"
    if cache.exists() and meta.exists() and not force \
            and json.loads(meta.read_text()) == {"offer_source": src, "n": len(cells),
                                              "radius": geo.walk_radius_m()}:
        F = pd.read_parquet(cache)
    else:
        ob = offer[(offer["lon"] >= w - 4 * bx) & (offer["lon"] <= e + 4 * bx)
                   & (offer["lat"] >= s - 4 * by) & (offer["lat"] <= n + 4 * by)]
        F = model.build_features(cells, ob)
        F.to_parquet(cache, index=False)
        meta.write_text(json.dumps({"offer_source": src, "n": len(cells), "radius": geo.walk_radius_m()}))
    keep = np.flatnonzero(in_area)
    cells, F = cells.iloc[keep].reset_index(drop=True), F.iloc[keep].reset_index(drop=True)
    # score d'accessibilité 0-100 de l'étape 4 (si disponible) pour le volet « besoin »
    fa = C.OUT / "cells_access.parquet"
    if fa.exists():
        acc = pd.read_parquet(fa, columns=["key", "score"], filters=[("lon", ">=", w), ("lon", "<=", e),
                                                                  ("lat", ">=", s), ("lat", "<=", n)])
        F["access_score"] = cells["key"].map(acc.set_index("key")["score"]).values
    pred, p_ref, extra = {}, {}, {}
    for k in C.MODEL_KINDS:
        pred[k] = model.predict_value(F, k)
        b = model.load_bundle(k)
        p_ref[k] = b["p_ref"]
        if "penetration" in b:
            extra["penetration"] = b["penetration"]
    names = model.load_communes()["com_name"]
    ctx = {"name": name, "cells": cells, "F": F, "pred": pred, "p_ref": p_ref,
           "com_name": cells["com"].map(names).fillna(cells["com"]).values,
           "offer_source": src, "penetration": extra.get("penetration", 0.002),
           "prep_s": time.time() - t0}
    _CTX[name] = ctx
    return ctx


# --------------------------------------------------------------------------- briques
def served_mask(F, kind):
    """Carreau déjà desservi (≥ 1 point d'un mode cible du type à 5 min)."""
    return (sum(F[f"n_{m}_r5"].values for m in C.KIND_TARGET_MODES[kind]) > 0)


def _rank(v):
    return pd.Series(v).rank(pct=True, method="average").fillna(0.5).values


def need_index(cells, F):
    """Besoin ∈ [0,1] : rangs-percentiles pondérés (pauvreté, sans voiture, faible accessibilité)."""
    wts = C.NEED_WEIGHTS
    parts = {"poverty_rate": _rank(cells["poverty_rate"].values),
             "carfree_share": _rank(cells["carfree_share"].values),
             "low_access": _rank(-(F["access_score"].fillna(0).values if "access_score" in F
                                   else F["n_options_r5"].values))}
    return sum(wts[k] * parts[k] for k in wts) / sum(wts.values())


def pop_at(cells, horizon):
    """Population à l'horizon : interpolation linéaire du facteur Omphale 2021 -> GROWTH_HORIZON."""
    t = (horizon - 2021) / (C.GROWTH_HORIZON - 2021)
    return cells["ind"].values * (1 + (cells["growth"].fillna(1).values - 1) * t)


def bus_extra_annual(d):
    """Surcoût annuel d'exploitation du détour (aller-retour 2·d) pour un arrêt à d m de la ligne."""
    b = C.BUS_DETOUR
    return 2 * d / 1000 * b["trips_per_day"] * 365 * b["cost_per_km"]


def _coverage(cells, cand_idx):
    """Liste (par candidat) des indices de carreaux à ≤ rayon de marche du centre du candidat."""
    r = geo.walk_radius_m()
    cx, cy, cc = (cells[c].values for c in ("x", "y", "crs_id"))
    I, J = geo.pairs_within(cc[cand_idx], cx[cand_idx], cy[cand_idx], cc, cx, cy, r)
    order = np.argsort(I, kind="stable")
    I, J = I[order], J[order]
    bounds = np.searchsorted(I, np.arange(len(cand_idx) + 1))
    return [J[bounds[a]:bounds[a + 1]] for a in range(len(cand_idx))]


def solve(ctx, budget=C.DEFAULT_BUDGET, equity_lambda=C.EQUITY_LAMBDA, kinds=C.MODEL_KINDS,
          horizon=C.GROWTH_HORIZON, naive=False, max_sites=None, cand_filter=None):
    """
    Sélection gloutonne budgétée (cand_filter : masque booléen des carreaux candidats admis). naive=True : stratégie « population seule » (v = 1, λ = 0,
    offre existante ignorée dans le choix). Renvoie le DataFrame des sites choisis (ordonnés).
    """
    cells, F = ctx["cells"], ctx["F"]
    n = len(cells)
    pop_h = pop_at(cells, horizon)
    lam = 0.0 if naive else equity_lambda
    w_base = pop_h * (1 + C.EQUITY_SCALE * lam * need_index(cells, F))
    hab = np.flatnonzero(cells["ind"].values > 0)
    d_bus = F["d_transit"].values.astype(float)

    cand_cells, val, cost, meta, W = [], [], [], [], []
    for t, kind in enumerate(kinds):
        served = served_mask(F, kind)
        W.append(w_base if naive else np.where(served, 0.0, w_base))
        idx = hab if naive else hab[~served[hab]]
        if cand_filter is not None:
            idx = idx[cand_filter[idx]]
        ext = np.zeros(len(idx))
        if kind == "bus":
            ok = d_bus[idx] <= C.BUS_DETOUR["max_dist_m"]
            idx = idx[ok]
            ext = bus_extra_annual(d_bus[idx])
        if len(idx) == 0:
            continue
        cov = _coverage(cells, idx)
        p = ctx["pred"][kind][idx]
        v = np.ones(len(idx)) if naive else \
            np.clip(p / ctx["p_ref"][kind], *C.VALUE_CLIP) * C.KIND_BENEFIT[kind]
        cand_cells += [c + t * n for c in cov]
        val.append(v)
        cost.append(np.array([C.facility_cost(kind, e) for e in ext]))
        meta.append(pd.DataFrame({"kind": kind, "cell": idx, "p": p, "v_rel": np.clip(
            p / ctx["p_ref"][kind], *C.VALUE_CLIP), "extra_annual": ext}))
    if not cand_cells:
        return pd.DataFrame()
    val, cost, meta = np.concatenate(val), np.concatenate(cost), pd.concat(meta, ignore_index=True)
    meta["cost"] = cost
    chosen, gains, spent = optimize(cand_cells, val, cost, np.concatenate(W), budget, max_sites)
    out = meta.iloc[chosen].reset_index(drop=True)
    out["objective_gain"] = gains
    out["covered"] = [cand_cells[j] - kinds.index(k) * n for j, k in zip(chosen, out["kind"])]
    return out


def evaluate(ctx, picks, horizon=C.GROWTH_HORIZON):
    """Indicateurs RÉELS d'une sélection (population non déjà desservie, CO2, équité), site par site."""
    cells, F = ctx["cells"], ctx["F"]
    if len(picks) == 0:
        return pd.DataFrame()
    pop_h = pop_at(cells, horizon)
    ind, men = cells["ind"].values, cells["men"].fillna(0).values
    pauv = cells["men_pauv"].fillna(0).values
    carfree_men = cells["carfree_share"].values * men
    inc = cells["income_pc"].values
    ok = np.isfinite(inc)
    # 3e décile de revenu (pondéré population) de la zone
    o = np.argsort(inc[ok])
    cum = np.cumsum(ind[ok][o]) / ind[ok].sum()
    d3 = inc[ok][o][np.searchsorted(cum, 0.3)]
    low_inc = ok & (inc <= d3)
    low_dens = F["dens_1k"].values < C.LOW_DENSITY_HAB_KM2
    taken = {k: served_mask(F, k).copy() for k in C.MODEL_KINDS}
    pen, per_car = ctx["penetration"], C.CITIZ_DRIVERS_FR / C.CITIZ_CARS_FR
    rows = []
    for _, s in picks.iterrows():
        k = s["kind"]
        cov = s["covered"]
        new = cov[~taken[k][cov]]
        taken[k][new] = True
        pn, mn = ind[new].sum(), men[new].sum()
        v = s["v_rel"]
        # usage prédit et CO2 évité (t/an), hypothèses de Config (impactco2 / ADEME)
        if k == "citiz":
            usage = min(per_car, pn * pen * v)                     # adhérents
            unit = "adhérents"
            co2 = usage * C.CARSHARING_ACTIVE_SHARE * C.CARSHARING_CAR_KM_AVOIDED_PER_USER \
                * C.CO2_G_PER_KM["car"] / 1e6
        elif k == "bike":
            usage = C.BIKE_TRIPS_PER_STATION_DAY * v                # trajets / jour
            unit = "trajets/jour"
            co2 = usage * 365 * C.BIKE_KM_PER_TRIP * C.BIKE_CAR_SHIFT \
                * (C.CO2_G_PER_KM["car"] - C.CO2_G_PER_KM["bike"]) / 1e6
        else:
            usage = pn * C.BUS_TRIPS_PER_RESIDENT_DAY * v           # montées / jour
            unit = "montées/jour"
            detour_vkm = 2 * F["d_transit"].values[s["cell"]] / 1000 * C.BUS_DETOUR["trips_per_day"]
            co2 = usage * 365 * C.BUS_KM_PER_TRIP * C.BUS_CAR_SHIFT \
                * (C.CO2_G_PER_KM["car"] - C.CO2_G_PER_KM["bus"]) / 1e6 \
                - detour_vkm * 365 * C.BUS_KGCO2_PER_VKM / 1e3
        priv = mn >= C.PRIVACY_MIN_HOUSEHOLDS
        rows.append({
            "pop_new": pn, "pop_new_horizon": pop_h[new].sum(), "households_new": mn,
            "usage_pred": usage, "usage_unit": unit, "co2_avoided_t_yr": co2,
            "share_poor_households": pauv[new].sum() / mn if priv else np.nan,
            "share_carfree_households": carfree_men[new].sum() / mn if priv else np.nan,
            "pop_new_low_income": ind[new][low_inc[new]].sum() if len(new) else 0.0,
            "pop_new_low_density": ind[new][low_dens[new]].sum() if len(new) else 0.0,
        })
    return pd.DataFrame(rows)


def _assemble(ctx, picks, ev):
    cells = ctx["cells"]
    i = picks["cell"].values
    df = pd.DataFrame({
        "rank": np.arange(1, len(picks) + 1), "type": picks["kind"].values,
        "equipement": picks["kind"].map(KIND_LABEL).values,
        "lon": cells["lon"].values[i].round(5), "lat": cells["lat"].values[i].round(5),
        "commune": ctx["com_name"][i], "code_commune": cells["com"].values[i],
        "pop_newly_served": ev["pop_new"].round(0).values,
        f"pop_{C.GROWTH_HORIZON}": ev["pop_new_horizon"].round(0).values,
        "propensity": picks["p"].round(4).values, "value_rel": picks["v_rel"].round(3).values,
        "usage_pred": ev["usage_pred"].round(1).values, "usage_unit": ev["usage_unit"].values,
        "cost_eur": picks["cost"].round(0).values,
    })
    df["cost_cum_eur"] = df["cost_eur"].cumsum()
    df["eur_per_new_resident"] = (df["cost_eur"] / df["pop_newly_served"].replace(0, np.nan)).round(0)
    df["co2_avoided_t_yr"] = ev["co2_avoided_t_yr"].round(2).values
    df["share_poor_households"] = ev["share_poor_households"].round(3).values
    df["share_carfree_households"] = ev["share_carfree_households"].round(3).values
    return df


def _totals(ev, picks):
    if len(ev) == 0:
        return {"n_sites": 0}
    pn = ev["pop_new"].sum()
    return {
        "n_sites": int(len(picks)), "by_type": picks["kind"].value_counts().to_dict(),
        "cost_eur": float(picks["cost"].sum()), "pop_newly_served": float(pn),
        "pop_newly_served_horizon": float(ev["pop_new_horizon"].sum()),
        "eur_per_new_resident": float(picks["cost"].sum() / max(pn, 1)),
        "co2_avoided_t_yr": float(ev["co2_avoided_t_yr"].sum()),
        "share_new_in_income_deciles_1_3": float(ev["pop_new_low_income"].sum() / max(pn, 1)),
        "share_new_in_low_density": float(ev["pop_new_low_density"].sum() / max(pn, 1)),
    }


# --------------------------------------------------------------------------- point d'entrée
def _mark_served(ctx, picks):
    """Copie du contexte où les carreaux couverts par `picks` comptent comme desservis."""
    ctx2 = dict(ctx, F=ctx["F"].copy())
    for k in picks["kind"].unique():
        cov = np.unique(np.concatenate(picks.loc[picks["kind"] == k, "covered"].tolist()))
        col = f"n_{C.KIND_TARGET_MODES[k][0]}_r5"
        ctx2["F"].loc[cov, col] = ctx2["F"].loc[cov, col] + 1
    return ctx2


def solve_split(ctx, budget=C.DEFAULT_BUDGET, equity_lambda=C.EQUITY_LAMBDA, kinds=C.MODEL_KINDS,
                horizon=C.GROWTH_HORIZON, split=C.BUDGET_SPLIT, rural_share=C.LOW_DENSITY_BUDGET_SHARE,
                naive=False):
    """
    Optimisation en étapes successives (chaque étape voit les sites des précédentes comme
    offre existante) :
      1. quota « zones peu denses » : part `rural_share` du budget réservée aux candidats en
         zone peu dense (densité à ~1 km < C.LOW_DENSITY_HAB_KM2), tous types confondus.
         Raison : maximiser la couverture favorise mécaniquement les zones denses (un site
         y couvre 10× plus d'habitants), ce que λ seul ne compense pas ;
      2. enveloppes par type (parts `split`) sur le reste ;
      3. réallocation du reliquat en passage global.
    naive=True : enveloppes par type seulement (pas de quota, pas de prise en compte de l'offre).
    La liste finale est triée par gain/coût décroissant.
    """
    kinds = tuple(kinds)
    stages = []
    if rural_share and not naive:
        stages.append((budget * rural_share, kinds, _low_density_mask(ctx)))
    rest = budget - sum(b for b, _, _ in stages)
    if split and len(kinds) > 1:
        tot = sum(split.get(k, 0) for k in kinds) or 1.0
        stages += [(rest * split.get(k, 0) / tot, (k,), None) for k in kinds]
    else:
        stages.append((rest, kinds, None))
    parts, cur = [], ctx
    for b, ks, filt in stages:
        if b <= 0:
            continue
        p = solve(cur, b, equity_lambda, ks, horizon, naive, cand_filter=filt)
        if len(p):
            parts.append(p)
            if not naive:
                cur = _mark_served(cur, p)
    picks = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    left = budget - (picks["cost"].sum() if len(picks) else 0.0)
    if left > 0 and len(picks) and not naive and len(stages) > 1:
        extra = solve(cur, left, equity_lambda, kinds, horizon, naive)
        picks = pd.concat([picks, extra], ignore_index=True)
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
    compare=True ajoute au résumé les stratégies λ=0 et « population seule » (même budget).
    """
    t0 = time.time()
    kinds = tuple(kinds)
    ctx = prepare(area)
    picks = solve_split(ctx, budget, equity_lambda, kinds, horizon, split, rural_share)
    ev = evaluate(ctx, picks, horizon)
    df = _assemble(ctx, picks, ev) if len(picks) else pd.DataFrame()
    cells = ctx["cells"]
    summary = {
        "area": ctx["name"], "offer_source": ctx["offer_source"], "budget_eur": budget,
        "equity_lambda": equity_lambda, "kinds": list(kinds), "horizon": horizon, "budget_split": split,
        "low_density_budget_share": rural_share,
        "zone": {"cells": int(len(cells)), "population": float(cells["ind"].sum()),
                 "already_served_share": {k: float(cells["ind"].values[served_mask(ctx["F"], k)].sum()
                                                   / cells["ind"].sum()) for k in kinds}},
        "selected": _totals(ev, picks),
    }
    if compare:
        summary["comparison"] = {}
        for label, kw in (("lambda_0", dict(equity_lambda=0.0)), ("naive_population_only", dict(naive=True)),
                          ("no_low_density_quota", dict(rural_share=0.0)),
                          ("global_pool_no_split_no_quota", dict(split=None, rural_share=0.0))):
            kw = {"equity_lambda": equity_lambda, "split": split, "rural_share": rural_share, **kw}
            pk = solve_split(ctx, budget, kinds=kinds, horizon=horizon, **kw)
            summary["comparison"][label] = _totals(evaluate(ctx, pk, horizon), pk)
        summary["comparison"]["naive_population_only"]["definition"] = C.NAIVE_LABEL
    summary["hypotheses"] = {
        "walk_radius_m": geo.walk_radius_m(),
        "weight": f"pop_horizon × (1 + {C.EQUITY_SCALE}·λ·besoin), besoin = " + json.dumps(C.NEED_WEIGHTS),
        "value": f"clip(p / p_ref, {C.VALUE_CLIP}) ; p_ref = " + json.dumps(
            {k: round(v, 4) for k, v in ctx["p_ref"].items()}),
        "costs": {k: {"capex": C.COSTS[k]["capex"], "opex_per_yr": C.COSTS[k]["opex"],
                      "horizon_years": C.HORIZON_YEARS} for k in C.COSTS},
        "bus_detour": dict(C.BUS_DETOUR, formula="2·d/1000 × passages/j × 365 × €/km"),
        "co2": {
            "citiz": f"min({C.CITIZ_DRIVERS_FR}/{C.CITIZ_CARS_FR} adhérents/véhicule, pop_new × "
                     f"pénétration {ctx['penetration']:.4f} × v) × {C.CARSHARING_ACTIVE_SHARE} actifs × "
                     f"{C.CARSHARING_CAR_KM_AVOIDED_PER_USER} km × {C.CO2_G_PER_KM['car']} g/km",
            "bike": f"{C.BIKE_TRIPS_PER_STATION_DAY} trajets/j × v × 365 × {C.BIKE_KM_PER_TRIP} km × "
                    f"{C.BIKE_CAR_SHIFT} report × {C.CO2_G_PER_KM['car']} g/km",
            "bus": f"pop_new × {C.BUS_TRIPS_PER_RESIDENT_DAY} montées/j × v × 365 × {C.BUS_KM_PER_TRIP} km × "
                   f"{C.BUS_CAR_SHIFT} report × ({C.CO2_G_PER_KM['car']}-{C.CO2_G_PER_KM['bus']}) g/km "
                   f"− détour km-véhicule × {C.BUS_KGCO2_PER_VKM} kg/km",
            "source": "impactco2.fr (ADEME Base Empreinte), enquête nationale autopartage ADEME/6t 2022",
        },
        "privacy": f"parts non publiées si < {C.PRIVACY_MIN_HOUSEHOLDS} ménages dans la zone servie",
    }
    summary["runtime_s"] = {"prepare": round(ctx["prep_s"], 2), "total": round(time.time() - t0, 2)}
    if write:
        df.to_csv(C.OUT / "recommendations.csv", index=False)
        (C.OUT / "recommendations_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                                                       default=float))
    return df, summary


def main():
    ap = argparse.ArgumentParser(description="Recommandation de sites sous budget")
    ap.add_argument("--dep", default=None, help="code département (défaut : Eurométropole de Strasbourg)")
    ap.add_argument("--budget", type=float, default=C.DEFAULT_BUDGET)
    ap.add_argument("--lambda", dest="lam", type=float, default=C.EQUITY_LAMBDA)
    ap.add_argument("--kinds", default=",".join(C.MODEL_KINDS))
    ap.add_argument("--horizon", type=int, default=C.GROWTH_HORIZON)
    ap.add_argument("--no-split", action="store_true", help="budget global sans enveloppes par type")
    a = ap.parse_args()
    area = a.dep or "ems"
    t0 = time.time()
    df, s = recommend(area, a.budget, a.lam, a.kinds.split(","), a.horizon,
                      split=None if a.no_split else C.BUDGET_SPLIT, write=(a.dep is None))
    if a.dep is not None:   # autre zone : fichiers suffixés pour ne pas écraser l'étude de cas
        df.to_csv(C.OUT / f"recommendations_dep{a.dep}.csv", index=False)
        (C.OUT / f"recommendations_summary_dep{a.dep}.json").write_text(
            json.dumps(s, indent=2, ensure_ascii=False, default=float))
    pd.set_option("display.width", 200)
    cols = ["rank", "type", "commune", "pop_newly_served", "usage_pred", "usage_unit", "cost_eur",
            "cost_cum_eur", "co2_avoided_t_yr"]
    print(df[cols].head(15).to_string(index=False) if len(df) else "aucun site")
    print(json.dumps({k: s[k] for k in ("selected", "comparison", "runtime_s")}, indent=1,
                     ensure_ascii=False, default=float))
    print(f"temps total (premier appel, chargement compris) : {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
