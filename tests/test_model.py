"""Tests de src/model.py (synthétiques, sans dépendre des modèles entraînés ni du cache)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import model  # noqa: E402


def test_feature_columns_exclude_target_modes():
    """Anti-fuite : aucune variable d'un mode cible (ni d'un mode exclu) dans le modèle du type."""
    for kind in C.MODEL_KINDS:
        cols = model.feature_columns(kind)
        excl = set(C.KIND_EXCLUDED_FEATURE_MODES[kind]) | set(C.KIND_TARGET_MODES[kind])
        assert set(C.KIND_TARGET_MODES[kind]) <= set(C.KIND_EXCLUDED_FEATURE_MODES[kind])
        for m in excl:
            assert not any(c in cols for c in (f"n_{m}_r5", f"n_{m}_1k", f"d_{m}", f"cap_{m}_r5"))
        assert "growth" not in cols and "n_options_r5" not in cols   # constante dép. / agrégat cible


def test_grid_box_sums_matches_brute_force():
    rng = np.random.default_rng(0)
    n = 300
    sx = rng.integers(0, 40, n) * C.CELL + 100.0
    sy = rng.integers(0, 40, n) * C.CELL + 100.0
    w = rng.random(n)
    qx, qy = sx[:50], sy[:50]
    out = model._grid_box_sums(np.zeros(n, int), sx, sy, w, np.zeros(50, int), qx, qy, [1, 5])
    for h in (1, 5):
        brute = np.array([w[(np.abs(sx - x) <= h * C.CELL + 1) & (np.abs(sy - y) <= h * C.CELL + 1)].sum()
                          for x, y in zip(qx, qy)])
        np.testing.assert_allclose(out[h][:, 0], brute, rtol=1e-9, atol=1e-9)


class _Const:
    def __init__(self, v):
        self.v = v

    def predict_proba(self, X):
        return np.column_stack([1 - np.full(len(X), self.v), np.full(len(X), self.v)])


@pytest.fixture
def fake_bundle():
    b = {"kind": "citiz", "features": ["a"], "model": _Const(0.9),
         "fold_models": [_Const(0.1), _Const(0.2)], "dep_fold": {"67": 0, "54": 1},
         "p_ref": 0.3, "p_ref_insample": 0.5}
    old = model._BUNDLES.get("citiz")
    model._BUNDLES["citiz"] = b
    yield b
    if old is None:
        model._BUNDLES.pop("citiz", None)
    else:
        model._BUNDLES["citiz"] = old


def test_predict_value_oof_routing(fake_bundle):
    F = pd.DataFrame({"a": np.zeros(4)})
    np.testing.assert_allclose(model.predict_value(F, "citiz"), 0.9)            # rétrocompatible
    p = model.predict_value(F, "citiz", oof=True, dep=["67", "54", "2A", "67"])
    np.testing.assert_allclose(p, [0.1, 0.2, 0.9, 0.1])                       # dép. inconnu -> complet
    np.testing.assert_allclose(model.predict_value(F, "citiz", oof=True, dep="54"), 0.2)
    with pytest.raises(ValueError):
        model.predict_value(F, "citiz", oof=True)
    F["dep"] = "67"
    np.testing.assert_allclose(model.predict_value(F, "citiz", oof=True), 0.1)


def test_within_dep_backtest_perfect_model():
    rng = np.random.default_rng(1)
    n = 400
    groups = np.repeat(["67", "54"], n // 2)
    y = rng.random(n) < 0.2
    pop = rng.random(n)                       # population non informative
    res = model._within_dep_backtest(y, y.astype(float) + 0.01 * rng.random(n), pop, groups)
    assert res["n_deps"] == 2 and res["model_beats_pop_ap"] == 2
    assert res["mean_ap_model"] == pytest.approx(1.0) and res["mean_prec_k_model"] == pytest.approx(1.0)
