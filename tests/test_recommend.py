"""Tests de src/recommend.py sur une zone synthétique (sans dépendre des modèles entraînés)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import model, recommend as R  # noqa: E402


def synthetic_ctx(n_side=30, seed=0, served_block=None, poor_block=None):
    """Grille n_side² carreaux 200 m ; offre fictive ; propensions uniformes."""
    rng = np.random.default_rng(seed)
    gx, gy = np.meshgrid(np.arange(n_side), np.arange(n_side))
    gx, gy = gx.ravel(), gy.ravel()
    n = len(gx)
    ind = rng.gamma(2.0, 30, n)
    cells = pd.DataFrame({
        "crs_id": np.zeros(n, np.int8), "x": 4_000_000 + gx * 200.0 + 100, "y": 2_800_000 + gy * 200.0 + 100,
        "lon": 7.7 + gx * 0.0027, "lat": 48.5 + gy * 0.0018, "com": "67482", "dep": "67",
        "ind": ind, "men": ind / 2.2, "growth": 1.05, "pop_future": ind * 1.05,
        "poverty_rate": 0.1, "carfree_share": 0.3, "income_pc": rng.normal(25_000, 3_000, n),
    })
    cells["men_pauv"] = cells["men"] * cells["poverty_rate"]
    F = pd.DataFrame({f"n_{m}_r5": np.zeros(n) for m in model.MODES})
    F["d_transit"] = 300.0
    F["dens_1k"] = 3000.0
    F["n_options_r5"] = 1.0
    if served_block is not None:           # carreaux déjà desservis par tous les modes
        m = served_block(gx, gy)
        for k in ("citiz", "bike", "transit"):
            F.loc[m, f"n_{k}_r5"] = 1
    if poor_block is not None:             # quartier à fort besoin mais un peu moins peuplé
        m = poor_block(gx, gy)
        cells.loc[m, "poverty_rate"] = 0.6
        cells.loc[m, "carfree_share"] = 0.6
        cells.loc[m, "ind"] *= 0.8
        cells["men_pauv"] = cells["men"] * cells["poverty_rate"]
    pred = {k: np.full(n, 0.5) for k in C.MODEL_KINDS}
    return {"name": "test", "cells": cells, "F": F, "pred": pred, "p_ref": {k: 0.5 for k in C.MODEL_KINDS},
            "com_name": np.array(["Test"] * n), "offer_source": "synthetic", "penetration": 0.01, "prep_s": 0}


def test_budget_respected():
    ctx = synthetic_ctx()
    for budget in (100_000, 500_000, 1_500_000):
        picks = R.solve(ctx, budget=budget)
        assert picks["cost"].sum() <= budget + 1e-6
        assert len(picks) > 0
        # glouton : le reliquat est inférieur au coût du site le moins cher encore utile
        assert budget - picks["cost"].sum() < min(C.facility_cost(k) for k in ("citiz", "bike")) \
            or len(picks) == (ctx["cells"]["ind"] > 0).sum() * 3


def test_served_cells_ignored():
    # moitié gauche de la grille déjà desservie par tous les modes
    ctx = synthetic_ctx(served_block=lambda gx, gy: gx < 15)
    picks = R.solve(ctx, budget=1_000_000)
    gx = ((ctx["cells"]["x"].values - 4_000_100) / 200).astype(int)
    # aucun candidat placé dans la zone desservie
    assert (gx[picks["cell"].values] >= 15).all()
    ev = R.evaluate(ctx, picks)
    served = gx < 15
    # la population comptée comme nouvellement desservie exclut les carreaux déjà desservis
    covered_unserved = set()
    for _, s in picks.iterrows():
        covered_unserved |= {(s["kind"], c) for c in s["covered"] if not served[c]}
    pop = ctx["cells"]["ind"].values
    assert np.isclose(ev["pop_new"].sum(), sum(pop[c] for _, c in covered_unserved))


def test_lambda_changes_order():
    ctx = synthetic_ctx(poor_block=lambda gx, gy: (gx >= 20) & (gy >= 20))
    poor = ctx["cells"]["poverty_rate"].values > 0.5
    p0 = R.solve(ctx, budget=600_000, equity_lambda=0.0)
    p1 = R.solve(ctx, budget=600_000, equity_lambda=3.0)
    assert list(p0["cell"]) != list(p1["cell"])
    share = lambda p: np.mean([poor[c].mean() for c in p["covered"]])  # noqa: E731
    assert share(p1) > share(p0)


def test_bus_detour_cost_and_exclusion():
    ctx = synthetic_ctx()
    ctx["F"]["d_transit"] = np.where(np.arange(len(ctx["cells"])) % 2 == 0, 800.0, 5_000.0)
    picks = R.solve(ctx, budget=3_000_000, kinds=("bus",))
    d = ctx["F"]["d_transit"].values[picks["cell"].values]
    assert (d <= C.BUS_DETOUR["max_dist_m"]).all()
    assert np.allclose(picks["cost"], C.facility_cost("bus", R.bus_extra_annual(800.0)))


if __name__ == "__main__":
    test_budget_respected()
    test_served_cells_ignored()
    test_lambda_changes_order()
    test_bus_detour_cost_and_exclusion()
    print("ok")
