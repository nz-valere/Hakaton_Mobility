"""Tests de src/usage.py et de src/collect_gbfs.py sur des relevés synthétiques."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402
from src import collect_gbfs, usage  # noqa: E402


def _collect(tmp_path, n=20):
    rows = []
    for k in range(n):
        ts = f"2026-10-20T{8 + k // 12:02d}:{(k % 12) * 5:02d}:00+00:00"
        rows.append((ts, 1, "A", 2, 2 if k % 2 == 0 else 1, 0))     # 2 voitures, 75 % du temps réservées
        rows.append((ts, 1, "B", 1, 0, 0))                          # jamais réservée
        if k < 5:
            rows.append((ts, 1, "C", 1, 1, 0))                      # trop peu de relevés
    pd.DataFrame(rows, columns=["ts_utc", "provider_id", "station_id", "n_vehicles", "n_reserved", "n_disabled"]) \
        .to_csv(tmp_path / "citiz_status_2026-10-20.csv", index=False)
    info = {"data": {"stations": [{"station_id": s, "name": [{"text": f"Station {s}", "language": "fr"}],
                                   "lat": 48.58 + i * 0.001, "lon": 7.75} for i, s in enumerate("ABC")]}}
    (tmp_path / "citiz_stations_p1_2026-10-20.json").write_text(json.dumps(info), encoding="utf-8")
    return tmp_path


def test_occupation_and_availability(tmp_path):
    u, period = usage.station_usage(_collect(tmp_path), min_snapshots=12)
    u = u.set_index("station_id")
    assert set(u.index) == {"A", "B"}                         # C écartée (5 relevés < 12)
    assert np.isclose(u.loc["A", "occupation"], 0.75)
    assert np.isclose(u.loc["A", "disponibilite"], 0.5)        # libre seulement quand 1 seule réservée
    assert u.loc["B", "occupation"] == 0 and u.loc["B", "disponibilite"] == 1
    assert u.loc["A", "saturee"] == (0.75 >= C.SATURATION_OCCUPANCY)
    assert u.loc["A", "name"] == "Station A"
    assert period["releves"] == 20


def test_collector_keeps_only_station_totals():
    vehicles = [{"vehicle_id": "v1", "station_id": "S", "lat": 1, "lon": 2, "is_reserved": True, "is_disabled": False},
                {"vehicle_id": "v2", "station_id": "S", "lat": 1, "lon": 2, "is_reserved": False, "is_disabled": True},
                {"vehicle_id": "v3", "home_station_id": "T", "is_reserved": False}]
    agg = collect_gbfs.aggregate(vehicles)
    assert agg == {"S": [2, 1, 1], "T": [1, 0, 0]}            # pas d'identifiant ni de position de véhicule
