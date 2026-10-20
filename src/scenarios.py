"""
Étape 6c – Scénarios précalculés pour les curseurs du rapport Power BI.

L'app Streamlit relance l'optimiseur (src/recommend.py) à chaque mouvement de curseur : budget
Citiz, budget collectivité, priorité équité λ. Power BI ne peut pas exécuter Python à la volée :
on calcule donc d'avance toute la grille des curseurs de l'app, et le rapport filtre le scénario
choisi par des paramètres « what-if ».

Territoires : les TOP premiers du classement Citiz (outputs/territories_citiz.csv, colonne rank) et
l'Eurométropole de Strasbourg (territoire témoin), soit le segment « territoire » du rapport.

Les deux financeurs sont indépendants (recommend_by_funder : chaque liste a son propre budget et sa
propre couverture) : chaque financeur est optimisé seul, pour chaque (budget, λ). La grille reprend
celle de l'app : budgets de BUDGET_STEP à BUDGET_MAX par pas de BUDGET_STEP, λ de 0 à 1 par pas de 0,1.
Un budget n'est pas un simple préfixe d'une liste unique (enveloppes par type, quota peu dense) :
chaque point de la grille est une optimisation complète.

Chaque territoire est mis en cache (outputs/cache/scenarios_<zone>.parquet) : un calcul interrompu
reprend où il s'était arrêté. Les territoires sont répartis sur `--jobs` processus.

Sorties (outputs/fabric/) :
    scenarios_sites.parquet  – une ligne par site retenu × territoire × financeur × budget × λ ;
    scenarios_resume.parquet – une ligne par territoire × financeur × budget × λ (KPI, « prix de l'équité »).
Usage : python -m src.scenarios [--top 10] [--jobs 4] [--force]
"""
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import json

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

BUDGET_STEP = 100_000      # pas des curseurs de budget de l'app
BUDGET_MAX = 5_000_000
LAMBDAS = np.array(C.EQUITY_LAMBDAS)
TOP = 10
FABRIC = C.OUT / "fabric"
CACHE = C.OUT / "cache"


def areas(top=TOP):
    """[(zone, nom, rang Citiz)] : les `top` premiers territoires du classement, puis Strasbourg (témoin).
    Le premier (territoire prioritaire) est le territoire par défaut, comme dans l'app."""
    from src import territories
    t = pd.read_csv(C.OUT / "territories_citiz.csv", dtype={"epci": str})
    t = t[t["rank"].notna()].sort_values("rank").head(top)
    out = [(territories.area_of(r.epci), r.territoire, int(r.rank)) for r in t.itertuples()]
    if "ems" not in [a for a, _, _ in out]:
        out.append(("ems", "Eurométropole de Strasbourg (témoin)", None))
    return out


def _cache_files(area):
    name = area.replace(":", "")
    return (CACHE / f"scenarios_{name}_sites.parquet", CACHE / f"scenarios_{name}_resume.parquet",
            CACHE / f"scenarios_{name}.json")


def _signature(area):
    """Ce dont dépend la grille : un cache dont la signature diffère est recalculé."""
    files = [C.INTERIM / "offer.parquet", C.OUT / "cells_access.parquet",
             C.OUT / f"frequency_cells_{area.replace(':', '')}.parquet", *sorted(C.OUT.glob("model_*.joblib"))]
    return {"inputs": {f.name: int(f.stat().st_mtime) for f in files if f.exists()},
            "budget_step": BUDGET_STEP, "budget_max": BUDGET_MAX, "lambdas": [float(x) for x in LAMBDAS],
            "min_yield": C.ENVELOPE_MIN_YIELD}


def grid(area="ems"):
    """Optimise chaque financeur pour chaque (budget, λ) d'un territoire ; renvoie (sites, résumé)."""
    from src import recommend as rec
    budgets = range(BUDGET_STEP, BUDGET_MAX + 1, BUDGET_STEP)
    sites, resume = [], []
    for key in rec.FUNDERS:
        for b in budgets:
            for lam in LAMBDAS:
                bud = {"citiz_budget": b if key == "citiz" else 0, "public_budget": b if key != "citiz" else 0}
                df, s = rec.recommend_by_funder(area=area, equity_lambda=float(lam), compare=False, **bud)
                # entiers pour les paramètres « what-if » de Power BI (un double 0,3 ne s'égalise pas)
                tag = dict(financeur=key, budget_eur=b, budget_k_eur=b // 1000, equity_lambda=float(lam),
                           lambda_x10=int(round(10 * lam)))
                if len(df):
                    sites.append(df.assign(**tag))
                sel = (s["funders"].get(key) or {}).get("selected") or {}
                resume.append({**tag, "n_sites": sel.get("n_sites", 0), "cost_eur": sel.get("cost_eur", 0.0),
                               "pop_newly_served": sel.get("pop_newly_served", 0.0),
                               "pop_from_zero_option": sel.get("pop_from_zero_option", 0.0),
                               "eur_per_new_resident": sel.get("eur_per_new_resident"),
                               "co2_avoided_t_yr": sel.get("co2_avoided_t_yr", 0.0),
                               "part_modestes": sel.get("share_new_in_income_deciles_1_3", 0.0)})
    sites = pd.concat(sites, ignore_index=True).rename(columns={"code_commune": "com"}) if sites else pd.DataFrame()
    return sites, pd.DataFrame(resume)


def run_area(area, force=False):
    """Grille d'un territoire, depuis le cache si présent ; renvoie (zone, secondes)."""
    f_sites, f_resume, f_sig = _cache_files(area)
    t0 = time.time()
    sig = _signature(area)
    fresh = (f_sites.exists() and f_resume.exists() and f_sig.exists()
             and json.loads(f_sig.read_text(encoding="utf-8")) == sig)
    if force or not fresh:
        sites, resume = grid(area)
        CACHE.mkdir(parents=True, exist_ok=True)
        sites.to_parquet(f_sites, index=False)
        resume.to_parquet(f_resume, index=False)
        f_sig.write_text(json.dumps(sig, indent=1), encoding="utf-8")
    return area, time.time() - t0


def main():
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else TOP
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    force = "--force" in sys.argv
    zones = areas(top)
    print(f"[scenarios] {len(zones)} territoires × 2 financeurs × "
          f"{BUDGET_MAX // BUDGET_STEP * len(LAMBDAS)} scénarios, {jobs} processus")
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(run_area, a, force) for a, _, _ in zones]
        for fu in as_completed(futs):
            a, secs = fu.result()
            print(f"[scenarios] {a} : {secs:.0f} s", flush=True)
    sites, resume = [], []
    for order, (a, nom, rank) in enumerate(zones):
        f_sites, f_resume, _ = _cache_files(a)
        # zone sans « : » (même clé que recommandations.zone), epci = SIREN (clé de territoires_citiz)
        tag = dict(zone=a.replace(":", ""), epci=C.EMS_EPCI if a == "ems" else a.split(":")[-1],
                   zone_nom=nom, rang_citiz=rank if rank is not None else -1, ordre=order + 1,
                   zone_par_defaut=order == 0)
        sites.append(pd.read_parquet(f_sites).assign(**tag))
        resume.append(pd.read_parquet(f_resume).assign(**tag))
    sites, resume = pd.concat(sites, ignore_index=True), pd.concat(resume, ignore_index=True)
    for df in (sites, resume):
        df["rang_citiz"] = df["rang_citiz"].astype("int64")      # -1 = témoin hors classement
    FABRIC.mkdir(parents=True, exist_ok=True)
    sites.to_parquet(FABRIC / "scenarios_sites.parquet", index=False)
    resume.to_parquet(FABRIC / "scenarios_resume.parquet", index=False)
    print(f"-> scenarios_sites.parquet ({len(sites)} lignes), scenarios_resume.parquet ({len(resume)} lignes)")


if __name__ == "__main__":
    main()
