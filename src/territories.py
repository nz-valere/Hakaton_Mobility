"""
Étape 5b – Où Citiz doit-il s'implanter en priorité ? Classement national des intercommunalités.

La recommandation site par site (src/recommend.py) répond à « où, DANS un territoire » ; ce
module choisit d'abord LE territoire. Unité : intercommunalité (EPCI, geo.api.gouv.fr), échelle
à laquelle une coopérative Citiz négocie le stationnement avec la collectivité.

Deux étapes :
    1. criblage national (toutes les EPCI d'au moins C.TERRITORY_MIN_POP habitants, hors
       C.TERRITORY_EXCLUDED_DEPS) : potentiel = Σ habitants × valeur du site (modèle Citiz, même
       formule que l'optimiseur : clip(p / p_ref) ** C.MODEL_VALUE_EXPONENT, propensions HORS PLI
       départemental) sur les carreaux DENSES (≥ C.LOW_DENSITY_HAB_KM2 à ~1 km) qu'aucune station
       d'autopartage (Citiz ou autre) ne dessert à 5 min. Rapide, mais ignore le budget : une
       grande EPCI a mécaniquement plus de potentiel qu'un opérateur ne peut en capter ;
    2. simulation budgétée sur les C.TERRITORY_SHORTLIST premières EPCI (+ l'Eurométropole de
       Strasbourg, territoire témoin où Citiz est déjà implanté) : la même optimisation que
       src/recommend.py, stations Citiz seules, budget C.CITIZ_BUDGET. Classement final par
       adhérents potentiels des stations retenues (habitants nouvellement desservis × pénétration
       nationale Citiz × valeur du site) : c'est ce qu'un même budget rapporte à Citiz ici.

Statut : « nouveau territoire » si aucune station Citiz ne dessert d'habitant de l'EPCI,
« extension » sinon.

Île-de-France exclue (C.TERRITORY_EXCLUDED_DEPS) : l'autopartage y est surtout le fait
d'opérateurs absents des flux GBFS publics (Getaround, Zity, Communauto, Free2Move), d'où une
couverture apparente de ~1 % pour le Grand Paris ; le potentiel y serait surestimé d'un ordre de
grandeur. Même biais, plus faible, ailleurs : c'est une limite du classement.

Sorties : outputs/territories_citiz.csv (criblage + simulation), outputs/territories_summary.json
(territoire prioritaire `top`). Usage : python -m src.territories
"""
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import model  # noqa: E402

F_RANK = C.OUT / "territories_citiz.csv"
F_SUMMARY = C.OUT / "territories_summary.json"
# Paris, Marseille, Lyon : les carreaux Filosofi portent le code d'arrondissement municipal
PLM = (("751", "75056"), ("132", "13055"), ("6938", "69123"))


# --------------------------------------------------------------------------- référentiel EPCI
@lru_cache(maxsize=1)
def _epci_tables():
    com_epci = {c["code"]: c.get("codeEpci") for c in json.loads((C.RAW / "communes_epci.json").read_text(encoding="utf-8"))}
    names = {e["code"]: e["nom"] for e in json.loads((C.RAW / "epcis.json").read_text(encoding="utf-8"))}
    return com_epci, names


def com_to_epci(com):
    """Code EPCI (SIREN) de chaque code commune ; arrondissements PLM rattachés à leur commune."""
    com_epci, _ = _epci_tables()
    s = pd.Series(np.asarray(com, dtype=object)).astype(str)
    for prefix, code in PLM:
        s = s.where(~s.str.startswith(prefix) | (s.str.len() != 5), code)
    return s.map(com_epci)


def epci_name(code):
    return _epci_tables()[1].get(str(code), str(code))


@lru_cache(maxsize=64)
def epci_communes(code):
    """Codes commune (tels qu'ils figurent dans cells.parquet) appartenant à l'EPCI `code`."""
    coms = pd.Series(pd.read_parquet(C.INTERIM / "cells.parquet", columns=["com"])["com"].unique())
    sel = coms[(com_to_epci(coms) == str(code)).values]
    if len(sel) == 0:
        raise ValueError(f"aucun carreau pour l'EPCI {code}")
    return tuple(sorted(sel))


def area_of(code):
    """Paramètre `area` de src.recommend pour une EPCI (l'Eurométropole garde son alias « ems »)."""
    return "ems" if str(code) == C.EMS_EPCI else f"epci:{code}"


def load_summary():
    try:
        return json.loads(F_SUMMARY.read_text(encoding="utf-8"))
    except Exception:
        return None


def top_area():
    """Zone du territoire prioritaire (outputs/territories_summary.json), sinon l'Eurométropole."""
    s = load_summary()
    return area_of(s["top"]["epci"]) if s and s.get("top") else "ems"


# --------------------------------------------------------------------------- 1. criblage national
def screen(cells, F, pred, p_ref):
    """Une ligne par EPCI : population, couverture autopartage / Citiz, potentiel pondéré par le modèle."""
    ind = cells["ind"].fillna(0).values
    served = (F["n_citiz_r5"].values + F["n_carsharing_r5"].values) > 0
    citiz = F["n_citiz_r5"].values > 0
    dense = F["dens_1k"].values >= C.LOW_DENSITY_HAB_KM2
    v = np.clip(pred / p_ref, *C.VALUE_CLIP) ** C.MODEL_VALUE_EXPONENT
    target = ~served & dense
    df = pd.DataFrame({
        "epci": com_to_epci(cells["com"].values).values, "dep": cells["dep"].values, "ind": ind,
        "pop_dense": ind * dense, "pop_carsharing": ind * served, "pop_citiz": ind * citiz,
        "pop_target": ind * target, "potential": ind * target * v, "v_target": v * ind * target,
        "carfree": cells["carfree_share"].fillna(0).values * ind,
        "d_citiz": F["d_citiz"].values})
    df = df[df["epci"].notna()]
    g = df.groupby("epci").agg(
        population=("ind", "sum"), pop_dense=("pop_dense", "sum"), pop_carsharing=("pop_carsharing", "sum"),
        pop_citiz=("pop_citiz", "sum"), pop_target=("pop_target", "sum"), potential=("potential", "sum"),
        v_target=("v_target", "sum"), carfree=("carfree", "sum"), d_citiz_m=("d_citiz", "min"),
        dep=("dep", lambda s: s.value_counts().index[0]))
    pop = g["population"].clip(lower=1)
    out = pd.DataFrame({
        "epci": g.index, "territoire": [epci_name(c) for c in g.index], "dep": g["dep"].values,
        "population": g["population"].round(0).values,
        "share_dense": (g["pop_dense"] / pop).round(3).values,
        "share_carsharing_served": (g["pop_carsharing"] / pop).round(3).values,
        "share_citiz_served": (g["pop_citiz"] / pop).round(3).values,
        "share_carfree_households": (g["carfree"] / pop).round(3).values,
        "pop_dense_unserved": g["pop_target"].round(0).values,
        "mean_value_unserved": (g["v_target"] / g["pop_target"].clip(lower=1)).round(3).values,
        "potential": g["potential"].round(0).values,
        # distance du carreau habité le plus proche à une station Citiz (plafond 20 km)
        "dist_citiz_km": (g["d_citiz_m"] / 1000).round(1).values,
    })
    out["statut"] = np.where(out["share_citiz_served"] > 0, "extension", "nouveau territoire")
    out["eligible"] = (out["population"] >= C.TERRITORY_MIN_POP) & ~out["dep"].isin(C.TERRITORY_EXCLUDED_DEPS)
    return out.sort_values("potential", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- 2. simulation budgétée
def simulate(code, budget=None, equity_lambda=C.EQUITY_LAMBDA):
    """Optimisation Citiz seule sur l'EPCI (même moteur que src/recommend.py) -> indicateurs."""
    from src import recommend
    budget = C.CITIZ_BUDGET if budget is None else budget
    df, s = recommend.recommend(area_of(code), budget, equity_lambda, kinds=("citiz",), compare=False)
    sel = s["selected"]
    return {
        "sim_sites": int(sel.get("n_sites", 0)),
        "sim_pop_newly_served": round(float(sel.get("pop_newly_served", 0)), 0),
        "sim_members_potential": round(float(df["demand_potential"].sum()) if len(df) else 0.0, 0),
        "sim_vehicles_suggested": int(df["vehicles_suggested"].sum()) if len(df) else 0,
        "sim_co2_t_yr": round(float(sel.get("co2_avoided_t_yr", 0)), 1),
        "sim_eur_per_resident": round(float(sel.get("eur_per_new_resident", np.nan)), 1),
        "sim_share_low_income": round(float(sel.get("share_new_in_income_deciles_1_3", np.nan)), 3),
        "sim_top_communes": ", ".join(df["commune"].drop_duplicates().head(3)) if len(df) else "",
    }


def rank(scr, n_short=None, budget=None):
    """Liste courte (criblage) + territoire témoin, simulés puis classés par adhérents potentiels."""
    n_short = C.TERRITORY_SHORTLIST if n_short is None else n_short
    short = scr[scr["eligible"]].head(n_short)["epci"].tolist()
    ref = [] if C.EMS_EPCI in short else [C.EMS_EPCI]
    rows = []
    for code in short + ref:
        t0 = time.time()
        r = simulate(code, budget)
        rows.append({"epci": code, "shortlist": code in short, **r})
        print(f"  {epci_name(code)[:45]:45s} {r['sim_sites']:3d} stations  "
              f"{r['sim_pop_newly_served']:>8,.0f} hab.  {r['sim_members_potential']:>6,.0f} adhérents "
              f"({time.time() - t0:.0f} s)")
    sim = pd.DataFrame(rows)
    out = scr.merge(sim, on="epci", how="left")
    out["shortlist"] = out["shortlist"].astype("boolean").fillna(False).astype(bool)
    ok = out["shortlist"] & out["sim_members_potential"].notna()
    out["rank"] = np.nan
    order = out[ok].sort_values(["sim_members_potential", "sim_pop_newly_served"], ascending=False).index
    out.loc[order, "rank"] = np.arange(1, len(order) + 1)
    out["screen_rank"] = np.nan
    el = out.index[out["eligible"]]
    out.loc[el, "screen_rank"] = np.arange(1, len(el) + 1)
    out["reference"] = out["epci"] == C.EMS_EPCI
    return out.sort_values(["rank", "screen_rank"], na_position="last").reset_index(drop=True)


def main():
    t0 = time.time()
    cells, F, _ = model.cached_features()
    b = model.load_bundle("citiz")
    pred = model.predict_value(F, "citiz", oof=True, dep=cells["dep"].values)
    scr = screen(cells, F, pred, b["p_ref"])
    print(f"criblage : {int(scr['eligible'].sum())} EPCI éligibles sur {len(scr)} ({time.time() - t0:.0f} s)")
    out = rank(scr)
    out.to_csv(F_RANK, index=False)
    top = out.iloc[0]
    ref = out[out["reference"]].iloc[0] if out["reference"].any() else None
    cols = ["epci", "territoire", "dep", "population", "statut", "share_carsharing_served", "share_citiz_served",
            "potential", "sim_sites", "sim_pop_newly_served", "sim_members_potential", "sim_vehicles_suggested",
            "sim_co2_t_yr", "sim_top_communes"]

    def rec(r):
        return {c: (r[c].item() if hasattr(r[c], "item") else r[c]) for c in cols}

    summary = {
        "method": "criblage national (Σ habitants × valeur du modèle, carreaux denses sans autopartage à 5 min) "
                  "puis simulation de l'optimiseur Citiz seul sur la liste courte ; classement par "
                  "adhérents potentiels",
        "citiz_budget_eur": C.CITIZ_BUDGET, "min_population": C.TERRITORY_MIN_POP,
        "excluded_deps": list(C.TERRITORY_EXCLUDED_DEPS), "shortlist": C.TERRITORY_SHORTLIST,
        "n_epci_screened": int(len(scr)), "n_epci_eligible": int(scr["eligible"].sum()),
        "top": rec(top), "reference_strasbourg": rec(ref) if ref is not None else None,
        "ranking": [rec(r) for _, r in out[out["rank"].notna()].iterrows()],
        "runtime_s": round(time.time() - t0, 1),
    }
    F_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    pd.set_option("display.width", 220)
    show = ["rank", "territoire", "statut", "population", "share_carsharing_served", "potential", "sim_sites",
            "sim_pop_newly_served", "sim_members_potential"]
    print(out[out["rank"].notna() | out["reference"]][show].to_string(index=False))
    print(f"-> territoire prioritaire : {top['territoire']} ({top['statut']}) ; {F_RANK.name}, {F_SUMMARY.name}")
    return out, summary


if __name__ == "__main__":
    from src import territories as _t   # objets importés sous src.territories (cf. src/model.py)
    _t.main()
