"""
Étape 6 – Optimisation : couverture maximale sous contrainte de budget.

Problème (Budgeted Maximum Coverage pondéré, NP-difficile) :
    choisir un ensemble S de sites (de types différents : Citiz, vélo, bus) tel que
    coût(S) <= B, en maximisant

        f(S) = Σ_cellules  w_i · max_{j ∈ S, j couvre i} v_j        (0 si i non couverte)

avec
    w_i : poids de la cellule = population (projetée) × (1 + λ·besoin_i)
    v_j : valeur prédite du site j (propension relative du modèle, cf. model.py)
et en ne comptant que la population NON déjà desservie par l'offre existante du même type
(« taking the existing offer into account » : w_i = 0 si déjà desservie).

Chaque cellule compte une seule fois, avec la valeur du MEILLEUR site qui la couvre
(c'est une fonction de type « facility location ») : f est monotone et sous-modulaire.
Gain marginal de j :  Σ_{i couverte par j} w_i · max(0, v_j − cur_i),  cur_i = meilleure valeur
déjà offerte à i. (Une version « premier arrivé » — v_j · Σ w_i des cellules encore non
couvertes — n'est pas une fonction d'ensemble : elle dépend de l'ordre de sélection et la
garantie ci-dessous ne s'y applique pas ; elle coïncide avec f quand toutes les v_j sont égales.)

L'algorithme glouton sur le ratio gain/coût (avec évaluation paresseuse, Minoux 1978)
combiné au meilleur site unique garantit au moins (1 - 1/e)/2 de l'optimum
(Khuller, Moss & Naor 1999) ; en pratique ~97 % sur les instances de validation
(tests/test_optimize.py, valeurs v_j hétérogènes).
"""
import heapq

import numpy as np


def coverage_value(cand_cells, cand_value, cell_weight, S):
    """f(S) = Σ_i w_i · max_{j∈S couvrant i} v_j (référence, utilisée par les tests)."""
    cur = np.zeros(len(cell_weight))
    for j in S:
        c = cand_cells[j]
        cur[c] = np.maximum(cur[c], cand_value[j])
    return float((np.asarray(cell_weight, float) * cur).sum())


def greedy_budgeted_coverage(cand_cells, cand_value, cand_cost, cell_weight, budget,
                             max_sites=None):
    """
    cand_cells : liste de np.ndarray (indices des cellules couvertes par chaque candidat)
    cand_value : np.ndarray, multiplicateur de valeur propre à chaque candidat (>=0)
    cand_cost  : np.ndarray, coût de chaque candidat (>0)
    cell_weight: np.ndarray, poids de chaque cellule (déjà à 0 si cellule déjà desservie)
    Renvoie (ordre des candidats choisis, gains marginaux de f, coût total).
    """
    w = np.asarray(cell_weight, float)
    cur = np.zeros(len(w))                    # meilleure valeur de site offerte à chaque cellule
    n = len(cand_cells)

    def gain(j):
        c = cand_cells[j]
        return float((w[c] * np.maximum(cand_value[j] - cur[c], 0.0)).sum())

    # tas max sur le ratio gain/coût (valeurs négatives pour heapq) ; les gains ne peuvent
    # que décroître (sous-modularité) : une borne supérieure périmée suffit (évaluation paresseuse)
    heap = [(-gain(j) / cand_cost[j], j) for j in range(n)]
    heapq.heapify(heap)
    chosen, gains, spent = [], [], 0.0
    while heap and (max_sites is None or len(chosen) < max_sites):
        neg_ratio, j = heapq.heappop(heap)
        if spent + cand_cost[j] > budget:
            continue                          # trop cher pour le budget restant (définitif)
        g = gain(j)
        if g <= 0:
            continue                          # gain nul : ne remontera jamais
        ratio = g / cand_cost[j]
        # évaluation paresseuse : si le ratio recalculé reste le meilleur, on le prend
        if heap and ratio < -heap[0][0] - 1e-12:
            heapq.heappush(heap, (-ratio, j))
            continue
        chosen.append(j)
        gains.append(g)
        spent += cand_cost[j]
        c = cand_cells[j]
        cur[c] = np.maximum(cur[c], cand_value[j])
    return np.array(chosen, dtype=int), np.array(gains, dtype=float), spent


def best_single(cand_cells, cand_value, cand_cost, cell_weight, budget):
    w = np.asarray(cell_weight, float)
    g = np.array([cand_value[j] * w[c].sum() if cand_cost[j] <= budget else -1.0
                  for j, c in enumerate(cand_cells)])
    return int(g.argmax()), float(g.max())


def optimize(cand_cells, cand_value, cand_cost, cell_weight, budget, max_sites=None):
    """Glouton + garde-fou du meilleur site unique (garantie (1-1/e)/2)."""
    chosen, gains, spent = greedy_budgeted_coverage(
        cand_cells, cand_value, cand_cost, cell_weight, budget, max_sites)
    if len(cand_cells) == 0:
        return chosen, gains, spent
    j, g1 = best_single(cand_cells, cand_value, cand_cost, cell_weight, budget)
    if g1 > gains.sum():
        return np.array([j]), np.array([g1]), float(cand_cost[j])
    return chosen, gains, spent
