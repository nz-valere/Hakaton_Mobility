"""Tests de src/frequency.py (GTFS synthétique) et du facteur de service des arrêts de bus (recommend)."""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import frequency, geo, recommend  # noqa: E402

LON, LAT = 7.75, 48.58          # Strasbourg (métropole, crs_id 0)


def _gtfs(tmp_path, tuesday="1"):
    """2 lignes : R1 (8 départs par sens aux arrêts S1 et S2, voisins), R2 (2 départs, S1) ; S3 loin."""
    stops = pd.DataFrame({"stop_id": ["S1", "S2", "S3"], "stop_name": ["A", "B", "C"],
                          "stop_lat": [LAT, LAT + 0.0005, LAT + 0.05], "stop_lon": [LON, LON + 0.0005, LON + 0.05]})
    routes = pd.DataFrame({"route_id": ["R1", "R2"], "route_short_name": ["1", "2"], "route_type": ["3", "3"]})
    trips, st = [], []
    for r, n, dirs in (("R1", 8, (0, 1)), ("R2", 2, (0,))):
        for d in dirs:
            for k in range(n):
                tid = f"{r}_{d}_{k}"
                trips.append((r, "WD", tid, d))
                for s, (stop, minute) in enumerate((("S1", 0), ("S2", 2))):
                    if r == "R2" and stop == "S2":
                        continue
                    hh = 8 + k
                    st.append((tid, f"{hh:02d}:{minute:02d}:00", f"{hh:02d}:{minute:02d}:00", stop, s + 1))
    trips = pd.DataFrame(trips, columns=["route_id", "service_id", "trip_id", "direction_id"])
    st = pd.DataFrame(st, columns=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"])
    cal = pd.DataFrame({"service_id": ["WD"], "monday": ["1"], "tuesday": [tuesday], "wednesday": ["1"],
                        "thursday": ["1"], "friday": ["1"], "saturday": ["0"], "sunday": ["0"],
                        "start_date": ["20261101"], "end_date": ["20261130"]})
    path = tmp_path / "gtfs_test.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, df in (("stops.txt", stops), ("routes.txt", routes), ("trips.txt", trips),
                         ("stop_times.txt", st), ("calendar.txt", cal)):
            z.writestr(name, df.to_csv(index=False))
    return path


def _cells(lons, lats):
    crs, x, y = geo.project(np.array(lons), np.array(lats))
    return pd.DataFrame({"crs_id": crs, "x": x, "y": y})


def test_departures_per_hour(tmp_path):
    lf, day = frequency.line_frequencies(_gtfs(tmp_path), "20261117")
    assert day == "20261117"
    h = C.FREQ_HOURS[1] - C.FREQ_HOURS[0]
    r1 = lf[(lf["stop_id"].str.endswith("S1")) & (lf["line"].str.contains(":R1:0"))]
    assert np.isclose(r1["dep_h"].iloc[0], 8 / h)
    assert set(lf["line"].str.rsplit(":", n=2).str[1]) == {"R1", "R2"}


def test_line_counted_once_and_weighted(tmp_path):
    lf, _ = frequency.line_frequencies(_gtfs(tmp_path), "20261117")
    cells = _cells([LON, LON + 0.05], [LAT, LAT + 0.05])
    fq = frequency.cell_frequency(cells, lf, radius=300, full=4.0)
    h = C.FREQ_HOURS[1] - C.FREQ_HOURS[0]
    # R1 passe à S1 et S2 (tous deux à < 300 m) : chaque sens compte une fois ; R2 : un sens
    expected = 2 * min(1, (8 / h) / 4) + min(1, (2 / h) / 4)
    assert np.isclose(fq["tc_freq_options"].iloc[0], expected)
    assert fq["tc_lines"].iloc[0] == 2
    # le carreau lointain n'a aucune ligne à 5 min (S3 n'est desservi par aucune course)
    assert fq["tc_freq_options"].iloc[1] == 0
    assert np.isfinite(fq["freq_nearest"].iloc[1])


def test_reference_date_fallback(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    z = zipfile.ZipFile(_gtfs(tmp_path / "a", tuesday="0"))
    assert frequency.active_services(z, "20261117") == set()
    z2 = zipfile.ZipFile(_gtfs(tmp_path / "b", tuesday="1"))
    day = frequency.reference_date(z2, "20251010")          # date hors GTFS -> mardi le plus chargé
    assert pd.Timestamp(day).weekday() == 1 and "20261101" <= day <= "20261130"


def test_bus_service_factor():
    F = pd.DataFrame({"freq_nearest": [8.0, 1.0, np.nan, 0.0]})
    q = recommend.bus_service_factor(F, np.arange(4))
    assert np.allclose(q, [1.0, 0.25, 1.0, C.FREQ_MIN_FACTOR])
    assert np.allclose(recommend.bus_service_factor(pd.DataFrame({"x": [1]}), np.arange(1)), [1.0])
