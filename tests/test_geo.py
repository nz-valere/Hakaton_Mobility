"""Tests de src/geo.py : projection, rayon, voisinages (cœur géométrique de tout le pipeline)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import geo  # noqa: E402


def test_territory_of_and_roundtrip():
    lon = np.array([7.75, -61.0, 55.45, -61.5, 0.0])     # Strasbourg, Martinique, Réunion, Guadeloupe, hors
    lat = np.array([48.58, 14.6, -21.1, 16.2, 0.0])
    crs, x, y = geo.project(lon, lat)
    assert crs.tolist() == [0, 1, 2, -1, -1]
    assert np.isnan(x[3:]).all() and np.isnan(y[3:]).all()
    lo, la = geo.unproject(x[:3], y[:3], crs[:3])
    np.testing.assert_allclose(lo, lon[:3], atol=1e-9)
    np.testing.assert_allclose(la, lat[:3], atol=1e-9)


def test_project_is_metric():
    # 0,001° de latitude ≈ 111 m quel que soit le territoire
    _, x, y = geo.project([7.75, 7.75], [48.580, 48.581])
    assert abs(np.hypot(x[1] - x[0], y[1] - y[0]) - 111.2) < 1.0


def _brute(src, dst, r):
    return {(i, j) for i, (ci, xi, yi) in enumerate(src) for j, (cj, xj, yj) in enumerate(dst)
            if ci == cj and ci >= 0 and np.hypot(xi - xj, yi - yj) <= r}


def test_pairs_within_matches_brute_force():
    rng = np.random.default_rng(0)
    n, m = 300, 200
    src = list(zip(rng.integers(-1, 3, n), rng.uniform(0, 2000, n), rng.uniform(0, 2000, n)))
    dst = list(zip(rng.integers(-1, 3, m), rng.uniform(0, 2000, m), rng.uniform(0, 2000, m)))
    dst.append(src[0])                                   # distance nulle : doit être gardée
    S, D = np.array(src), np.array(dst)
    I, J = geo.pairs_within(S[:, 0], S[:, 1], S[:, 2], D[:, 0], D[:, 1], D[:, 2], 150.0)
    assert set(zip(I.tolist(), J.tolist())) == _brute(src, dst, 150.0)
    assert I.dtype.kind == "i" and J.dtype.kind == "i"


def test_pairs_within_empty_and_other_territory():
    I, J = geo.pairs_within([0], [0.0], [0.0], [1], [0.0], [0.0], 100.0)   # même x,y, autre CRS
    assert len(I) == 0 and len(J) == 0


def test_nearest():
    d = geo.nearest([0, 0, 1], [0.0, 0.0, 0.0], [0.0, 1000.0, 0.0], [0], [3.0], [4.0], max_dist=500)
    assert d[0] == pytest.approx(5.0)
    assert np.isinf(d[1])          # au-delà de max_dist
    assert np.isinf(d[2])          # aucun point dans ce territoire


@pytest.mark.parametrize("r", [100.0, 282.0, 400.0])
def test_cell_offsets_fraction_integrates_disc_area(r):
    _, _, f = geo.cell_offsets_fraction(r, sub=64)
    assert f.sum() * C.CELL ** 2 == pytest.approx(np.pi * r * r, rel=0.01)
    assert f.max() <= 1.0 and f.min() > 0


def test_cell_fraction_symmetry_and_bounds():
    f = geo.cell_fraction_within([200, -200, 0, 0], [0, 0, 200, -200], 250.0)
    assert np.allclose(f, f[0])
    assert geo.cell_fraction_within(0, 0, 1e6) == 1.0
    assert geo.cell_fraction_within(5000, 0, 100) == 0.0


def test_walk_radius_reads_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    assert geo.detour_factor() == C.DEFAULT_DETOUR                     # pas de calibration -> défaut
    assert geo.walk_radius_m() == pytest.approx(C.WALK_NETWORK_M / C.DEFAULT_DETOUR)
    (tmp_path / "walk_calibration.json").write_text(json.dumps({"detour": 2.0}), encoding="utf-8")
    assert geo.walk_radius_m() == pytest.approx(C.WALK_NETWORK_M / 2.0)
