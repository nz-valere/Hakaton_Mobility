"""
Étape 4 – Accessibilité : options de transport à 5 minutes de marche, par carreau et par point d'offre.

Entrées : data/interim/cells.parquet (carreaux 200 m habités), data/interim/offer.parquet
(points d'offre dédoublonnés, option --offer pour un autre fichier), outputs/walk_calibration.json
(via geo.walk_radius_m()).

Rayon « 5 minutes »
-------------------
400 m de réseau (4,8 km/h × 5 min) approximés par un cercle euclidien r = 400 / détour, le détour
étant calibré sur le graphe piéton OSM de Strasbourg (src/walk_calibration.py : r ≈ 282 m,
détour ≈ 1,42, critère d'égalité des effectifs ; précision 0,92 / rappel 0,98 sur la population
desservie, biais de comptage +5 %). Distances mesurées depuis le *centre* du carreau.

Indicateurs par carreau i (voisinage V(i) = points / carreaux à ≤ r du centre de i)
-----------------------------------------------------------------------------------
- n_<mode>       = nombre de points d'offre du mode dans V(i) ;
- n_options      = Σ_mode C.MODE_WEIGHT[mode] · n_<mode> (poids 1 par défaut : « nombre d'options ») ;
- n_modes        = nombre de modes distincts accessibles (diversité) ;
- served_<mode>  = n_<mode> > 0 ;
- pop_catchment  = habitants des carreaux dont le centre est à ≤ r du centre de i (i inclus) :
                   la population qui « se partage » les mêmes options ;
- options_per_1000 = 1000 · n_options / pop_catchment : offre par habitant, version simple ;
- access_2sfca   = Two-Step Floating Catchment Area (Luo & Wang 2003), mesure standard de
                   « l'offre par habitant » en accessibilité : étape 1, chaque point j reçoit un
                   ratio R_j = w_j / P_j où P_j = habitants à ≤ r de j ; étape 2, A_i = 1000 · Σ_{j∈V(i)} R_j
                   (options pour 1000 habitants, concurrence entre habitants prise en compte point par
                   point). Propriété : Σ_i ind_i · A_i = 1000 · Σ_j w_j (l'offre est intégralement répartie
                   entre ses usagers potentiels) ;
- score_options / score_2sfca (0-100, froid -> chaud) = 0 si aucune option à 5 min ; sinon
                   SCORE_MIN_SERVED + (100 - SCORE_MIN_SERVED) · rang-percentile national pondéré par la
                   population de n_options (resp. access_2sfca) parmi les carreaux desservis.
                   Pourquoi un rang : les distributions sont à queue très lourde (Paris : 40 options
                   en moyenne, un arrêt isolé desservant 5 habitants donne un ratio 2SFCA énorme) ;
                   le rang est invariant aux transformations monotones, insensible aux extrêmes et se
                   lit directement (« score 80 = mieux doté que 80 % des habitants desservis »).
                   Le 0 strict garantit qu'un carreau sans option est le plus froid.
- score          = score_<C.SCORE_BASIS>, "n_options" par défaut. Choix assumé : « options par
                   habitant » est lu comme « options accessibles *depuis le domicile de chaque
                   habitant* » (mesure au carreau, pondérée par la population dans tous les agrégats).
                   La version ratio (2SFCA) répond à une autre question — la *capacité* partagée — et
                   produit un artefact connu : un hameau avec un arrêt (ratio 1 / 30 hab.) devient
                   « chaud » et le centre de Strasbourg « froid » (score moyen pondéré : carreaux
                   desservis peu denses 82 vs Strasbourg 28 en 2SFCA ; 23 vs 58 en n_options).
                   Sans fréquence ni capacité par arrêt, diviser par la population pénalise la
                   densité au lieu de mesurer la saturation. access_2sfca reste exporté pour la
                   lecture « concurrence » et pour l'analyse de sensibilité.

Indicateurs par point d'offre j
-------------------------------
pop_served = Σ ind des carreaux à ≤ r ; households_served = Σ men ; pop_served_exclusive = habitants
des carreaux pour lesquels j est le seul point de son mode à ≤ r (perte nette si le point fermait).

Confidentialité (C.PRIVACY_MIN_HOUSEHOLDS = 11)
------------------------------------------------
Filosofi impute déjà les caractéristiques des carreaux de moins de 11 ménages. Règle d'affichage :
les indicateurs d'accessibilité sont purement géographiques et peuvent être cartographiés au carreau ;
toute statistique socio-économique (revenu, pauvreté…) n'est affichée qu'agrégée sur ≥ 11 ménages.
La colonne `privacy_ok` (men ≥ seuil) est fournie dans les trois sorties ; commune_access et
access_summary n'agrègent que des groupes très supérieurs au seuil.

Sorties : outputs/cells_access.parquet, outputs/stations_served.parquet,
outputs/commune_access.parquet, outputs/access_summary.json
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
from src import geo  # noqa: E402

MODES = list(C.MODES)
CELL_COLS = ["key", "crs_id", "x", "y", "lon", "lat", "com", "dep", "ind", "men", "income_pc", "territory"]


# --------------------------------------------------------------------------- voisinages
def cell_neighbours(cells, radius):
    """
    Paires (i, k) de carreaux dont les centres sont à ≤ radius, i ≠ k inclus et i = k inclus.
    Les carreaux sont sur une grille exacte de 200 m : on énumère les décalages (dl, dc) admissibles
    et on retrouve les voisins par leur clé (population.cell_key), sans KD-tree.
    """
    keys = cells["key"].to_numpy()
    order = np.argsort(keys)
    sk = keys[order]
    m = int(np.floor(radius / C.CELL))
    I, K = [], []
    for dl in range(-m, m + 1):
        for dc in range(-m, m + 1):
            if C.CELL * np.hypot(dl, dc) > radius + 1e-9:
                continue
            target = keys + dl * 10**6 + dc
            pos = np.searchsorted(sk, target)
            pos = np.minimum(pos, len(sk) - 1)
            ok = sk[pos] == target
            I.append(np.flatnonzero(ok))
            K.append(order[pos[ok]])
    return np.concatenate(I), np.concatenate(K)


def weighted_rank(values, weights):
    """Rang-percentile pondéré ∈ [0, 1] (milieu de classe pour les ex æquo)."""
    order = np.argsort(values, kind="mergesort")
    v, w = values[order], weights[order]
    cw = np.cumsum(w)
    tot = cw[-1]
    # bornes des groupes d'ex æquo
    uniq, start = np.unique(v, return_index=True)
    end = np.r_[start[1:], len(v)]
    lo = np.where(start > 0, cw[start - 1], 0.0)
    mid = (lo + cw[end - 1]) / 2 / tot
    out = np.empty(len(values))
    out[order] = np.repeat(mid, end - start)
    return out


def wmedian(x, w):
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, cw[-1] / 2)]) if len(x) else np.nan


# --------------------------------------------------------------------------- calcul
def compute(cells, offer, radius):
    """Cœur du calcul (testable) : renvoie (cells_access, stations_served)."""
    nc, no, nm = len(cells), len(offer), len(MODES)
    ind = cells["ind"].to_numpy(float)
    men = cells["men"].to_numpy(float)
    mode_code = offer["mode"].map({m: k for k, m in enumerate(MODES)}).to_numpy()
    w_mode = np.array([C.MODE_WEIGHT[m] for m in MODES])
    w_pt = w_mode[mode_code]

    # paires carreau -> point d'offre (KD-tree par territoire)
    ci, oj = geo.pairs_within(cells.crs_id.values, cells.x.values, cells.y.values,
                              offer.crs_id.values, offer.x.values, offer.y.values, radius)
    n = np.bincount(ci * nm + mode_code[oj], minlength=nc * nm).reshape(nc, nm).astype(np.int32)

    # population à ≤ r de chaque carreau (grille)
    a, b = cell_neighbours(cells, radius)
    pop_catch = np.bincount(a, weights=ind[b], minlength=nc)

    # par point d'offre
    pop_served = np.bincount(oj, weights=ind[ci], minlength=no)
    hh_served = np.bincount(oj, weights=men[ci], minlength=no)
    excl = n[ci, mode_code[oj]] == 1
    pop_excl = np.bincount(oj[excl], weights=ind[ci[excl]], minlength=no)

    # 2SFCA
    R = np.divide(w_pt, pop_served, out=np.zeros(no), where=pop_served > 0)
    a2 = 1000 * np.bincount(ci, weights=R[oj], minlength=nc)

    out = cells[[c for c in CELL_COLS if c in cells.columns]].copy()
    for k, m in enumerate(MODES):
        out[f"n_{m}"] = n[:, k]
    n_opt = n @ w_mode
    out["n_options"] = n_opt
    out["n_modes"] = (n > 0).sum(1).astype(np.int8)
    out["pop_catchment"] = pop_catch
    out["options_per_1000"] = np.divide(1000 * n_opt, pop_catch, out=np.zeros(nc), where=pop_catch > 0)
    out["access_2sfca"] = a2
    served = n_opt > 0
    lo = C.SCORE_MIN_SERVED
    for col, src in (("score_2sfca", a2), ("score_options", n_opt)):
        s = np.zeros(nc)
        if served.any():
            s[served] = lo + (100 - lo) * weighted_rank(src[served], np.maximum(ind[served], 1e-9))
        out[col] = s.round(2)
    out["score"] = out["score_options" if C.SCORE_BASIS == "n_options" else "score_2sfca"]
    for k, m in enumerate(MODES):
        out[f"served_{m}"] = n[:, k] > 0
    out["privacy_ok"] = men >= C.PRIVACY_MIN_HOUSEHOLDS

    st = offer.copy()
    st["pop_served"] = pop_served
    st["pop_served_exclusive"] = pop_excl
    st["households_served"] = hh_served
    st["privacy_ok"] = hh_served >= C.PRIVACY_MIN_HOUSEHOLDS
    return out, st


# --------------------------------------------------------------------------- agrégats
def commune_table(ca):
    ind = ca["ind"].to_numpy()
    df = pd.DataFrame({
        "com": ca["com"], "dep": ca["dep"], "territory": ca["territory"], "ind": ind, "men": ca["men"],
        "pop_served": ind * (ca["n_options"] > 0), "w_opt": ind * ca["n_options"],
        "w_2sfca": ind * ca["access_2sfca"], "w_score": ind * ca["score"],
    })
    g = df.groupby("com")
    res = pd.DataFrame({
        "dep": g["dep"].first(), "territory": g["territory"].first(),
        "population": g["ind"].sum(), "households": g["men"].sum(), "n_cells": g.size(),
    })
    res["share_pop_served"] = g["pop_served"].sum() / res["population"]
    res["n_options_mean"] = g["w_opt"].sum() / res["population"]
    res["access_2sfca_mean"] = g["w_2sfca"].sum() / res["population"]
    res["score_mean"] = g["w_score"].sum() / res["population"]
    # médiane pondérée population du score
    tmp = ca[["com", "score", "ind"]].sort_values(["com", "score"])
    tmp["cw"] = tmp.groupby("com")["ind"].cumsum()
    tmp["half"] = tmp.groupby("com")["ind"].transform("sum") / 2
    res["score_median"] = tmp[tmp.cw >= tmp.half].groupby("com")["score"].first()
    for m in MODES:
        res[f"share_served_{m}"] = (ca["ind"] * ca[f"served_{m}"]).groupby(ca["com"]).sum() / res["population"]
    res["privacy_ok"] = res["households"] >= C.PRIVACY_MIN_HOUSEHOLDS
    try:
        names = pd.DataFrame(json.loads((C.RAW / "communes.json").read_text()))[["code", "nom"]]
        res = res.join(names.set_index("code")["nom"])
    except Exception:  # noqa: BLE001 – nom de commune facultatif
        res["nom"] = None
    return res.reset_index()


def summary(ca, st, radius, offer_path, seconds):
    ind = ca["ind"].to_numpy()
    tot = ind.sum()
    none = ca["n_options"].to_numpy() == 0

    def block(mask):
        p = ind[mask]
        sub = ca[mask]
        return {
            "population": float(p.sum()),
            "share_no_option": float(p[none[mask]].sum() / p.sum()),
            "share_served_by_mode": {m: float((p * sub[f"served_{m}"]).sum() / p.sum()) for m in MODES},
            "n_options_mean": float(np.average(sub["n_options"], weights=p)),
            "n_modes_mean": float(np.average(sub["n_modes"], weights=p)),
            "score_mean": float(np.average(sub["score"], weights=p)),
            "score_2sfca_mean": float(np.average(sub["score_2sfca"], weights=p)),
        }

    out = {"radius_m": radius, "score_basis": C.SCORE_BASIS, "detour": geo.detour_factor(), "offer_file": str(offer_path),
           "population": float(tot), "n_cells": int(len(ca)), "national": block(np.ones(len(ca), bool)),
           "by_territory": {t: block((ca["territory"] == t).to_numpy()) for t in ca["territory"].unique()}}
    # déciles de revenu : niveau de vie moyen du carreau, déciles pondérés population (national)
    inc = ca["income_pc"].to_numpy()
    ok = np.isfinite(inc)
    r = weighted_rank(inc[ok], ind[ok])
    dec = np.full(len(ca), -1)
    dec[ok] = np.minimum((r * 10).astype(int), 9) + 1
    out["by_income_decile"] = {}
    for d in range(1, 11):
        m = dec == d
        b = block(m)
        b["income_pc_range"] = [float(inc[m].min()), float(inc[m].max())]
        out["by_income_decile"][str(d)] = b
    out["offer"] = {
        m: {"n_points": int((st["mode"] == m).sum()),
            "n_points_in_territories": int(((st["mode"] == m) & (st["crs_id"] >= 0)).sum()),
            "pop_served_median": float(st.loc[st["mode"] == m, "pop_served"].median()),
            "share_points_serving_nobody": float((st.loc[st["mode"] == m, "pop_served"] == 0).mean())}
        for m in MODES if (st["mode"] == m).any()}
    out["seconds"] = round(seconds, 1)
    return out


def build(offer_path=C.INTERIM / "offer.parquet"):
    t0 = time.time()
    radius = geo.walk_radius_m()
    print(f"Rayon 5 min : {radius:.0f} m euclidiens (détour {geo.detour_factor():.3f})", flush=True)
    cells = pd.read_parquet(C.INTERIM / "cells.parquet", columns=CELL_COLS)
    offer = pd.read_parquet(offer_path)
    offer = offer[offer["mode"].isin(MODES)].reset_index(drop=True)
    print(f"  {len(cells):,} carreaux, {len(offer):,} points d'offre ({offer_path.name})", flush=True)
    ca, st = compute(cells, offer, radius)
    print(f"  calcul : {time.time() - t0:.0f} s", flush=True)
    ca.to_parquet(C.OUT / "cells_access.parquet", index=False)
    st.to_parquet(C.OUT / "stations_served.parquet", index=False)
    commune_table(ca).to_parquet(C.OUT / "commune_access.parquet", index=False)
    s = summary(ca, st, radius, offer_path, time.time() - t0)
    (C.OUT / "access_summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))
    nat = s["national"]
    print(f"  population sans option à 5 min : {nat['share_no_option']:.1%}")
    for m, v in nat["share_served_by_mode"].items():
        print(f"    desservie {m:10s} : {v:.1%}")
    for d, v in s["by_income_decile"].items():
        print(f"    décile {d:>2} : sans option {v['share_no_option']:.1%}, score moyen {v['score_mean']:.1f}")
    print(f"  -> outputs/cells_access.parquet, stations_served.parquet, commune_access.parquet, "
          f"access_summary.json ({time.time() - t0:.0f} s)")
    return ca, st


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--offer", type=Path, default=C.INTERIM / "offer.parquet",
                    help="fichier d'offre (défaut data/interim/offer.parquet ; ex. offer_stub.parquet)")
    build(ap.parse_args().offer)
