"""Tests unitaires des briques non couvertes : population, offer, accessibility (rangs), scenarios,
app_data (couleurs, lecture tolérante), frequency (calendrier), walk_calibration, territories (risque)."""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import accessibility as A, offer as O, population as P  # noqa: E402


# --------------------------------------------------------------------------- population
def test_cell_key_unique_and_neighbour_arithmetic():
    x = np.array([4_000_000, 4_000_200, 4_000_000])
    y = np.array([2_800_000, 2_800_000, 2_800_200])
    k = P.cell_key(0, x, y)
    assert len(set(k)) == 3
    assert k[1] - k[0] == 1                 # colonne voisine : +1   (contrat de accessibility._grid_lookup)
    assert k[2] - k[0] == 10 ** 6           # ligne voisine   : +10^6
    assert P.cell_key(1, x[:1], y[:1])[0] != k[0]     # autre territoire, même x,y
    assert k.dtype == np.int64


# --------------------------------------------------------------------------- accessibility
def test_weighted_rank_ties_and_weights():
    r = A.weighted_rank(np.array([3.0, 1.0, 1.0, 2.0]), np.array([1.0, 1.0, 1.0, 2.0]))
    # poids cumulés triés : [1,1 | 2 | 1] / 5 ; ex aequo (valeur 1) -> milieu de leur classe = 1/5
    np.testing.assert_allclose(r, [4.5 / 5, 1 / 5, 1 / 5, 3 / 5])
    assert (0 <= r).all() and (r <= 1).all()


def test_wmedian():
    assert A.wmedian(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 10.0])) == 3.0
    assert np.isnan(A.wmedian(np.array([]), np.array([])))


# --------------------------------------------------------------------------- offer
@pytest.mark.parametrize("system,mode", [
    ({"name": "Citiz Grand Est", "form_factors": ["car"]}, "citiz"),
    ({"name": "Getaround", "form_factors": ["car"]}, "carsharing"),
    ({"name": "Lime Paris", "form_factors": ["bicycle", "scooter"]}, "scooter"),
    ({"name": "X", "form_factors": ["scooter_standing"]}, "scooter"),
    ({"name": "Vélhop", "form_factors": ["bicycle"]}, "bike"),
    ({"name": "Inconnu"}, "bike"),
])
def test_gbfs_mode(system, mode):
    assert O.gbfs_mode(system) == mode


def test_cluster_labels_single_linkage():
    x = np.array([0.0, 40.0, 80.0, 500.0])
    lab = O.cluster_labels(x, np.zeros(4), 50.0)
    assert lab[0] == lab[1] == lab[2] != lab[3]          # chaînage 0-40-80
    assert len(O.cluster_labels(np.array([]), np.array([]), 50.0)) == 0


def test_clean_coords_drops_nan_zero_and_abroad():
    pts = pd.DataFrame({"lon": [7.75, np.nan, 0.0, 13.4], "lat": [48.58, 48.0, 0.0, 52.5]})
    assert O.clean_coords(pts)["lon"].tolist() == [7.75]


def test_finalize_unique_ids_and_schema():
    out = pd.DataFrame({"mode": ["transit", "transit"], "src_key": ["g1", "g1"], "raw_id": ["a", "a"],
                        "name": ["A", "A"], "lon": [7.75, 7.76], "lat": [48.58, 48.58],
                        "source": "s", "operator": "o", "capacity": np.nan})
    df = O.finalize(out)
    assert df["offer_id"].is_unique
    assert df["crs_id"].dtype == np.int8
    assert set(df.columns) >= {"offer_id", "mode", "name", "lon", "lat", "crs_id", "x", "y", "source",
                               "operator", "capacity"}


# --------------------------------------------------------------------------- frequency
def _gtfs_calendar(tmp_path):
    p = tmp_path / "g.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
                                   "start_date,end_date\nS,0,1,0,0,0,0,0,20260101,20261231\n")
    return zipfile.ZipFile(p)


def test_active_services_independent_of_locale(tmp_path):
    import locale
    from src import frequency
    z = _gtfs_calendar(tmp_path)
    old = locale.setlocale(locale.LC_TIME)
    try:
        try:
            locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
        except locale.Error:
            pytest.skip("locale fr_FR indisponible")
        assert frequency.active_services(z, "20261117") == {"S"}   # mardi
    finally:
        locale.setlocale(locale.LC_TIME, old)


# --------------------------------------------------------------------------- walk_calibration
def test_min_duplicates_keeps_shortest_edge():
    from scipy import sparse
    from src.walk_calibration import _min_duplicates
    coo = sparse.coo_matrix((np.array([5.0, 3.0, 7.0]), (np.array([0, 0, 1]), np.array([1, 1, 2]))), shape=(3, 3))
    g = _min_duplicates(coo)
    assert g[0, 1] == 3.0 and g[1, 2] == 7.0 and g.nnz == 2


# --------------------------------------------------------------------------- scenarios
def test_scenarios_grid_shape_and_funder_isolation(monkeypatch):
    from src import recommend as R, scenarios as Sc
    calls = []

    def fake(area, citiz_budget, public_budget, equity_lambda, compare):
        calls.append((citiz_budget, public_budget))
        key = "citiz" if citiz_budget else "collectivite"
        df = pd.DataFrame({"financeur": [key], "code_commune": ["67482"], "cost_eur": [1.0]})
        return df, {"funders": {key: {"selected": {"n_sites": 1, "cost_eur": 1.0}}}}

    monkeypatch.setattr(R, "recommend_by_funder", lambda area, equity_lambda, compare, **b: fake(
        area, b["citiz_budget"], b["public_budget"], equity_lambda, compare))
    monkeypatch.setattr(Sc, "BUDGET_MAX", 3 * Sc.BUDGET_STEP)
    sites, resume = Sc.grid("ems")
    n = len(R.FUNDERS) * 3 * len(Sc.LAMBDAS)
    assert len(resume) == n == len(calls)
    assert all((c == 0) != (p == 0) for c, p in calls)          # un seul financeur par appel
    assert "com" in sites and "code_commune" not in sites
    assert resume[["financeur", "budget_eur", "equity_lambda"]].duplicated().sum() == 0


def test_scenarios_cache_names():
    from src import scenarios as Sc
    a, b, _ = Sc._cache_files("epci:200030195")
    assert ":" not in a.name and a.name.endswith("_sites.parquet") and b.name.endswith("_resume.parquet")


# --------------------------------------------------------------------------- app_data (sans Streamlit serveur)
def test_score_rgb_and_levels():
    from src import app_data as ad
    rgb = ad.score_rgb([0, 1, 50, 100, np.nan])
    assert rgb.dtype == np.uint8 and rgb.shape == (5, 3)
    assert tuple(rgb[0]) == ad.ZERO_COLOR and tuple(rgb[4]) == ad.ZERO_COLOR
    assert tuple(rgb[3]) == tuple(ad.RAMP[-1].astype(int))
    lab = ad.level_label([0, 10, 30, 60, 90])
    assert lab[0] == ad.LEVELS[0][1] and lab[-1] == ad.LEVELS[-1][1]


def test_strategy_and_field_lookup():
    from src import app_data as ad
    summ = {"comparison": {"lambda_0": {"pop_newly_served_distinct": 12.0, "eur_per_new_resident": 5},
                           "no_model_value_1": {"pop_from_zero_option": 3}}}
    assert ad.strategy(summ, "no_equity") is summ["comparison"]["lambda_0"]
    assert ad.field(ad.strategy(summ, "no_equity"), "distinct") == 12.0
    assert ad.field(ad.strategy(summ, "no_model"), "zero_to_one") == 3.0
    assert ad.strategy({}, "naive") is None
