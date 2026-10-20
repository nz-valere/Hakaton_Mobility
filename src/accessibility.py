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
Sensibilité à l'IC 95 % du rayon (278-286 m) : part sans option 36,5 % / 35,6 % (vs 36,0 %),
n_options moyen −2,5 % / +2,6 % (access_summary.json -> radius_sensitivity).

Indicateurs par carreau i (voisinage V(i) = points / carreaux à ≤ r du centre de i)
-----------------------------------------------------------------------------------
- n_<mode>       = nombre de points d'offre du mode dans V(i) ; exception, le free-floating (scooter) :
                   nombre d'OPÉRATEURS distincts ayant au moins une zone dans V(i) si
                   C.FREEFLOAT_COUNT_BY_OPERATOR (défaut). Les zones GBFS free-floating sont des places
                   virtuelles (Paris : 31 zones à 5 min en moyenne, 78 % de n_options) : les compter une à
                   une mesure le maillage du stationnement, pas le nombre de services utilisables ;
- n_options      = Σ_mode C.MODE_WEIGHT[mode] · n_<mode> (poids 1 par défaut : « nombre d'options ») ;
- n_modes        = nombre de modes distincts accessibles (diversité) ;
- served_<mode>  = n_<mode> > 0 ;
- pop_catchment  = habitants à ≤ r du centre de i : Σ_k f_ik · ind_k, f_ik = part de la surface du
                   carreau k à ≤ r (population uniforme dans le carreau ; geo.cell_offsets_fraction).
                   Un critère « centre de k à ≤ r » serait instable : r ≈ 282 m ≈ diagonale du carreau
                   (282,8 m), soit 5 carreaux à 282 m et 9 à 283 m (+68 % de pop_catchment) ;
- options_per_1000 = 1000 · n_options / pop_catchment : offre par habitant, version simple ;
- access_2sfca   = Two-Step Floating Catchment Area (Luo & Wang 2003), mesure standard de
                   « l'offre par habitant » en accessibilité : étape 1, chaque point j reçoit un
                   ratio R_j = w_j / P_j où P_j = habitants à ≤ r de j ; étape 2, A_i = 1000 · Σ_{j∈V(i)} R_j
                   (options pour 1000 habitants, concurrence entre habitants prise en compte point par
                   point). Propriété : Σ_i ind_i · A_i = 1000 · Σ_j w_j (l'offre est intégralement répartie
                   entre ses usagers potentiels ; points ne desservant personne exclus). Ici chaque zone
                   free-floating reste une unité d'offre ;
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
                   « chaud » et le centre de Strasbourg « froid » (score moyen pondéré des carreaux
                   desservis, access_summary.json -> score_by_group_served : densité à ~1 km
                   < C.LOW_DENSITY_HAB_KM2 : 64 en 2SFCA contre 31 en n_options ; commune de
                   Strasbourg : 30 contre 63). Les deux scores sont peu concordants (Spearman pondéré
                   0,21, score_concordance) : le choix de lecture n'est pas neutre. Leurs moyennes
                   nationales sont en revanche égales PAR CONSTRUCTION (rang moyen 0,5 × part desservie).
                   Sans fréquence ni capacité par arrêt, diviser par la population pénalise la
                   densité au lieu de mesurer la saturation. access_2sfca reste exporté pour la
                   lecture « concurrence » et pour l'analyse de sensibilité.

Indicateurs par point d'offre j
-------------------------------
pop_served = Σ ind des carreaux dont le centre est à ≤ r (échantillonnage au centre : sans biais en
moyenne pour des points non alignés sur la grille) ; households_served = Σ men ; pop_served_exclusive =
habitants des carreaux pour lesquels j est le seul point de son mode à ≤ r (perte nette si le point
fermait ; pour le free-floating, seule zone, tous opérateurs confondus).

Résumé (access_summary.json) : national, territoires, EMS ; courbe par décile national de revenu
(tous carreaux, carreaux ≥ 11 ménages — 77 % des carreaux ont un revenu imputé par l'INSEE —, EMS) ;
scores par groupe de densité ; concordance des deux scores ; parts autopartage homogènes ;
sensibilité aux bornes de l'IC 95 % du rayon ; statistiques des points d'offre limitées aux
territoires couverts par Filosofi (crs_id ≥ 0).

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
def _grid_lookup(keys, offsets):
    """Pour chaque décalage (dl, dc) : (i, k) tels que le carreau k = carreau i + (dl, dc)."""
    order = np.argsort(keys)
    sk = keys[order]
    for dl, dc in offsets:
        target = keys + int(dl) * 10**6 + int(dc)
        pos = np.minimum(np.searchsorted(sk, target), len(sk) - 1)
        ok = sk[pos] == target
        yield np.flatnonzero(ok), order[pos[ok]]


def cell_neighbours(cells, radius):
    """
    Paires (i, k) de carreaux voisins et poids f = part de la surface de k à ≤ radius du centre
    de i (geo.cell_offsets_fraction ; f = 1 pour i = k). Les carreaux sont sur une grille exacte
    de 200 m : on énumère les décalages (dl, dc) et on retrouve les voisins par leur clé
    (population.cell_key), sans KD-tree. La fraction évite l'effet de seuil d'un critère
    « centre à ≤ r » quand r ≈ 282 m ≈ diagonale du carreau (5 ou 9 carreaux à 1 m près).
    """
    dl, dc, f = geo.cell_offsets_fraction(radius)
    I, K, W = [], [], []
    for (i, k), w in zip(_grid_lookup(cells["key"].to_numpy(), zip(dl, dc)), f):
        I.append(i)
        K.append(k)
        W.append(np.full(len(i), w))
    return np.concatenate(I), np.concatenate(K), np.concatenate(W)


def grid_box_sum(cells, values, half):
    """Σ values sur le carré de (2·half+1)² carreaux centré sur chaque carreau."""
    out = np.zeros(len(cells))
    offs = [(a, b) for a in range(-half, half + 1) for b in range(-half, half + 1)]
    for i, k in _grid_lookup(cells["key"].to_numpy(), offs):
        out[i] += values[k]
    return out


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
    n_raw = np.bincount(ci * nm + mode_code[oj], minlength=nc * nm).reshape(nc, nm).astype(np.int32)
    n = n_raw.copy()
    if C.FREEFLOAT_COUNT_BY_OPERATOR and "scooter" in MODES and "operator" in offer.columns:
        # free-floating : une option = un opérateur distinct à ≤ r (pas une zone de stationnement)
        k_sc = MODES.index("scooter")
        op = pd.factorize(offer["operator"].astype(str))[0].astype(np.int64)
        sc = mode_code[oj] == k_sc
        cell_op = np.unique(ci[sc].astype(np.int64) * (op.max() + 1) + op[oj[sc]])
        n[:, k_sc] = np.bincount(cell_op // (op.max() + 1), minlength=nc)

    # population à ≤ r de chaque carreau (grille, couverture fractionnaire des voisins)
    a, b, f = cell_neighbours(cells, radius)
    pop_catch = np.bincount(a, weights=ind[b] * f, minlength=nc)

    # par point d'offre (exclusivité : point seul de son mode à ≤ r, zones free-floating comprises)
    pop_served = np.bincount(oj, weights=ind[ci], minlength=no)
    hh_served = np.bincount(oj, weights=men[ci], minlength=no)
    excl = n_raw[ci, mode_code[oj]] == 1
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
        names = pd.DataFrame(json.loads((C.RAW / "communes.json").read_text(encoding="utf-8")))[["code", "nom"]]
        res = res.join(names.set_index("code")["nom"])
    except Exception:  # noqa: BLE001 – nom de commune facultatif
        res["nom"] = None
    return res.reset_index()


def summary(ca, st, radius, offer_path, seconds, sensitivity=None):
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
           "freefloat_count_by_operator": bool(C.FREEFLOAT_COUNT_BY_OPERATOR),
           "population": float(tot), "n_cells": int(len(ca)), "national": block(np.ones(len(ca), bool)),
           "by_territory": {t: block((ca["territory"] == t).to_numpy()) for t in ca["territory"].unique()}}
    lon, lat = ca["lon"].to_numpy(), ca["lat"].to_numpy()
    w_, s_, e_, n_ = C.STRASBOURG_BBOX
    ems = ((ca["dep"] == C.STRASBOURG_DEPT).to_numpy() & (lon >= w_) & (lon <= e_) & (lat >= s_) & (lat <= n_))
    out["ems"] = block(ems)

    # déciles de revenu : niveau de vie moyen du carreau, déciles pondérés population (national).
    # Attention : 77 % des carreaux (< 11 ménages) ont des variables Filosofi imputées par l'INSEE ;
    # on publie donc aussi la courbe restreinte aux carreaux ≥ 11 ménages (seuils nationaux) et
    # la courbe de l'EMS (seuils nationaux, puis seuils propres à la zone).
    inc = ca["income_pc"].to_numpy()
    ok = np.isfinite(inc)

    def deciles(mask):
        dec = np.full(len(ca), -1)
        mk = ok & mask
        r = weighted_rank(inc[mk], ind[mk])
        dec[mk] = np.minimum((r * 10).astype(int), 9) + 1
        return dec

    dec_nat = deciles(np.ones(len(ca), bool))
    thr = [float(inc[dec_nat == d].max()) for d in range(1, 10)]

    def curve(dec, mask, full=False):
        res = {}
        for d in range(1, 11):
            m = (dec == d) & mask
            if not m.any():
                continue
            b = block(m)
            b["income_pc_range"] = [float(inc[m].min()), float(inc[m].max())]
            res[str(d)] = b if full else {k: b[k] for k in ("population", "share_no_option", "n_options_mean",
                                                             "score_mean", "income_pc_range")}
        return res

    priv = ca["privacy_ok"].to_numpy() if "privacy_ok" in ca else ca["men"].to_numpy() >= C.PRIVACY_MIN_HOUSEHOLDS
    out["by_income_decile"] = curve(dec_nat, np.ones(len(ca), bool), full=True)
    out["income_decile_thresholds"] = thr
    out["by_income_decile_privacy_ok"] = curve(dec_nat, priv)
    out["ems_by_income_decile_national"] = curve(dec_nat, ems)
    out["ems_by_income_decile_local"] = curve(deciles(ems), ems)

    # densité locale (≈ dens_1k du modèle : carré de 11 × 11 carreaux, hab/km²) et score par densité
    dens = grid_box_sum(ca, ind, 5) / (11 * C.CELL / 1000) ** 2
    served = ca["n_options"].to_numpy() > 0

    def wmean(col, m):
        return float(np.average(ca[col].to_numpy()[m], weights=ind[m])) if m.any() else None

    groups = {"strasbourg_commune": (ca["com"] == "67482").to_numpy(), "ems": ems,
              f"dens_lt_{C.LOW_DENSITY_HAB_KM2}": dens < C.LOW_DENSITY_HAB_KM2,
              f"dens_ge_{C.LOW_DENSITY_HAB_KM2}": dens >= C.LOW_DENSITY_HAB_KM2,
              "paris": ca["com"].astype(str).str.startswith("751").to_numpy()}
    out["score_by_group_served"] = {
        g: {"population_served": float(ind[m & served].sum()),
            "score_options_mean": wmean("score_options", m & served),
            "score_2sfca_mean": wmean("score_2sfca", m & served),
            "n_options_mean": wmean("n_options", m & served)} for g, m in groups.items()}

    # concordance des deux scores (les moyennes sont égales par construction : rang moyen 0,5 ×
    # part desservie) : corrélation de rang pondérée et matrice de transition par quintile
    so, s2, wv = ca["score_options"].to_numpy()[served], ca["score_2sfca"].to_numpy()[served], ind[served]
    ro, r2 = weighted_rank(so, wv), weighted_rank(s2, wv)
    cov = np.cov(ro, r2, aweights=wv)
    q_o = np.minimum((ro * 5).astype(int), 4)
    q_2 = np.minimum((r2 * 5).astype(int), 4)
    trans = np.zeros((5, 5))
    np.add.at(trans, (q_o, q_2), wv)
    out["score_concordance"] = {
        "weighted_spearman": float(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])),
        "quintile_transition_rows_options_cols_2sfca": (trans / trans.sum(1, keepdims=True)).round(3).tolist(),
        "share_same_quintile": float(np.trace(trans) / trans.sum()),
        "note": "moyennes nationales de score_options et score_2sfca égales par construction"}

    # autopartage : parts homogènes (Citiz seul / Citiz + autre autopartage), national et EMS
    cs = (ca["served_citiz"] | ca["served_carsharing"]).to_numpy()
    out["carsharing_served_share"] = {
        z: {"citiz": float(ind[m & ca["served_citiz"].to_numpy()].sum() / ind[m].sum()),
            "citiz_or_carsharing": float(ind[m & cs].sum() / ind[m].sum())}
        for z, m in (("national", np.ones(len(ca), bool)), ("ems", ems))}

    # points d'offre : statistiques sur les territoires couverts par Filosofi (crs_id ≥ 0) ; les
    # points hors carreaux (Guadeloupe, Guyane, Mayotte, étranger) ont pop_served = 0 par construction
    sti = st[st["crs_id"] >= 0]
    out["offer"] = {
        m: {"n_points": int((st["mode"] == m).sum()),
            "n_points_in_territories": int((sti["mode"] == m).sum()),
            "pop_served_median": float(sti.loc[sti["mode"] == m, "pop_served"].median()),
            "pop_served_exclusive_median": float(sti.loc[sti["mode"] == m, "pop_served_exclusive"].median()),
            "share_points_serving_nobody": float((sti.loc[sti["mode"] == m, "pop_served"] == 0).mean())}
        for m in MODES if (sti["mode"] == m).any()}
    if sensitivity:
        out["radius_sensitivity"] = sensitivity
    out["seconds"] = round(seconds, 1)
    return out


def radius_sensitivity(cells, offer, radii):
    """Indicateurs nationaux clés recalculés pour d'autres rayons (bornes de l'IC 95 % du détour)."""
    ind = cells["ind"].to_numpy()
    res = {}
    for r in radii:
        ca, st = compute(cells, offer, r)
        sti = st[st["crs_id"] >= 0]
        res[f"{r:.1f}"] = {
            "share_no_option": float(ind[ca["n_options"].to_numpy() == 0].sum() / ind.sum()),
            "n_options_mean": float(np.average(ca["n_options"], weights=ind)),
            "pop_catchment_mean": float(np.average(ca["pop_catchment"], weights=ind)),
            "share_served_citiz": float(np.average(ca["served_citiz"], weights=ind)),
            "pop_served_median": {m: float(v) for m, v in sti.groupby("mode")["pop_served"].median().items()},
        }
    return res


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
    sens = None
    f_cal = C.OUT / "walk_calibration.json"
    if f_cal.exists():
        lo, hi = json.loads(f_cal.read_text(encoding="utf-8"))["ci95"]["r_equal_count"]
        print(f"  sensibilité au rayon : {lo:.0f} / {hi:.0f} m", flush=True)
        sens = radius_sensitivity(cells, offer, [lo, radius, hi])
    s = summary(ca, st, radius, offer_path, time.time() - t0, sens)
    (C.OUT / "access_summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
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
