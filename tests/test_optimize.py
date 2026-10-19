"""Validation de l'optimiseur glouton contre la solution exacte (force brute) sur petites instances."""
import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.optimize import optimize  # noqa: E402


def brute_force(cells, value, cost, w, budget):
    best = 0.0
    n = len(cells)
    for k in range(1, n + 1):
        for S in itertools.combinations(range(n), k):
            if cost[list(S)].sum() > budget:
                continue
            covered = np.zeros_like(w)
            tot = 0.0
            # valeur : chaque cellule compte une fois, avec la meilleure valeur de site
            for j in sorted(S, key=lambda j: -value[j]):
                m = covered[cells[j]] == 0
                tot += value[j] * w[cells[j]][m].sum()
                covered[cells[j]] = 1
            best = max(best, tot)
    return best


def test_greedy_close_to_optimum():
    rng = np.random.default_rng(0)
    ratios = []
    for _ in range(40):
        n_cells, n_cand = 60, 9
        w = rng.gamma(1.0, 50, n_cells)
        cells = [rng.choice(n_cells, rng.integers(3, 12), replace=False) for _ in range(n_cand)]
        value = np.ones(n_cand)
        cost = rng.uniform(1, 5, n_cand)
        budget = cost.sum() * 0.4
        chosen, gains, spent = optimize(cells, value, cost, w, budget)
        assert spent <= budget + 1e-9
        opt = brute_force(cells, value, cost, w, budget)
        ratios.append(gains.sum() / opt)
    assert min(ratios) >= (1 - 1 / np.e) / 2
    print(f"glouton / optimum : moyenne {np.mean(ratios):.3f}, min {np.min(ratios):.3f}")


if __name__ == "__main__":
    test_greedy_close_to_optimum()
