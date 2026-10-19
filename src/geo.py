"""
Outils géographiques partagés : projection dans le CRS des carreaux INSEE,
rayon de marche « 5 minutes » et requêtes de voisinage (KD-tree par territoire).

Les carreaux Filosofi sont dans 3 CRS métriques (cf. population.CRS_ID) :
    0 = Métropole (EPSG:3035), 1 = Martinique (EPSG:5490), 2 = La Réunion (EPSG:2975).
Tout point d'offre est projeté dans le CRS du territoire où il se trouve ; les points
hors de ces territoires (Guadeloupe, Guyane, Mayotte, étranger) reçoivent crs_id = -1
et sont ignorés dans les calculs d'accessibilité (pas de carreaux de population).
"""
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

EPSG = {0: 3035, 1: 5490, 2: 2975}
# emprises lon/lat grossières (ouest, sud, est, nord)
BBOX = {
    0: (-5.5, 41.2, 10.0, 51.3),      # métropole + Corse
    1: (-61.3, 14.3, -60.7, 14.95),   # Martinique
    2: (55.1, -21.5, 55.9, -20.8),    # La Réunion
}
_TF = {cid: Transformer.from_crs(4326, epsg, always_xy=True) for cid, epsg in EPSG.items()}
_TF_INV = {cid: Transformer.from_crs(epsg, 4326, always_xy=True) for cid, epsg in EPSG.items()}


def territory_of(lon, lat):
    """crs_id (0/1/2) de chaque point, -1 si hors des territoires couverts par Filosofi."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    out = np.full(lon.shape, -1, dtype=np.int8)
    for cid, (w, s, e, n) in BBOX.items():
        out[(lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)] = cid
    return out


def project(lon, lat, crs_id=None):
    """(lon, lat) -> (crs_id, x, y) dans le CRS métrique du territoire. x,y = NaN si crs_id = -1."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    crs_id = territory_of(lon, lat) if crs_id is None else np.asarray(crs_id, np.int8)
    x = np.full(lon.shape, np.nan)
    y = np.full(lon.shape, np.nan)
    for cid, tf in _TF.items():
        m = crs_id == cid
        if m.any():
            x[m], y[m] = tf.transform(lon[m], lat[m])
    return crs_id, x, y


def unproject(x, y, crs_id):
    """(x, y, crs_id) -> (lon, lat)."""
    x, y, crs_id = np.asarray(x, float), np.asarray(y, float), np.asarray(crs_id)
    lon = np.full(x.shape, np.nan)
    lat = np.full(x.shape, np.nan)
    for cid, tf in _TF_INV.items():
        m = crs_id == cid
        if m.any():
            lon[m], lat[m] = tf.transform(x[m], y[m])
    return lon, lat


def detour_factor():
    """Coefficient réseau / vol d'oiseau calibré sur OSM (outputs/walk_calibration.json), sinon défaut."""
    f = C.OUT / "walk_calibration.json"
    if f.exists():
        return float(json.loads(f.read_text())["detour"])
    return C.DEFAULT_DETOUR


def walk_radius_m():
    """Rayon euclidien équivalent à 5 min de marche sur le réseau (≈ 400 m / détour)."""
    return C.WALK_NETWORK_M / detour_factor()


def pairs_within(src_crs, src_x, src_y, dst_crs, dst_x, dst_y, radius):
    """
    Toutes les paires (i_src, j_dst) à moins de `radius` mètres, territoire par territoire.
    Renvoie deux np.ndarray d'indices (positions dans les tableaux d'entrée).
    """
    src_crs, dst_crs = np.asarray(src_crs), np.asarray(dst_crs)
    I, J = [], []
    for cid in EPSG:
        si = np.flatnonzero(src_crs == cid)
        di = np.flatnonzero(dst_crs == cid)
        if len(si) == 0 or len(di) == 0:
            continue
        tree = cKDTree(np.c_[np.asarray(dst_x)[di], np.asarray(dst_y)[di]])
        sp = cKDTree(np.c_[np.asarray(src_x)[si], np.asarray(src_y)[si]])
        coo = sp.sparse_distance_matrix(tree, radius, output_type="coo_matrix")
        I.append(si[coo.row])
        J.append(di[coo.col])
    if not I:
        return np.array([], int), np.array([], int)
    return np.concatenate(I), np.concatenate(J)


def cell_fraction_within(dx, dy, radius, cell=None, sub=None):
    """
    Part de la surface d'un carreau (côté `cell`, centre décalé de (dx, dy) m par rapport à un
    point P) située à ≤ radius de P, estimée sur une sous-grille sub × sub (centres des
    sous-cellules). Vectorisé sur dx, dy. Sert de couverture fractionnaire : population
    du carreau à ≤ r de P = frac · ind, sous hypothèse de population uniforme dans le carreau.
    Supprime l'effet de seuil d'un comptage « centre du carreau à ≤ r » (r ≈ diagonale 282,8 m).
    """
    cell = C.CELL if cell is None else cell
    sub = C.CATCHMENT_SUBGRID if sub is None else sub
    u = (np.arange(sub) + 0.5) / sub * cell - cell / 2
    ux, uy = np.meshgrid(u, u)
    dx = np.asarray(dx, float)[..., None]
    dy = np.asarray(dy, float)[..., None]
    d2 = (dx + ux.ravel()) ** 2 + (dy + uy.ravel()) ** 2
    return (d2 <= radius * radius).mean(-1)


def cell_offsets_fraction(radius, cell=None, sub=None):
    """Décalages (dl, dc) en carreaux et fraction de surface du carreau voisin à ≤ radius du
    centre du carreau d'origine (fraction > 0 seulement)."""
    cell = C.CELL if cell is None else cell
    m = int(np.ceil((radius + cell / 2 * np.sqrt(2)) / cell))
    dl, dc = np.meshgrid(np.arange(-m, m + 1), np.arange(-m, m + 1), indexing="ij")
    dl, dc = dl.ravel(), dc.ravel()
    f = cell_fraction_within(dc * cell, dl * cell, radius, cell, sub)
    k = f > 0
    return dl[k], dc[k], f[k]


def nearest(src_crs, src_x, src_y, dst_crs, dst_x, dst_y, max_dist=np.inf):
    """
    Distance (m) de chaque point source au point destination le plus proche du même
    territoire (np.inf si aucun dans `max_dist`). Ajout rétro-compatible (model/recommend).
    """
    src_crs, dst_crs = np.asarray(src_crs), np.asarray(dst_crs)
    out = np.full(len(src_crs), np.inf)
    for cid in EPSG:
        si = np.flatnonzero(src_crs == cid)
        di = np.flatnonzero(dst_crs == cid)
        if len(si) == 0 or len(di) == 0:
            continue
        tree = cKDTree(np.c_[np.asarray(dst_x)[di], np.asarray(dst_y)[di]])
        d, _ = tree.query(np.c_[np.asarray(src_x)[si], np.asarray(src_y)[si]],
                          distance_upper_bound=max_dist)
        out[si] = d
    return out
