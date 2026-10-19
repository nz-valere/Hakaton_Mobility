"""Tests de src/territories.py (référentiel EPCI, criblage) et du découpage par financeur."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import recommend as R, territories as T  # noqa: E402


def test_plm_arrondissements_mapped_to_their_epci():
    e = T.com_to_epci(["75112", "13205", "69381", "67482"])
    assert e[0] == "200054781"          # Métropole du Grand Paris
    assert e[1] == "200054807"          # Aix-Marseille-Provence
    assert e[2] == "200046977"          # Métropole de Lyon
    assert e[3] == C.EMS_EPCI


def test_ems_epci_matches_config_communes():
    assert set(T.epci_communes(C.EMS_EPCI)) == set(C.EMS_COMMUNES)
    assert T.area_of(C.EMS_EPCI) == "ems"
    assert T.area_of("200030195") == "epci:200030195"


def test_screen_counts_only_dense_unserved_population():
    n = 4
    cells = pd.DataFrame({"com": ["67482"] * n, "dep": "67", "ind": [100.0, 200.0, 300.0, 400.0],
                          "carfree_share": 0.3})
    F = pd.DataFrame({"n_citiz_r5": [1, 0, 0, 0], "n_carsharing_r5": [0, 1, 0, 0],
                      "dens_1k": [5000, 5000, 5000, 100], "d_citiz": [0, 500, 900, 3000]})
    p_ref = 0.5
    out = T.screen(cells, F, np.full(n, p_ref), p_ref)   # v = 1 partout
    r = out.iloc[0]
    assert r["epci"] == C.EMS_EPCI
    assert r["pop_dense_unserved"] == 300           # carreau 3 seul : dense et sans autopartage
    assert r["potential"] == 300
    assert np.isclose(r["share_carsharing_served"], 300 / 1000)
    assert r["statut"] == "extension"


def test_funders_have_separate_kinds():
    assert R.FUNDERS["citiz"][1] == ("citiz",)
    assert set(R.FUNDERS["collectivite"][1]) == {"bike", "bus"}
