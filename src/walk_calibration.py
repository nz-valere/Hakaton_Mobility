"""
Étape 3b – Calibration du « rayon 5 minutes » sur le réseau piéton OSM (Eurométropole de Strasbourg).

Question : l'indicateur compte les options de transport à ≤ 5 min de marche, soit
400 m *de réseau* (C.WALK_NETWORK_M). Pour tourner à l'échelle nationale (2,3 M carreaux)
on approxime l'isochrone réseau par un cercle euclidien de rayon r = 400 / détour.
Ce module estime ce détour sur données réelles et mesure l'erreur de l'approximation.

Méthode
-------
1. Graphe piéton : nœuds OSM (lon/lat -> EPSG:3035), arêtes = segments consécutifs des
   ways piétonnables (requête Overpass dans data/raw/overpass_query.txt), poids = longueur
   projetée (m). On garde la plus grande composante connexe.
2. Origines : N carreaux habités de la zone tirés au hasard *pondérés par la population*
   (seed C.RANDOM_STATE), rattachés au nœud le plus proche (≤ C.CALIB_SNAP_MAX_M).
   On mesure donc le détour « vu des habitants », pas celui des champs ou des zones d'activité.
3. Dijkstra borné (scipy.sparse.csgraph.dijkstra, limit) depuis chaque origine.
4. Trois estimateurs du rayon équivalent, IC 95 % par bootstrap sur les origines
   (les paires d'une même origine sont corrélées : on rééchantillonne les origines) :
   a. ratio médian réseau / vol d'oiseau pour les nœuds à 200-600 m  ->  r = 400 / médiane ;
   b. frontière à 50 % : r tel que P(réseau ≤ 400 m | vol d'oiseau = r) = 0,5 ;
   c. **égalité des effectifs (retenu)** : r tel que le cercle de rayon r contienne autant de
      nœuds que l'isochrone réseau de 400 m (somme sur les origines). C'est le critère qui rend
      le *comptage* non biaisé : les faux positifs du cercle (points proches mais derrière une
      voie ferrée) compensent ses faux négatifs. Or notre indicateur est un comptage
      (nb d'options, nb d'habitants servis) : c'est le critère pertinent.
   Le détour retenu = 400 / r_c.
5. Validation (bonus) : pour chaque carreau habité de la zone (marge de 1 km aux bords) et
   les arrêts/stations réels (offer.parquet si disponible, sinon arrêts GTFS CTS), on calcule
   la vraie distance réseau (Dijkstra depuis chaque point d'offre + distances de rattachement)
   et on compare au cercle : précision / rappel pondérés par la population de « desservi
   (≥ 1 point) », et biais sur le nombre de points comptés.

Sorties : outputs/walk_calibration.json, outputs/figures/walk_detour.png
"""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

D_NET = C.WALK_NETWORK_M  # 400 m


# --------------------------------------------------------------------------- graphe
def load_graph(path=C.RAW / "osm_walk_strasbourg.json"):
    """Graphe piéton non orienté : (xy des nœuds [n,2], matrice CSR des longueurs)."""
    el = json.loads(Path(path).read_text(encoding="utf-8"))["elements"]
    nodes = [(e["id"], e["lon"], e["lat"]) for e in el if e["type"] == "node"]
    ids = np.array([n[0] for n in nodes], dtype=np.int64)
    lon = np.array([n[1] for n in nodes])
    lat = np.array([n[2] for n in nodes])
    order = np.argsort(ids)
    ids, lon, lat = ids[order], lon[order], lat[order]
    _, x, y = geo.project(lon, lat, np.zeros(len(ids), np.int8))
    xy = np.c_[x, y]

    a, b = [], []
    for e in el:
        if e["type"] == "way" and len(e.get("nodes", [])) > 1:
            nd = np.asarray(e["nodes"], dtype=np.int64)
            a.append(nd[:-1])
            b.append(nd[1:])
    a, b = np.concatenate(a), np.concatenate(b)
    ia, ib = np.searchsorted(ids, a), np.searchsorted(ids, b)
    ok = (ia < len(ids)) & (ib < len(ids))
    ok &= (ids[np.minimum(ia, len(ids) - 1)] == a) & (ids[np.minimum(ib, len(ids) - 1)] == b)
    ok &= ia != ib
    ia, ib = ia[ok], ib[ok]
    w = np.hypot(*(xy[ia] - xy[ib]).T)
    w = np.maximum(w, 1e-3)                       # un poids nul = « pas d'arête » en CSR
    n = len(ids)
    g = sparse.coo_matrix((np.r_[w, w], (np.r_[ia, ib], np.r_[ib, ia])), shape=(n, n))
    g = _min_duplicates(g)

    _, lab = connected_components(g, directed=False)
    keep = lab == np.bincount(lab).argmax()
    idx = np.flatnonzero(keep)
    g = g[idx][:, idx].tocsr()
    return xy[idx], g


def _min_duplicates(coo):
    """CSR en gardant le poids minimal pour les arêtes en double (ways superposés)."""
    key = coo.row.astype(np.int64) * coo.shape[0] + coo.col
    order = np.lexsort((coo.data, key))
    key, data = key[order], coo.data[order]
    first = np.r_[True, key[1:] != key[:-1]]
    k = key[first]
    return sparse.csr_matrix((data[first], (k // coo.shape[0], k % coo.shape[0])), shape=coo.shape)


def strasbourg_cells(margin_m=0.0):
    """Carreaux habités de l'emprise d'étude (métropole), avec option de marge intérieure."""
    w, s, e, n = C.STRASBOURG_BBOX
    cells = pd.read_parquet(C.INTERIM / "cells.parquet",
                            columns=["key", "crs_id", "x", "y", "lon", "lat", "ind", "men"])
    m = (cells.crs_id == 0) & cells.lon.between(w, e) & cells.lat.between(s, n) & (cells.ind > 0)
    c = cells[m].reset_index(drop=True)
    if margin_m > 0:
        x0, x1, y0, y1 = c.x.min(), c.x.max(), c.y.min(), c.y.max()
        c = c[c.x.between(x0 + margin_m, x1 - margin_m) & c.y.between(y0 + margin_m, y1 - margin_m)]
    return c.reset_index(drop=True)


# --------------------------------------------------------------------------- calibration
def sample_pairs(xy, g, cells, n_origins, rng):
    """
    Pour N origines (nœuds rattachés à des carreaux tirés ∝ population) : listes par origine
    des distances euclidiennes et réseau vers tous les nœuds à ≤ limite euclidienne.
    """
    tree = cKDTree(xy)
    dsnap, node = tree.query(np.c_[cells.x, cells.y])
    ok = dsnap <= C.CALIB_SNAP_MAX_M
    p = cells.ind.values * ok
    pick = rng.choice(len(cells), size=n_origins, replace=False, p=p / p.sum())
    origins = np.unique(node[pick])
    lim = C.CALIB_DIJKSTRA_LIMIT_M
    out = []
    for k in range(0, len(origins), 64):
        o = origins[k:k + 64]
        dist = dijkstra(g, directed=False, indices=o, limit=lim)
        for r, oi in enumerate(o):
            nb = np.asarray(tree.query_ball_point(xy[oi], lim * 0.9), dtype=int)
            nb = nb[nb != oi]
            de = np.hypot(*(xy[nb] - xy[oi]).T)
            out.append((de, dist[r, nb]))       # inf = non atteint dans la limite
    return out


# Résumés par origine (histogrammes) : le bootstrap ne manipule que des poids d'origines.
R_EDGES = np.arange(0, 1201, 1.0)            # pas de 1 m pour les distances euclidiennes
B_EDGES = np.arange(150, 651, 10.0)          # paliers de 10 m pour la frontière à 50 %
Q_EDGES = np.arange(1.0, 5.0005, 0.001)    # ratios réseau / vol d'oiseau (≥ 5 et non atteints -> 5)


def summarize(per_origin):
    """Matrices (origines × classes) : effectifs nécessaires aux trois estimateurs."""
    lo, hi = C.CALIB_DIST_BAND
    H_e, H_bin, H_bin_in, H_q, n_net, s_ratio, n_ratio = [], [], [], [], [], [], []
    for de, dn in per_origin:
        H_e.append(np.histogram(de, R_EDGES)[0])
        H_bin.append(np.histogram(de, B_EDGES)[0])
        H_bin_in.append(np.histogram(de[dn <= D_NET], B_EDGES)[0])
        band = (de >= lo) & (de <= hi)
        q = np.maximum(dn[band] / de[band], 1.0)
        H_q.append(np.histogram(np.minimum(q, 4.9995), Q_EDGES)[0])
        n_net.append(np.sum(dn <= D_NET))
        fin = np.isfinite(q)
        s_ratio.append(q[fin].sum())
        n_ratio.append(fin.sum())
    S = {k: np.asarray(v, float) for k, v in dict(H_e=H_e, H_bin=H_bin, H_bin_in=H_bin_in, H_q=H_q,
                                                   n_net=n_net, s_ratio=s_ratio, n_ratio=n_ratio).items()}
    S["ratio"] = np.concatenate([np.maximum(dn / de, 1.0)[(de >= lo) & (de <= hi)]
                                 for de, dn in per_origin])
    return S


def estimators(S, w=None):
    """Les trois estimateurs du rayon équivalent (cf. docstring) ; w = poids des origines."""
    w = np.ones(len(S["n_net"])) if w is None else w
    hq = w @ S["H_q"]
    cq = np.cumsum(hq)
    med = float(Q_EDGES[np.searchsorted(cq, cq[-1] / 2)])
    mean = float(w @ S["s_ratio"] / (w @ S["n_ratio"]))
    # b. frontière 50 %
    pin = (w @ S["H_bin_in"]) / np.maximum(w @ S["H_bin"], 1)
    mids = (B_EDGES[:-1] + B_EDGES[1:]) / 2
    j = np.flatnonzero((pin[:-1] >= 0.5) & (pin[1:] < 0.5))
    if len(j):
        j = j[0]
        r_b = mids[j] + (pin[j] - 0.5) / (pin[j] - pin[j + 1]) * (mids[j + 1] - mids[j])
    else:
        r_b = np.nan
    # c. égalité des effectifs : Σ_o #{euclid ≤ r} = Σ_o #{réseau ≤ 400}
    ce = np.cumsum(w @ S["H_e"])
    r_c = float(R_EDGES[1:][np.searchsorted(ce, w @ S["n_net"])])
    return {"median": med, "mean": mean, "r_median": D_NET / med, "r_boundary50": float(r_b),
            "r_equal_count": r_c, "p_in_curve": (mids, pin)}


def bootstrap(S, n_boot, rng):
    """IC 95 % par rééchantillonnage des origines (poids multinomiaux)."""
    keys = ["median", "mean", "r_median", "r_boundary50", "r_equal_count"]
    res = {k: [] for k in keys}
    n = len(S["n_net"])
    for _ in range(n_boot):
        e = estimators(S, np.bincount(rng.integers(0, n, n), minlength=n).astype(float))
        for k in keys:
            res[k].append(e[k])
    return {k: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))] for k, v in res.items()}


# --------------------------------------------------------------------------- validation
def load_points():
    """Points d'offre de l'emprise : offer.parquet si présent, sinon arrêts GTFS CTS."""
    w, s, e, n = C.STRASBOURG_BBOX
    f = C.INTERIM / "offer.parquet"
    if f.exists():
        o = pd.read_parquet(f, columns=["lon", "lat", "mode"])
        src = "offer.parquet"
    else:
        st = pd.read_csv(io.BytesIO(zipfile.ZipFile(C.RAW / "gtfs_cts.zip").read("stops.txt")))
        if "location_type" in st:
            st = st[st.location_type.fillna(0) == 0]
        o = pd.DataFrame({"lon": st.stop_lon, "lat": st.stop_lat, "mode": "transit"})
        src = "gtfs_cts stops.txt"
    o = o[o.lon.between(w, e) & o.lat.between(s, n)].reset_index(drop=True)
    _, o["x"], o["y"] = geo.project(o.lon.values, o.lat.values, np.zeros(len(o), np.int8))
    return o, src


def validate(xy, g, radii):
    """Compare l'isochrone réseau 400 m et le cercle euclidien (carreaux × points d'offre)."""
    cells = strasbourg_cells(margin_m=1000)
    pts, src = load_points()
    tree = cKDTree(xy)
    dc, nc = tree.query(np.c_[cells.x, cells.y])
    dp, npt = tree.query(np.c_[pts.x, pts.y])
    pts = pts[dp <= C.CALIB_SNAP_MAX_M].reset_index(drop=True)
    npt, dp = npt[dp <= C.CALIB_SNAP_MAX_M], dp[dp <= C.CALIB_SNAP_MAX_M]
    # distance réseau carreau -> point = rattachement carreau + réseau + rattachement point
    rows, cols = [], []
    for k in range(0, len(pts), 256):
        sl = slice(k, k + 256)
        dist = dijkstra(g, directed=False, indices=npt[sl], limit=D_NET)
        tot = dist[:, nc] + dc[None, :] + dp[sl, None]
        r, c = np.nonzero(tot <= D_NET)
        rows.append(r + k)
        cols.append(c)
    ci = np.concatenate(cols)
    n_net = np.bincount(ci, minlength=len(cells))
    pop = cells.ind.values
    ctree = cKDTree(np.c_[cells.x, cells.y])
    ptree = cKDTree(np.c_[pts.x, pts.y])
    out = {"points_source": src, "n_points": int(len(pts)), "n_cells": int(len(cells)),
           "population": float(pop.sum()),
           "pop_share_served_network": float(pop[n_net > 0].sum() / pop.sum()), "by_radius": {}}
    for name, r in radii.items():
        n_circ = np.array([len(v) for v in ctree.query_ball_tree(ptree, r)])
        a, b = n_circ > 0, n_net > 0
        tp = pop[a & b].sum()
        out["by_radius"][name] = {
            "radius_m": float(r),
            "pop_share_served_circle": float(pop[a].sum() / pop.sum()),
            "precision_pop": float(tp / pop[a].sum()),
            "recall_pop": float(tp / pop[b].sum()),
            "accuracy_pop": float(pop[a == b].sum() / pop.sum()),
            # biais de comptage : Σ_pop n_cercle / Σ_pop n_réseau (1 = sans biais)
            "count_ratio_pop": float((pop * n_circ).sum() / (pop * n_net).sum()),
            "count_mae": float(np.average(np.abs(n_circ - n_net), weights=pop)),
            "count_spearman": float(pd.Series(n_circ).corr(pd.Series(n_net), method="spearman")),
        }
    return out


# --------------------------------------------------------------------------- figure
def figure(est, r_keep, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, c1, c2 = "#0b0b0b", "#52514e", "#2a78d6", "#eb6834"
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), facecolor="#fcfcfb")
    r = est["ratio"]
    r = r[np.isfinite(r)]
    ax[0].hist(np.clip(r, 1, 3), bins=80, color=c1, edgecolor="#fcfcfb", linewidth=0.5)
    ax[0].axvline(est["median"], color=c2, lw=2)
    ax[0].text(est["median"] + 0.03, ax[0].get_ylim()[1] * 0.9,
               f"médiane {est['median']:.2f}", color=ink)
    ax[0].set_xlabel("distance réseau / distance à vol d'oiseau (paires à 200-600 m, tronqué à 3)")
    ax[0].set_ylabel("nombre de paires")
    ax[0].set_title("Coefficient de détour piéton – Strasbourg (OSM)", color=ink, loc="left")
    mids, pin = est["p_in_curve"]
    ax[1].plot(mids, pin, color=c1, lw=2)
    ax[1].axhline(0.5, color=muted, lw=0.8, ls=":")
    ax[1].axvline(r_keep, color=c2, lw=2)
    ax[1].text(r_keep + 8, 0.85, f"rayon retenu {r_keep:.0f} m", color=ink)
    ax[1].set_xlabel("distance à vol d'oiseau (m)")
    ax[1].set_ylabel("P(≤ 400 m de réseau)")
    ax[1].set_title("Part des points réellement à 5 min de marche", color=ink, loc="left")
    for a in ax:
        a.set_facecolor("#fcfcfb")
        a.grid(alpha=0.25)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        a.tick_params(colors=muted)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build():
    t0 = time.time()
    rng = np.random.default_rng(C.RANDOM_STATE)
    print("Graphe piéton OSM…")
    xy, g = load_graph()
    print(f"  {g.shape[0]:,} nœuds, {g.nnz // 2:,} arêtes (plus grande composante)")
    cells = strasbourg_cells()
    per_origin = sample_pairs(xy, g, cells, C.CALIB_N_ORIGINS, rng)
    S = summarize(per_origin)
    est = estimators(S)
    est["ratio"] = S["ratio"]
    ci = bootstrap(S, C.CALIB_BOOTSTRAP, rng)
    r_keep = est["r_equal_count"]
    detour = D_NET / r_keep
    print(f"  ratio médian {est['median']:.3f}, moyen {est['mean']:.3f} ; rayons : "
          f"400/médiane {est['r_median']:.0f} m, frontière 50 % {est['r_boundary50']:.0f} m, "
          f"effectifs égaux {r_keep:.0f} m -> détour {detour:.3f}")
    print("Validation cercle vs réseau…")
    val = validate(xy, g, {"retenu": r_keep, "defaut_1.30": D_NET / C.DEFAULT_DETOUR,
                           "400m_sans_detour": D_NET, "400_sur_mediane": est["r_median"]})
    for k, v in val["by_radius"].items():
        print(f"  {k:18s} r={v['radius_m']:.0f} m  précision {v['precision_pop']:.3f}  "
              f"rappel {v['recall_pop']:.3f}  biais comptage {v['count_ratio_pop']:.3f}")
    n_pairs = int(len(est["ratio"]))
    res = {
        "detour": round(float(detour), 4),
        "radius_m": round(float(r_keep), 1),
        "n_pairs": n_pairs,
        "n_origins": len(per_origin),
        "method": ("égalité des effectifs : rayon euclidien r tel que le cercle contienne autant de "
                   "nœuds du graphe piéton OSM que l'isochrone réseau de 400 m, cumulé sur des "
                   "origines tirées ∝ population ; détour = 400 / r"),
        "network_m": D_NET,
        "ratio_median": est["median"], "ratio_mean": est["mean"],
        "radius_400_over_median": est["r_median"],
        "radius_boundary50": est["r_boundary50"],
        "radius_equal_count": est["r_equal_count"],
        "ci95": ci,
        "detour_ci95": [D_NET / ci["r_equal_count"][1], D_NET / ci["r_equal_count"][0]],
        "dist_band_m": list(C.CALIB_DIST_BAND),
        "graph": {"nodes": int(g.shape[0]), "edges": int(g.nnz // 2), "source": "osm_walk_strasbourg.json"},
        "validation": val,
        "seconds": round(time.time() - t0, 1),
    }
    out = C.OUT / "walk_calibration.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    figure(est, r_keep, C.FIG / "walk_detour.png")
    print(f"  -> {out} ({res['seconds']} s)")
    return res


if __name__ == "__main__":
    build()
