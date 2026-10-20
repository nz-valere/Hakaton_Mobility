"""Tests de src/territories.py (référentiel EPCI, criblage) et du découpage par financeur."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import recommend as R, territories as T  # noqa: E402

# Les référentiels EPCI (data/raw) et les carreaux (data/interim) ne sont pas versionnés :
# sur un clone neuf, les tests qui les lisent sont sautés au lieu d'échouer.
HAS_RAW = (C.RAW / "communes_epci.json").exists() and (C.RAW / "epcis.json").exists()
needs_raw = pytest.mark.skipif(not HAS_RAW, reason="data/raw absent : python -m src.download static")
needs_cells = pytest.mark.skipif(not (C.INTERIM / "cells.parquet").exists(),
                                 reason="data/interim/cells.parquet absent : python -m src.population")


@pytest.fixture
def fake_epci(monkeypatch):
    T._epci_tables.cache_clear()
    monkeypatch.setattr(T, "_epci_tables", lambda: ({"67482": C.EMS_EPCI}, {C.EMS_EPCI: "Eurométropole"}))


@needs_raw
def test_plm_arrondissements_mapped_to_their_epci():
    e = T.com_to_epci(["75112", "13205", "69381", "67482"])
    assert e[0] == "200054781"          # Métropole du Grand Paris
    assert e[1] == "200054807"          # Aix-Marseille-Provence
    assert e[2] == "200046977"          # Métropole de Lyon
    assert e[3] == C.EMS_EPCI


@needs_raw
@needs_cells
def test_ems_epci_matches_config_communes():
    assert set(T.epci_communes(C.EMS_EPCI)) == set(C.EMS_COMMUNES)
    assert T.area_of(C.EMS_EPCI) == "ems"
    assert T.area_of("200030195") == "epci:200030195"


def test_screen_counts_only_dense_unserved_population(fake_epci):
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


def test_field_risk_discounts_failed_and_occupied_territories():
    r_nice, f_nice, _ = T.risk("200030195")          # Auto Bleue puis Mobilize Share : échecs répétés
    assert "echec_station" in f_nice and r_nice >= 0.5
    assert T.risk("243400017")[0] >= 0.4               # Montpellier : Modulauto hors GBFS
    assert T.risk(C.EMS_EPCI) == (0.0, "", "")         # territoire témoin, aucun signal
    assert T.risk("243100518")[0] < 0                  # Toulouse : réseau Citiz retenu par la Métropole
    for factors, _ in C.TERRITORY_RISK.values():
        assert set(factors) <= set(C.TERRITORY_RISK_WEIGHTS)
