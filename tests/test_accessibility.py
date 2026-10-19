"""
Cas synthétique calculé à la main pour src/accessibility.compute (rayon 250 m).

    A (10 hab, 5 mén.)  centre (100, 100)
    B (20 hab, 10 mén.) centre (300, 100)      A–B = 200 m -> voisins
    C (40 hab, 15 mén.) centre (1100, 100)     isolé, aucune option
    S1 transit (200, 100) : à 100 m de A et de B
    S2 vélo    (400, 100) : à 100 m de B, 300 m de A (hors rayon)

Attendu : n_options A=1, B=2, C=0 ; pop_catchment A=B=30, C=40 ; pop_served S1=30, S2=20 ;
2SFCA : R1 = 1/30, R2 = 1/20 -> A = 33,33 ; B = 33,33 + 50 = 83,33 ; C = 0.
Rang pondéré de n_options parmi les desservis (A:10 hab, B:20 hab) : A = 5/30, B = 20/30
-> score_options A = 1 + 99/6 = 17,5 ; B = 1 + 99·2/3 = 67 ; C = 0.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src.accessibility import compute  # noqa: E402
from src.population import cell_key  # noqa: E402


@pytest.fixture
def result():
    x = np.array([100.0, 300.0, 1100.0])
    y = np.array([100.0, 100.0, 100.0])
    cells = pd.DataFrame({
        "key": cell_key(0, x - C.CELL / 2, y - C.CELL / 2), "crs_id": np.int8(0), "x": x, "y": y,
        "com": "00001", "dep": "00", "ind": [10.0, 20.0, 40.0], "men": [5.0, 10.0, 15.0],
    })
    offer = pd.DataFrame({"offer_id": ["transit:t:1", "bike:t:2"], "mode": ["transit", "bike"],
                          "crs_id": np.int8(0), "x": [200.0, 400.0], "y": [100.0, 100.0]})
    return compute(cells, offer, radius=250.0)


def test_cells(result):
    ca, _ = result
    assert ca["n_transit"].tolist() == [1, 1, 0]
    assert ca["n_bike"].tolist() == [0, 1, 0]
    assert ca["n_options"].tolist() == [1, 2, 0]
    assert ca["n_modes"].tolist() == [1, 2, 0]
    assert ca["pop_catchment"].tolist() == [30, 30, 40]
    np.testing.assert_allclose(ca["options_per_1000"], [1000 / 30, 2000 / 30, 0])
    np.testing.assert_allclose(ca["access_2sfca"], [1000 / 30, 1000 / 30 + 50, 0])
    np.testing.assert_allclose(ca["score_options"], [17.5, 67.0, 0.0])
    assert ca["served_bike"].tolist() == [False, True, False]


def test_stations(result):
    ca, st = result
    assert st["pop_served"].tolist() == [30, 20]
    assert st["households_served"].tolist() == [15, 10]
    assert st["pop_served_exclusive"].tolist() == [30, 20]
    # 2SFCA : toute l'offre est répartie entre ses habitants (Σ ind·A = 1000 · nb de points)
    assert np.isclose((ca["ind"] * ca["access_2sfca"]).sum(), 2000)


def test_unserved_is_zero(result):
    ca, _ = result
    assert ca.loc[2, "score"] == 0 and ca.loc[2, "score_2sfca"] == 0
