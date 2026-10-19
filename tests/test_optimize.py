"""Validation de l'optimiseur glouton contre la solution exacte (force brute) sur petites instances."""
import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.optimize import coverage_value, greedy_budgeted_coverage, optimize  # noqa: E402

BOUND = (1 - 1 / np.e) / 2


def brute_force(cells, value, cost, w, budget):
    """Optimum exact de f(S) = Σ w_i max_{j∈S} v_j sous coût(S) <= budget."""
    best, n = 0.0, len(cells)
    for k in range(1, n + 1):
        for S in itertools.combinations(range(n), k):
            if cost[list(S)].sum() <= budget:
                best = max(best, coverage_value(cells, value, w, S))
    return best


def naive_greedy(cells, value, cost, w, budget):
    """Glouton gain/coût NON paresseux (recalcule tout à chaque pas) : référence du lazy."""
    chosen, spent = [], 0.0
    while True:
        base = coverage_value(cells, value, w, chosen)
        best, bj = 0.0, None
        for j in range(len(cells)):
            if j in chosen or spent + cost[j] > budget:
                continue
            r = (coverage_value(cells, value, w, chosen + [j]) - base) / cost[j]
            if r > best + 1e-12:
                best, bj = r, j
        if bj is None:
            return chosen
        chosen.append(bj)
        spent += cost[bj]


def random_instance(rng, n_cells=60, n_cand=10, n_types=1, hetero=True):
    """Instance réaliste : candidats de plusieurs types (copies de cellules par type, comme
    recommend.solve), recouvrements entre voisins, valeurs v hétérogènes bornées comme VALUE_CLIP,
    coûts discrets (60 k / 45 k + détour) et budget couvrant quelques sites."""
    w0 = rng.gamma(1.0, 50, n_cells)
    w0[rng.random(n_cells) < 0.3] = 0.0                       # déjà desservies
    w = np.tile(w0, n_types)
    cells, value, cost = [], [], []
    for _ in range(n_cand):
        t = rng.integers(n_types)
        centre = rng.integers(n_cells)
        nb = np.unique(np.clip(centre + rng.integers(-4, 5, rng.integers(3, 8)), 0, n_cells - 1))
        cells.append(nb + t * n_cells)
        value.append(rng.uniform(0.05, 1.5) if hetero else 1.0)
        cost.append(60.0 if t < 2 else 45.0 + rng.uniform(0, 170))
    cost = np.array(cost)
    return cells, np.array(value), cost, w, cost.sum() * rng.uniform(0.2, 0.5)


def _ratios(n_types, hetero, n_inst=60, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_inst):
        cells, value, cost, w, budget = random_instance(rng, n_types=n_types, hetero=hetero)
        chosen, gains, spent = optimize(cells, value, cost, w, budget)
        assert spent <= budget + 1e-9
        # les gains renvoyés sont bien les gains marginaux de f (somme = f(S))
        assert np.isclose(gains.sum(), coverage_value(cells, value, w, chosen))
        opt = brute_force(cells, value, cost, w, budget)
        out.append(gains.sum() / opt if opt > 0 else 1.0)
    return np.array(out)


def test_greedy_close_to_optimum_uniform_value():
    r = _ratios(n_types=1, hetero=False)
    assert r.min() >= BOUND
    print(f"v uniformes : glouton / optimum moyenne {r.mean():.3f}, min {r.min():.3f}")


def test_greedy_close_to_optimum_heterogeneous_multitype():
    r = _ratios(n_types=3, hetero=True, seed=1)
    assert r.min() >= BOUND
    assert r.mean() >= 0.9
    print(f"v hétérogènes, 3 types : glouton / optimum moyenne {r.mean():.3f}, min {r.min():.3f}")


def test_lazy_equals_naive_greedy():
    rng = np.random.default_rng(2)
    for _ in range(40):
        cells, value, cost, w, budget = random_instance(rng, n_cand=12, n_types=3)
        lazy, _, _ = greedy_budgeted_coverage(cells, value, cost, w, budget)
        ref = naive_greedy(cells, value, cost, w, budget)
        assert np.isclose(coverage_value(cells, value, w, lazy), coverage_value(cells, value, w, ref))


def test_better_site_upgrades_overlap():
    # deux sites qui se recouvrent : le second (meilleur) n'apporte que l'écart de valeur
    cells = [np.array([0, 1]), np.array([1, 2])]
    value = np.array([0.5, 1.0])
    w = np.array([1.0, 1.0, 1.0])
    chosen, gains, _ = greedy_budgeted_coverage(cells, value, np.array([1.0, 1.0]), w, 2.0)
    assert list(chosen) == [1, 0]
    assert np.allclose(gains, [2.0, 0.5])            # f = 1·0.5 + 1·1 + 1·1 = 2.5


if __name__ == "__main__":
    test_greedy_close_to_optimum_uniform_value()
    test_greedy_close_to_optimum_heterogeneous_multitype()
    test_lazy_equals_naive_greedy()
    test_better_site_upgrades_overlap()
