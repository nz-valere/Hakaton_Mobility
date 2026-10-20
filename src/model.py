"""
Étape 5 – Modèle de « valeur d'un site » : où un équipement (station Citiz / autopartage,
station vélo, arrêt de bus) a-t-il le plus de chances d'être utile ?

Idée : l'offre existante révèle la demande. Les opérateurs (Citiz, réseaux vélo, réseaux
de bus) implantent leurs points là où l'usage est suffisant ; on apprend donc, à partir des
caractéristiques du bassin de chaque carreau habité, la probabilité qu'il soit desservi par
le type d'équipement considéré. Appliquée à un carreau NON desservi, cette probabilité
mesure à quel point il « ressemble » aux sites qui fonctionnent : c'est la valeur du site.

Unité d'observation : carreau habité 200 m (cells.parquet), avec des variables de bassin
    - à 5 min de marche (3×3 carreaux ≈ rayon geo.walk_radius_m()) : population, ménages,
    - dans des fenêtres de contexte de demi-côté 1 km et 3 km : population (densité),
      revenu, pauvreté, structure par âge, logement collectif / social, propriétaires…,
    - commune : population, distance au centre, motorisation (RP 2021), croissance Omphale,
    - offre des AUTRES modes : nb de points à 5 min, à 1 km, distance au plus proche.
  Les modes cibles du type (C.KIND_EXCLUDED_FEATURE_MODES) sont exclus des variables
  (sinon fuite triviale : « il y a une station à côté »).

Cible y = au moins un point du mode cible à ≤ walk_radius_m() du centre du carreau.
Problème positive-unlabeled (PU) : un carreau sans station n'est pas forcément un mauvais
site, il peut simplement être hors du périmètre d'un opérateur. On n'apprend donc que dans
les communes où le réseau opère (≥ 1 carreau desservi par ce mode) : là, l'absence est
informative (l'opérateur aurait pu s'y implanter). Il reste un biais PU résiduel (sites
pas encore équipés). Sous l'hypothèse SCAR (Elkan & Noto 2008), p(desservi|x) = c·p(bon|x)
et le classement serait inchangé ; mais SCAR est violée par construction (ce sont les
opérateurs qui choisissent les sites, selon x : le modèle apprend « ressembler aux sites
choisis », biais des choix passés inclus). Si la probabilité d'équipement croît avec la
qualité du site, le classement est préservé mais la propension est écrasée en haut et en
bas ; sinon (stratégie d'opérateur, ancienneté du réseau, contrats) il ne l'est pas. On
n'utilise donc la propension qu'en relatif (p / p_ref), comme un score de ressemblance.
La restriction aux communes équipées conditionne en outre sur l'issue au niveau commune :
dans les petites communes (≥ 1 carreau desservi par définition), le taux de positifs est
gonflé (Citiz : 12 % pour 30-100 carreaux vs 6 % pour 100-300).
Les candidats d'une zone d'étude étant des négatifs de l'apprentissage, la recommandation
les score HORS PLI (modèles par pli départemental, predict_value(oof=True, dep=...)).
Cible secondaire (autopartage, vélo) : capacité installée à 5 min (véhicules / bornes),
proxy de l'intensité d'usage puisque l'opérateur ajoute des voitures là où la demande l'exige.

Évaluation : validation croisée SPATIALE GroupKFold (groupe = département ≈ réseau /
agglomération) pour éviter la fuite par autocorrélation spatiale ; HistGradientBoosting vs
régression logistique vs heuristique « population seule » ; ROC-AUC, PR-AUC, Brier,
calibration ; Spearman / MAE pour la capacité ; importance par permutation.

Sorties : outputs/model_metrics.json, outputs/model_<kind>.joblib, outputs/figures/model_*.png,
cache outputs/cache/features_cells.parquet. Interface : build_features(), predict_value().
"""
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

CACHE = C.OUT / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
FEAT_CACHE = CACHE / "features_cells.parquet"
OFFER_STUB = C.INTERIM / "offer_stub.parquet"
MODES = list(C.MODES)
DIST_CAP = 20_000.0          # distance plafond (m) quand aucun point n'existe à proximité

# variables socio-démographiques moyennées sur les fenêtres de contexte (colonne, poids)
CONTEXT_MEANS = {
    "income_pc": "ind", "poverty_rate": "men", "share_18_39": "ind", "share_65p": "ind",
    "share_kids": "ind", "share_1ind": "men", "share_coll": "men", "share_soc": "men",
    "share_owner": "men",
}
CELL_COLS = ["key", "crs_id", "x", "y", "lon", "lat", "com", "dep", "ind", "men", "pop_future",
             "growth", "carfree_share", "multicar_share"] + list(CONTEXT_MEANS)


# --------------------------------------------------------------------------- données
def load_cells(columns=None, filters=None):
    return pd.read_parquet(C.INTERIM / "cells.parquet", columns=columns or CELL_COLS,
                           filters=filters)


def build_offer_stub():
    """
    Offre provisoire (si data/interim/offer.parquet n'existe pas encore) au schéma de
    CONTRACTS.md : GBFS France (Citiz = systèmes « Citiz » en voiture, carsharing = autres
    systèmes voiture, bike = systèmes vélo, scooter = trottinette seule) + arrêts GTFS
    nationaux (location_type 0, tous classés `transit`, dédoublonnés à ~20 m).
    """
    rows = []
    for s in json.loads((C.RAW / "gbfs_france.json").read_text(encoding="utf-8")):
        if not s.get("ok") or not s.get("stations"):
            continue
        ff = set(s.get("form_factors") or [])
        if "car" in ff:
            mode = "citiz" if "citiz" in s["name"].lower() else "carsharing"
        elif "bicycle" in ff:
            mode = "bike"
        elif ff & {"scooter", "scooter_standing"}:
            mode = "scooter"
        else:
            continue
        for st in s["stations"]:
            if st.get("lat") is None or st.get("lon") is None:
                continue
            rows.append((f"{mode}:{s['system_id']}:{st.get('station_id')}", mode, st.get("name", ""),
                         float(st["lon"]), float(st["lat"]), s["name"], s["name"],
                         float(st["capacity"]) if st.get("capacity") is not None else np.nan))
    gb = pd.DataFrame(rows, columns=["offer_id", "mode", "name", "lon", "lat", "source", "operator",
                                     "capacity"])
    st = pd.read_csv(C.RAW / "arrets_france.csv",
                     usecols=["dataset_custom_title", "stop_id", "stop_name", "stop_lat", "stop_lon",
                              "location_type", "agency_name"])
    st = st[(st["location_type"] == 0) & st["stop_lat"].notna()]
    st = st.assign(r_lon=(st["stop_lon"] / 2.5e-4).round(), r_lat=(st["stop_lat"] / 2e-4).round())
    st = st.drop_duplicates(["r_lon", "r_lat"])
    tr = pd.DataFrame({
        "offer_id": "transit:" + st["dataset_custom_title"].astype(str) + ":" + st["stop_id"].astype(str),
        "mode": "transit", "name": st["stop_name"].astype(str), "lon": st["stop_lon"], "lat": st["stop_lat"],
        "source": st["dataset_custom_title"].astype(str), "operator": st["agency_name"].astype(str),
        "capacity": np.nan})
    off = pd.concat([gb, tr], ignore_index=True).drop_duplicates("offer_id")
    off["crs_id"], off["x"], off["y"] = geo.project(off["lon"].values, off["lat"].values)
    off.to_parquet(OFFER_STUB, index=False)
    print(f"  stub d'offre : {len(off):,} points -> {OFFER_STUB}\n{off['mode'].value_counts().to_string()}")
    return off


def load_offer():
    """Offre réelle (étape 3) si disponible, sinon stub construit depuis les fichiers bruts."""
    f = C.INTERIM / "offer.parquet"
    if f.exists():   # la signature (date de modification) invalide les caches si l'offre change
        return pd.read_parquet(f), f"offer.parquet@{int(f.stat().st_mtime)}"
    if OFFER_STUB.exists():
        return pd.read_parquet(OFFER_STUB), "offer_stub.parquet"
    return build_offer_stub(), "offer_stub.parquet"


def load_communes():
    """Communes (geo.api.gouv.fr) : nom, population, centre (lon/lat) indexés par code INSEE."""
    js = json.loads((C.RAW / "communes.json").read_text(encoding="utf-8"))
    df = pd.DataFrame({
        "com": [c["code"] for c in js], "com_name": [c["nom"] for c in js],
        "com_lon": [c["centre"]["coordinates"][0] if c.get("centre") else np.nan for c in js],
        "com_lat": [c["centre"]["coordinates"][1] if c.get("centre") else np.nan for c in js]})
    return df.set_index("com")


# --------------------------------------------------------------------------- sommes sur grille
def _grid_box_sums(src_crs, src_x, src_y, W, q_crs, q_x, q_y, halves):
    """
    Somme, autour de chaque point requête, des poids W (n_src × m) des sources situées dans
    le carré de demi-côté h·200 m (h ∈ halves, en nombre de carreaux), via rastérisation sur
    la grille INSEE 200 m + filtre uniforme (O(N), indépendant du rayon).
    Renvoie {h: np.ndarray (n_q × m)}.
    """
    W = np.asarray(W, float).reshape(len(src_x), -1)
    out = {h: np.zeros((len(q_x), W.shape[1])) for h in halves}
    src_crs, q_crs = np.asarray(src_crs), np.asarray(q_crs)
    hmax = max(halves)
    for cid in geo.EPSG:
        si, qi = np.flatnonzero(src_crs == cid), np.flatnonzero(q_crs == cid)
        if len(si) == 0 or len(qi) == 0:
            continue
        sx = np.floor(np.asarray(src_x)[si] / C.CELL).astype(np.int64)
        sy = np.floor(np.asarray(src_y)[si] / C.CELL).astype(np.int64)
        qx = np.floor(np.asarray(q_x)[qi] / C.CELL).astype(np.int64)
        qy = np.floor(np.asarray(q_y)[qi] / C.CELL).astype(np.int64)
        x0, y0 = min(sx.min(), qx.min()) - hmax, min(sy.min(), qy.min()) - hmax
        nx, ny = max(sx.max(), qx.max()) - x0 + hmax + 1, max(sy.max(), qy.max()) - y0 + hmax + 1
        for k in range(W.shape[1]):
            grid = np.zeros((ny, nx))
            np.add.at(grid, (sy - y0, sx - x0), W[si, k])
            for h in halves:
                size = 2 * h + 1
                f = ndimage.uniform_filter(grid, size=size, mode="constant") * size * size
                out[h][qi, k] = f[qy - y0, qx - x0]
            del grid
    for h in halves:
        out[h][np.abs(out[h]) < 1e-9] = 0.0
    return out


# --------------------------------------------------------------------------- variables
def build_features(cells_df, offer_df, query_df=None, communes=None):
    """
    Variables explicatives pour chaque point de `query_df` (défaut : les carreaux eux-mêmes ;
    sinon tout DataFrame avec crs_id, x, y, com — ex. points candidats). Les sommes de bassin
    utilisent tous les carreaux de `cells_df` (prévoir une marge autour de la zone).
    Toutes les colonnes d'offre (n_<mode>_r5, n_<mode>_1k, d_<mode>, cap_<mode>_r5) sont
    calculées ; feature_columns(kind) choisit celles autorisées pour chaque modèle.
    """
    t0 = time.time()
    q = cells_df if query_df is None else query_df
    r = geo.walk_radius_m()
    h5 = max(1, int(r // C.CELL))                           # 308 m -> 3×3 carreaux
    hk = [int(round(m / C.CELL)) for m in C.MODEL_CONTEXT_HALF_M]
    F = pd.DataFrame(index=q.index)

    # --- population et moyennes socio-démographiques (pondérées) sur les fenêtres
    ind = cells_df["ind"].fillna(0).values
    men = cells_df["men"].fillna(0).values
    cols = [ind, men]
    for c, wcol in CONTEXT_MEANS.items():
        w = ind if wcol == "ind" else men
        v = cells_df[c].values
        ok = np.isfinite(v)
        cols += [np.where(ok, v * w, 0.0), np.where(ok, w, 0.0)]
    S = _grid_box_sums(cells_df["crs_id"].values, cells_df["x"].values, cells_df["y"].values,
                       np.column_stack(cols), q["crs_id"].values, q["x"].values, q["y"].values,
                       [h5] + hk)
    F["pop_r5"] = S[h5][:, 0]
    F["men_r5"] = S[h5][:, 1]
    for h, m in zip(hk, C.MODEL_CONTEXT_HALF_M):
        area_km2 = ((2 * h + 1) * C.CELL / 1000) ** 2
        F[f"dens_{m // 1000}k"] = S[h][:, 0] / area_km2       # hab/km²
    h1 = hk[0]
    for i, c in enumerate(CONTEXT_MEANS):
        num, den = S[h1][:, 2 + 2 * i], S[h1][:, 3 + 2 * i]
        F[f"{c}_1k"] = np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)

    # --- variables communales (motorisation RP au niveau commune, croissance Omphale)
    for c in ("carfree_share", "multicar_share", "growth"):
        F[c] = q[c].values if c in q else np.nan
    com_pop = cells_df.groupby("com")["ind"].sum()
    F["log_com_pop"] = np.log1p(q["com"].map(com_pop).fillna(0).values)
    communes = load_communes() if communes is None else communes
    cc = communes.reindex(q["com"].values)
    _, cx, cy = geo.project(cc["com_lon"].values, cc["com_lat"].values, q["crs_id"].values)
    F["d_com_centre"] = np.minimum(np.hypot(q["x"].values - cx, q["y"].values - cy), DIST_CAP)

    # --- offre par mode : nb de points à 5 min (exact), à ~1 km (carré), distance au plus proche
    for m in MODES:
        o = offer_df[(offer_df["mode"] == m) & (offer_df["crs_id"] >= 0)]
        if len(o) == 0:
            F[f"n_{m}_r5"] = 0.0
            F[f"n_{m}_1k"] = 0.0
            F[f"cap_{m}_r5"] = 0.0
            F[f"d_{m}"] = DIST_CAP
            continue
        I, J = geo.pairs_within(q["crs_id"].values, q["x"].values, q["y"].values,
                                o["crs_id"].values, o["x"].values, o["y"].values, r)
        F[f"n_{m}_r5"] = np.bincount(I, minlength=len(q)).astype(float)
        cap = np.nan_to_num(o["capacity"].values.astype(float), nan=1.0)
        F[f"cap_{m}_r5"] = np.bincount(I, weights=cap[J], minlength=len(q))
        Sk = _grid_box_sums(o["crs_id"].values, o["x"].values, o["y"].values, np.ones(len(o)),
                            q["crs_id"].values, q["x"].values, q["y"].values, [h1])
        F[f"n_{m}_1k"] = Sk[h1][:, 0]
        F[f"d_{m}"] = np.minimum(geo.nearest(q["crs_id"].values, q["x"].values, q["y"].values,
                                             o["crs_id"].values, o["x"].values, o["y"].values,
                                             max_dist=DIST_CAP), DIST_CAP)
    F["n_options_r5"] = sum(F[f"n_{m}_r5"] * C.MODE_WEIGHT[m] for m in MODES)
    print(f"  features : {len(F):,} points × {F.shape[1]} colonnes en {time.time() - t0:.1f} s")
    return F.astype("float32")


def feature_columns(kind):
    """Variables autorisées pour le modèle `kind` (les modes cibles sont exclus)."""
    excl = set(C.KIND_EXCLUDED_FEATURE_MODES[kind])
    base = ["pop_r5", "men_r5"] + [f"dens_{m // 1000}k" for m in C.MODEL_CONTEXT_HALF_M] \
        + [f"{c}_1k" for c in CONTEXT_MEANS] \
        + ["carfree_share", "multicar_share", "log_com_pop", "d_com_centre"]
    # NB : `growth` (Omphale) est constant par département = identifiant du groupe de CV ;
    # il est exclu des variables (il n'apprendrait que des effets départementaux).
    for m in MODES:
        if m not in excl:
            base += [f"n_{m}_r5", f"n_{m}_1k", f"d_{m}"]
    return base


def target(F, kind):
    """y = au moins un point des modes cibles à 5 min ; capacité installée correspondante."""
    modes = C.KIND_TARGET_MODES[kind]
    n = sum(F[f"n_{m}_r5"] for m in modes)
    cap = sum(F[f"cap_{m}_r5"] for m in modes)
    return (n > 0).values, cap.values


# --------------------------------------------------------------------------- modèles
def _hgb_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(random_state=C.RANDOM_STATE, **C.MODEL_HGB)


def _signed_log1p(X):
    return np.sign(X) * np.log1p(np.abs(X))


def _logit():
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler
    # log1p sur les comptes / populations / distances (toutes >= 0) puis standardisation
    return make_pipeline(SimpleImputer(strategy="median"),
                         FunctionTransformer(_signed_log1p),
                         StandardScaler(), LogisticRegression(max_iter=500, C=1.0))


def _clf_metrics(y, p):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, np.clip(p, 0, 1)))}


def training_set(F, cells, kind):
    """Carreaux des communes où le réseau du type opère (cadre PU, cf. docstring)."""
    y, cap = target(F, kind)
    com_pos = pd.Series(y, index=cells["com"].values).groupby(level=0).any()
    elig = cells["com"].map(com_pos).fillna(False).values.astype(bool)
    return elig, y, cap


def _fold_permutation_importance(fold_models, X, y, cols, rng):
    """
    Baisse de PR-AUC quand on permute une variable (ou un groupe de variables, permutées avec
    la même permutation), moyennée sur les plis : chaque modèle de pli est évalué sur son pli
    de test (≤ C.MODEL_PERM_SAMPLE lignes), C.MODEL_PERM_REPEATS répétitions.
    """
    from sklearn.metrics import average_precision_score
    targets = [(c, [i]) for i, c in enumerate(cols)]
    targets += [(g, [cols.index(c) for c in cs]) for g, cs in C.MODEL_PERM_GROUPS.items()
                if all(c in cols for c in cs)]
    acc = {name: [] for name, _ in targets}
    for model, te in fold_models:
        sub = te if len(te) <= C.MODEL_PERM_SAMPLE else rng.choice(te, C.MODEL_PERM_SAMPLE, replace=False)
        Xs, ys = X[sub].copy(), y[sub]
        if ys.min() == ys.max():
            continue
        base = average_precision_score(ys, model.predict_proba(Xs)[:, 1])
        for name, ii in targets:
            drops = []
            for _ in range(C.MODEL_PERM_REPEATS):
                Xp = Xs.copy()
                perm = rng.permutation(len(ys))
                Xp[:, ii] = Xs[perm][:, ii]
                drops.append(base - average_precision_score(ys, model.predict_proba(Xp)[:, 1]))
            acc[name].append(float(np.mean(drops)))
    mean = {k: float(np.mean(v)) for k, v in acc.items() if v}
    single = dict(sorted(((c, mean[c]) for c in cols if c in mean), key=lambda t: -t[1]))
    groups = {g: mean[g] for g in C.MODEL_PERM_GROUPS if g in mean}
    return single, groups


def _within_dep_backtest(y, p, pop, groups, min_pos=10):
    """
    Par département (prédictions hors pli) : PR-AUC, ROC-AUC et précision@k (k = nb de carreaux
    réellement desservis) du modèle vs du classement par population à 5 min. Résumé : nb de
    départements où le modèle bat la population, moyennes simples et pondérées par k.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score
    rows = []
    for d in np.unique(groups):
        m = groups == d
        k = int(y[m].sum())
        if k < min_pos or k == m.sum():
            continue
        ym, pm, qm = y[m], p[m], pop[m].astype(float)
        prec = {}
        for name, s in (("model", pm), ("pop", qm)):
            o = np.lexsort((np.arange(len(s)), -s))          # tri décroissant, ex aequo stables
            prec[name] = float(ym[o[:k]].mean())
        rows.append({"dep": str(d), "n": int(m.sum()), "k": k,
                     "ap_model": float(average_precision_score(ym, pm)),
                     "ap_pop": float(average_precision_score(ym, qm)),
                     "auc_model": float(roc_auc_score(ym, pm)), "auc_pop": float(roc_auc_score(ym, qm)),
                     "prec_k_model": prec["model"], "prec_k_pop": prec["pop"]})
    R = pd.DataFrame(rows)
    if R.empty:
        return {}
    out = {"n_deps": int(len(R)), "model_beats_pop_ap": int((R["ap_model"] > R["ap_pop"]).sum()),
           "model_beats_pop_prec_k": int((R["prec_k_model"] > R["prec_k_pop"]).sum())}
    for c in ("ap_model", "ap_pop", "auc_model", "auc_pop", "prec_k_model", "prec_k_pop"):
        out[f"mean_{c}"] = float(R[c].mean())
        out[f"wmean_{c}"] = float(np.average(R[c], weights=R["k"]))
    out["by_dep"] = {r["dep"]: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
                                if k != "dep"} for r in rows if r["dep"] in ("67", "54")}
    return out


def evaluate_kind(F, cells, kind, rng):
    """CV spatiale GroupKFold (département) : HGB vs logistique vs population seule."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupKFold

    elig, y_all, cap_all = training_set(F, cells, kind)
    idx = np.flatnonzero(elig)
    if len(idx) > C.MODEL_MAX_TRAIN:
        idx = np.sort(rng.choice(idx, C.MODEL_MAX_TRAIN, replace=False))
    cols = feature_columns(kind)
    X = F.iloc[idx][cols].values
    y = y_all[idx]
    groups = cells["dep"].values[idx]
    n_groups = len(np.unique(groups))
    k = min(C.MODEL_CV_FOLDS, n_groups)
    print(f"[{kind}] {len(idx):,} carreaux d'apprentissage ({elig.sum():,} éligibles, "
          f"{y.mean():.1%} positifs), {n_groups} départements, {k} plis")
    oof = {"hgb": np.zeros(len(idx)), "logit": np.zeros(len(idx)), "pop_only": np.zeros(len(idx))}
    folds = {m: [] for m in oof}
    pop = F.iloc[idx]["pop_r5"].values
    fold_models = []
    for f, (tr, te) in enumerate(GroupKFold(n_splits=k).split(X, y, groups)):
        if y[tr].min() == y[tr].max() or y[te].min() == y[te].max():
            continue
        hgb = _hgb_clf().fit(X[tr], y[tr])
        oof["hgb"][te] = hgb.predict_proba(X[te])[:, 1]
        lr = _logit().fit(X[tr], y[tr])
        oof["logit"][te] = lr.predict_proba(X[te])[:, 1]
        # heuristique « population seule » : rang de la population à 5 min, calibrée par
        # régression isotone apprise sur le pli d'apprentissage (pour un Brier comparable)
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(out_of_bounds="clip").fit(pop[tr], y[tr])
        oof["pop_only"][te] = iso.predict(pop[te])
        for m in oof:
            folds[m].append(_clf_metrics(y[te], oof[m][te]))
        fold_models.append((hgb, te))
        print(f"   pli {f}: AUC hgb {folds['hgb'][-1]['roc_auc']:.3f} | logit "
              f"{folds['logit'][-1]['roc_auc']:.3f} | pop {folds['pop_only'][-1]['roc_auc']:.3f}")

    res = {"n_train": int(len(idx)), "n_eligible": int(elig.sum()), "positive_rate": float(y.mean()),
           "n_departements": int(n_groups), "folds": k, "features": cols, "models": {}}
    for m in oof:
        df = pd.DataFrame(folds[m])
        res["models"][m] = {"pooled": _clf_metrics(y, oof[m]),
                            "fold_mean": df.mean().to_dict(), "fold_std": df.std().to_dict()}

    # sélection du modèle sur ces mêmes plis : 2 candidats seulement, hyperparamètres fixés a
    # priori (C.MODEL_HGB, non réglés sur ces plis) -> optimisme de sélection faible ; l'écart
    # hgb/logit est à lire avec fold_std.
    res["selection_note"] = ("modèle retenu = meilleure PR-AUC agrégée parmi {hgb, logit} sur les "
                             "mêmes plis ; hyperparamètres fixés a priori")

    # importance par permutation : moyenne sur TOUS les plis (modèle HGB de chaque pli, sur son
    # pli de test), variables seules + groupes colinéaires permutés ensemble (C.MODEL_PERM_GROUPS)
    res["permutation_importance"], res["permutation_importance_groups"] = \
        _fold_permutation_importance(fold_models, X, y, cols, rng)

    # backtest intra-département : dans chaque département tenu à l'écart, le modèle classe-t-il
    # les carreaux réellement desservis mieux que la population seule ? (c'est la question que
    # pose la recommandation, qui compare des sites DANS une même zone)
    res["within_dep_backtest"] = {m: _within_dep_backtest(y, oof[m], pop, groups)
                                  for m in ("hgb", "logit")}

    # cible secondaire : capacité installée (véhicules / bornes) parmi les carreaux desservis
    pos = y_all[idx]
    cap = cap_all[idx]
    has_cap = pos & np.isfinite(cap) & (cap > 0)
    if kind in ("citiz", "bike") and has_cap.sum() > 500:
        ii = np.flatnonzero(has_cap)
        yc = np.log1p(cap[ii])
        pred = np.zeros(len(ii))
        for tr, te in GroupKFold(n_splits=min(k, len(np.unique(groups[ii])))).split(ii, yc, groups[ii]):
            reg = HistGradientBoostingRegressor(random_state=C.RANDOM_STATE, max_iter=200,
                                                min_samples_leaf=50).fit(X[ii][tr], yc[tr])
            pred[te] = reg.predict(X[ii][te])
        res["capacity"] = {
            "n": int(len(ii)),
            "spearman_hgb": float(spearmanr(pred, yc).correlation),
            "spearman_pop_only": float(spearmanr(pop[ii], yc).correlation),
            "mae_hgb": float(np.mean(np.abs(np.expm1(pred) - cap[ii]))),
            # NB : malgré son nom (conservé pour app.py), baseline = MÉDIANE globale constante
            "mae_mean_baseline": float(np.mean(np.abs(np.median(cap[ii]) - cap[ii]))),
            "baseline": "médiane constante",
            "unit": "véhicules" if kind == "citiz" else "places / vélos"}
    return res, y, oof


def fit_final(F, cells, kind, rng, algo="hgb"):
    """
    Modèle final sur toutes les communes éligibles ; `algo` = meilleur modèle en CV spatiale
    (PR-AUC agrégée).

    Prédiction HORS PLI pour la recommandation : les carreaux non desservis d'une zone étudiée
    (ex. EMS) sont des NÉGATIFS de l'apprentissage ; le modèle complet a appris à leur donner
    une propension basse (fuite PU classique). On entraîne donc aussi un modèle par pli
    GroupKFold départemental : chaque département est scoré par le modèle qui ne l'a pas vu
    (predict_value(..., oof=True, dep=...)). p_ref = médiane HORS PLI des propensions des
    carreaux desservis (même échelle que les candidats scorés hors pli) ; p_ref_insample =
    médiane in-sample du modèle complet (à n'utiliser qu'avec oof=False).
    """
    from sklearn.model_selection import GroupKFold
    elig, y_all, _ = training_set(F, cells, kind)
    idx = np.flatnonzero(elig)
    if len(idx) > C.MODEL_FINAL_MAX_TRAIN:
        idx = np.sort(rng.choice(idx, C.MODEL_FINAL_MAX_TRAIN, replace=False))
    cols = feature_columns(kind)
    X, y = F.iloc[idx][cols].values, y_all[idx]
    make = _hgb_clf if algo == "hgb" else _logit
    model = make().fit(X, y)
    p_in = model.predict_proba(X)[:, 1]
    deps = cells["dep"].values[idx].astype(str)
    fold_models, dep_fold, p_oof = [], {}, np.full(len(idx), np.nan)
    for f, (tr, te) in enumerate(GroupKFold(n_splits=min(C.MODEL_CV_FOLDS, len(np.unique(deps))))
                                 .split(X, y, deps)):
        mf = make().fit(X[tr], y[tr])
        fold_models.append(mf)
        p_oof[te] = mf.predict_proba(X[te])[:, 1]
        dep_fold.update({d: f for d in np.unique(deps[te])})
    bundle = {"kind": kind, "algo": algo, "model": model, "features": cols,
              "fold_models": fold_models, "dep_fold": dep_fold,
              "p_ref": float(np.median(p_oof[y])), "p_ref_insample": float(np.median(p_in[y])),
              "trained_on": int(len(idx))}
    if kind == "citiz":
        # pénétration nationale : adhérents Citiz / habitants à 5 min d'une station Citiz
        pop_citiz = float(cells["ind"].values[F["n_citiz_r5"].values > 0].sum())
        bundle["pop_served_citiz_fr"] = pop_citiz
        bundle["penetration"] = C.CITIZ_DRIVERS_FR / max(pop_citiz, 1.0)
    joblib.dump(bundle, C.OUT / f"model_{kind}.joblib")
    return bundle


_BUNDLES = {}


def load_bundle(kind):
    if kind not in _BUNDLES:
        _BUNDLES[kind] = joblib.load(C.OUT / f"model_{kind}.joblib")
    return _BUNDLES[kind]


def predict_value(features_df, kind, oof=False, dep=None):
    """
    Propension p(site de type `kind` | variables) ∈ [0,1] pour chaque ligne de build_features().

    oof=False (défaut, rétrocompatible) : modèle complet ; à comparer à b["p_ref_insample"].
    oof=True : chaque ligne est scorée par le modèle de pli qui n'a PAS vu son département
    (un département absent de l'apprentissage -> modèle complet) ; à comparer à b["p_ref"].
    `dep` : code(s) département des lignes (scalaire ou tableau aligné), sinon colonne "dep"
    de features_df ; obligatoire avec oof=True.
    """
    b = load_bundle(kind)
    X = features_df[b["features"]].values.astype(float)
    if not oof:
        return b["model"].predict_proba(X)[:, 1]
    if "fold_models" not in b:
        raise ValueError(f"bundle {kind} sans modèles de pli : relancer python -m src.model")
    if dep is None:
        if "dep" not in features_df:
            raise ValueError("predict_value(oof=True) exige dep=... (codes département des lignes)")
        dep = features_df["dep"].values
    dep = np.broadcast_to(np.asarray(dep, dtype=object).astype(str), (len(X),))
    fold = pd.Series(dep).map(b["dep_fold"]).fillna(-1).astype(int).values
    out = np.empty(len(X))
    for f in np.unique(fold):
        m = fold == f
        mdl = b["model"] if f < 0 else b["fold_models"][f]
        out[m] = mdl.predict_proba(X[m])[:, 1]
    return out


# --------------------------------------------------------------------------- figures
COLORS = {"hgb": "#2a78d6", "logit": "#eb6834", "pop_only": "#1baf7a"}
LABELS = {"hgb": "Gradient boosting", "logit": "Régression logistique", "pop_only": "Population seule"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax, title, xl, yl):
    ax.set_facecolor(SURF)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_xlabel(xl, color=INK2)
    ax.set_ylabel(yl, color=INK2)
    ax.grid(color=GRID, lw=0.8)
    ax.tick_params(colors=INK2)
    for s in ax.spines.values():
        s.set_visible(False)


def plot_kind(kind, y, oof, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import precision_recall_curve, roc_curve

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), facecolor=SURF)
    for m, p in oof.items():
        met = res["models"][m]["pooled"]
        fpr, tpr, _ = roc_curve(y, p)
        axes[0].plot(fpr, tpr, color=COLORS[m], lw=2, label=f"{LABELS[m]} (AUC {met['roc_auc']:.2f})")
        pr, rc, _ = precision_recall_curve(y, p)
        axes[1].plot(rc, pr, color=COLORS[m], lw=2, label=f"{LABELS[m]} (AP {met['pr_auc']:.2f})")
        fp, mp = calibration_curve(y, np.clip(p, 0, 1), n_bins=10, strategy="quantile")
        axes[2].plot(mp, fp, color=COLORS[m], lw=2, marker="o", ms=5, label=LABELS[m])
    axes[0].plot([0, 1], [0, 1], color=INK2, lw=1, ls="--")
    axes[2].plot([0, 1], [0, 1], color=INK2, lw=1, ls="--")
    _style(axes[0], "ROC (CV spatiale par département)", "Taux de faux positifs", "Taux de vrais positifs")
    _style(axes[1], "Précision-rappel", "Rappel", "Précision")
    _style(axes[2], "Calibration (déciles)", "Probabilité prédite", "Fréquence observée")
    for ax in axes:
        ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    fig.suptitle(f"Modèle « {kind} » – {res['n_train']:,} carreaux, {res['n_departements']} départements",
                 x=0.01, ha="left", color=INK)
    fig.tight_layout()
    fig.savefig(C.FIG / f"model_{kind}_curves.png", dpi=130)
    plt.close(fig)

    imp = pd.Series(res["permutation_importance"]).head(15)[::-1]
    fig, ax = plt.subplots(figsize=(7, 5), facecolor=SURF)
    ax.barh(imp.index, imp.values, color=COLORS["hgb"], height=0.6)
    _style(ax, f"Importance par permutation – {kind} (baisse de PR-AUC)", "Δ PR-AUC", "")
    fig.tight_layout()
    fig.savefig(C.FIG / f"model_{kind}_importance.png", dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- pipeline
def cached_features(force=False):
    """Variables de tous les carreaux de France (cache disque)."""
    cells = load_cells()
    offer, src = load_offer()
    if FEAT_CACHE.exists() and not force:
        meta = json.loads((CACHE / "features_meta.json").read_text(encoding="utf-8"))
        if meta == {"offer_source": src, "n": len(cells), "radius": geo.walk_radius_m()}:
            return cells, pd.read_parquet(FEAT_CACHE), src
    F = build_features(cells, offer)
    F.to_parquet(FEAT_CACHE, index=False)
    (CACHE / "features_meta.json").write_text(json.dumps({"offer_source": src, "n": len(cells),
                                                             "radius": geo.walk_radius_m()}), encoding="utf-8")
    return cells, F, src


def _oof_diagnostics(F, cells, kind, b, deps=("67", "54")):
    """
    Effet de la fuite PU sur les candidats des zones d'étude : propensions in-sample vs hors pli
    des carreaux habités NON desservis du département, et part des candidats saturés
    (p/p_ref ≥ borne haute de C.VALUE_CLIP) dans chaque cas.
    """
    _BUNDLES[kind] = b
    y, _ = target(F, kind)
    hi = C.VALUE_CLIP[1]
    out = {}
    for d in deps:
        m = (cells["dep"].values == d) & ~y & (cells["ind"].values > 0)
        if m.sum() == 0:
            continue
        Fd = F[m]
        p_in = predict_value(Fd, kind)
        p_oof = predict_value(Fd, kind, oof=True, dep=d)
        out[d] = {"n_candidates": int(m.sum()),
                  "median_p_insample": float(np.median(p_in)), "median_p_oof": float(np.median(p_oof)),
                  "mean_p_insample": float(p_in.mean()), "mean_p_oof": float(p_oof.mean()),
                  "spearman_in_vs_oof": float(spearmanr(p_in, p_oof).correlation),
                  "share_saturated_insample": float((p_in / b["p_ref_insample"] >= hi).mean()),
                  "share_saturated_oof": float((p_oof / b["p_ref"] >= hi).mean())}
    return out


def main(force=False):
    t0 = time.time()
    cells, F, src = cached_features(force)
    print(f"offre utilisée : {src} ; {len(cells):,} carreaux")
    rng = np.random.default_rng(C.RANDOM_STATE)
    metrics = {"offer_source": src, "walk_radius_m": geo.walk_radius_m(), "cv": "GroupKFold par département",
               "pu_note": "apprentissage restreint aux communes où le réseau du type opère (positive-unlabeled)",
               "kinds": {}}
    for kind in C.MODEL_KINDS:
        res, y, oof = evaluate_kind(F, cells, kind, rng)
        plot_kind(kind, y, oof, res)
        algo = max(("hgb", "logit"), key=lambda m: res["models"][m]["pooled"]["pr_auc"])
        b = fit_final(F, cells, kind, rng, algo)
        res["selected_model"] = algo
        res["p_ref"] = b["p_ref"]
        res["p_ref_insample"] = b["p_ref_insample"]
        res["oof_vs_insample"] = _oof_diagnostics(F, cells, kind, b)
        if "penetration" in b:
            res["citiz_penetration"] = b["penetration"]
            res["pop_served_citiz_fr"] = b["pop_served_citiz_fr"]
        metrics["kinds"][kind] = res
    metrics["runtime_s"] = round(time.time() - t0, 1)
    (C.OUT / "model_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {C.OUT / 'model_metrics.json'} ({metrics['runtime_s']} s)")
    return metrics


if __name__ == "__main__":
    # exécuter via le module importé pour que les objets picklés référencent `src.model`
    # (et non `__main__`), sinon joblib.load échoue depuis recommend.py / app.py
    from src import model as _m
    _m.main(force="--force" in sys.argv)
