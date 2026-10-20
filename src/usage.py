"""
Étape 5c – Validation du modèle Citiz par l'USAGE RÉEL des stations (collecte GBFS, src/collect_gbfs.py).

Le modèle de src/model.py apprend où les opérateurs se sont implantés (positive-unlabeled) : il peut
reproduire leurs choix passés sans rien dire de l'usage. On le confronte donc à un signal indépendant
des choix d'implantation : le taux d'occupation observé de chaque station Citiz.

Indicateurs par station (relevés où la station a au moins une voiture) :
    occupation    = Σ voitures réservées / Σ voitures (part du temps-voiture réservé) ;
    disponibilite = part des relevés où au moins une voiture est libre ;
    saturee       = occupation ≥ C.SATURATION_OCCUPANCY (candidate à une 2e voiture plutôt qu'à une
                    nouvelle station : c'est moins cher et la demande y est déjà démontrée).
Validation : corrélation de rang (Spearman) entre l'occupation et la propension HORS PLI du modèle
(predict_value(oof=True) : chaque station est scorée par le modèle qui n'a pas vu son département),
comparée à la même corrélation pour la population à 5 min seule. Occupation moyenne par quintile
de propension.

Limites (écrites dans la sortie) : fenêtre courte (quelques jours), en partie pendant les vacances
de la Toussaint ; sens exact de `is_reserved` à confirmer avec Citiz ; collecte interrompue quand le
PC est en veille (le nombre de relevés par station est publié).

Sorties : outputs/citiz_usage.csv (une ligne par station), outputs/usage_validation.json.
Usage : python -m src.usage
"""
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402

F_USAGE = C.OUT / "citiz_usage.csv"
F_VALID = C.OUT / "usage_validation.json"


def _text(v):
    if isinstance(v, list):
        return v[0].get("text") if v and isinstance(v[0], dict) else None
    return v


def station_usage(collect_dir=None, min_snapshots=None):
    """Occupation et disponibilité de chaque station Citiz à partir des relevés collectés."""
    d = Path(collect_dir or C.GBFS_COLLECT)
    min_snapshots = C.USAGE_MIN_SNAPSHOTS if min_snapshots is None else min_snapshots
    files = sorted(d.glob("citiz_status_*.csv"))
    if not files:
        return None, {}
    s = pd.concat([pd.read_csv(f, dtype={"station_id": str}) for f in files], ignore_index=True)
    s = s[s["n_vehicles"] > 0].copy()
    s["libre"] = (s["n_vehicles"] - s["n_reserved"]) >= 1
    g = s.groupby(["provider_id", "station_id"]).agg(
        releves=("ts_utc", "nunique"), vehicules=("n_vehicles", "median"),
        res=("n_reserved", "sum"), veh=("n_vehicles", "sum"), disponibilite=("libre", "mean")).reset_index()
    g["occupation"] = g["res"] / g["veh"]
    g = g[g["releves"] >= min_snapshots].drop(columns=["res", "veh"])
    # nom et position : station_information la plus récente de chaque réseau
    info = {}
    for f in sorted(glob.glob(str(d / "citiz_stations_p*_*.json"))):
        pid = int(re.search(r"_p(\d+)_", f).group(1))
        for st in json.loads(Path(f).read_text(encoding="utf-8"))["data"]["stations"]:
            info[(pid, str(st["station_id"]))] = (_text(st.get("name")), st.get("lat"), st.get("lon"))
    meta = pd.DataFrame([(k[0], k[1], *v) for k, v in info.items()],
                        columns=["provider_id", "station_id", "name", "lat", "lon"])
    g = g.merge(meta, on=["provider_id", "station_id"], how="inner")
    g["saturee"] = g["occupation"] >= C.SATURATION_OCCUPANCY
    ts = pd.to_datetime(s["ts_utc"], utc=True)
    period = {"debut": str(ts.min()), "fin": str(ts.max()), "releves": int(s["ts_utc"].nunique()),
              "releves_attendus_si_continu": int((ts.max() - ts.min()).total_seconds() // C.GBFS_COLLECT_INTERVAL_S) + 1}
    return g.reset_index(drop=True), period


def attach_cells(usage, cells, max_dist=None):
    """Carreau habité le plus proche de chaque station (≤ max_dist m), même territoire."""
    max_dist = C.CELL * 1.5 if max_dist is None else max_dist
    crs, x, y = geo.project(usage["lon"].values, usage["lat"].values)
    idx = np.full(len(usage), -1)
    for cid in np.unique(crs[crs >= 0]):
        mc = cells["crs_id"].values == cid
        ms = crs == cid
        tree = cKDTree(np.c_[cells["x"].values[mc], cells["y"].values[mc]])
        dist, k = tree.query(np.c_[x[ms], y[ms]], distance_upper_bound=max_dist)
        ok = np.isfinite(dist)
        sel = np.flatnonzero(ms)[ok]
        idx[sel] = np.flatnonzero(mc)[k[ok]]
    return idx


def validate(usage, cells, F, kind="citiz"):
    from src import model
    idx = attach_cells(usage, cells)
    u = usage[idx >= 0].copy()
    u["cell"] = idx[idx >= 0]
    Fu = F.iloc[u["cell"].values]
    u["propension_oof"] = model.predict_value(Fu, kind, oof=True, dep=cells["dep"].values[u["cell"].values])
    u["pop_5min"] = Fu["pop_r5"].values
    rho_m, p_m = spearmanr(u["propension_oof"], u["occupation"])
    rho_p, p_p = spearmanr(u["pop_5min"], u["occupation"])
    u["quintile"] = pd.qcut(u["propension_oof"].rank(method="first"), 5, labels=[f"Q{i}" for i in range(1, 6)])
    q = u.groupby("quintile", observed=True).agg(stations=("occupation", "size"),
                                                 occupation_moyenne=("occupation", "mean"),
                                                 propension_mediane=("propension_oof", "median")).reset_index()
    res = {
        "stations_validees": int(len(u)), "stations_sans_carreau_habite_proche": int((idx < 0).sum()),
        "spearman_modele_occupation": round(float(rho_m), 3), "p_value_modele": float(p_m),
        "spearman_population_occupation": round(float(rho_p), 3), "p_value_population": float(p_p),
        "occupation_par_quintile_de_propension": q.round(3).to_dict("records"),
        "lecture": "Corrélation de rang entre la propension hors pli du modèle Citiz et la part du temps où les "
                   "voitures de la station sont réservées. > 0 : le modèle, appris seulement sur la PRÉSENCE des "
                   "stations, classe aussi correctement leur USAGE ; à comparer à la population seule.",
    }
    return u, res


def main():
    from src import model
    usage, period = station_usage()
    if usage is None or len(usage) == 0:
        print("Aucun relevé : lancer python -m src.collect_gbfs (quelques heures au moins).")
        return
    print(f"[usage] {len(usage)} stations Citiz avec au moins {C.USAGE_MIN_SNAPSHOTS} relevés "
          f"({period['releves']} relevés sur {period['releves_attendus_si_continu']} attendus)")
    cells, F, _ = model.cached_features()
    u, res = validate(usage, cells, F)
    out = {"periode": period, **res,
           "saturation": {"seuil_occupation": C.SATURATION_OCCUPANCY, "stations_saturees": int(u["saturee"].sum()),
                          "part": round(float(u["saturee"].mean()), 3)},
           "occupation_mediane": round(float(u["occupation"].median()), 3),
           "limites": ["fenêtre courte, en partie pendant les vacances de la Toussaint (17 oct.-2 nov. 2026)",
                       "sens exact de is_reserved à confirmer avec Citiz (réservation en cours ou à venir)",
                       "collecte interrompue quand le PC est en veille : voir releves vs releves_attendus_si_continu",
                       "validation, pas apprentissage : le modèle n'utilise pas ces données"]}
    cols = ["provider_id", "station_id", "name", "lon", "lat", "releves", "vehicules", "occupation", "disponibilite",
            "saturee", "propension_oof", "pop_5min"]
    u[cols].sort_values("occupation", ascending=False).to_csv(F_USAGE, index=False)
    F_VALID.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("stations_validees", "spearman_modele_occupation",
                                          "spearman_population_occupation", "saturation")}, ensure_ascii=False))
    print(f"-> {F_USAGE.name}, {F_VALID.name}")


if __name__ == "__main__":
    main()
