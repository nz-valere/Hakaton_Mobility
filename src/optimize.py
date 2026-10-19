"""
Étape 6 – Optimisation : couverture maximale sous contrainte de budget.

Problème (Budgeted Maximum Coverage, NP-difficile) :
    choisir un ensemble S de sites (de types différents : Citiz, vélo, bus) tel que
    coût(S) <= B, en maximisant  Σ_cellules  w_i · v_i · [i couverte par S]
avec
    w_i : poids de la cellule = population (projetée) × (1 + λ·besoin_i)
    v_i : valeur prédite (propension du modèle, cf. model.py) propre au type de site
et en ne comptant que la population NON déjà desservie par l'offre existante du même type
(« taking the existing offer into account »).

La fonction objectif est sous-modulaire monotone : l'algorithme glouton sur le ratio
gain/coût (avec évaluation paresseuse, Minoux 1978) combiné au meilleur site unique
garantit au moins (1 - 1/e)/2 de l'optimum (Khuller, Moss & Naor 1999) et, en pratique,
>95 % de l'optimum sur des instances de cette taille (cf. tests de validation).
"""
import heapq

import numpy as np


def greedy_budgeted_coverage(cand_cells, cand_value, cand_cost, cell_weight, budget,
                             max_sites=None):
    """
    cand_cells : liste de np.ndarray (indices des cellules couvertes par chaque candidat)
    cand_value : np.ndarray, multiplicateur de valeur propre à chaque candidat (>=0)
    cand_cost  : np.ndarray, coût de chaque candidat (>0)
    cell_weight: np.ndarray, poids de chaque cellule (déjà à 0 si cellule déjà desservie)
    Renvoie (ordre des candidats choisis, gains marginaux, coûts cumulés).
    """
    w = cell_weight.astype(float).copy()
    n = len(cand_cells)

    def gain(j):
        return cand_value[j] * w[cand_cells[j]].sum()

    # tas max sur le ratio gain/coût (valeurs négatives pour heapq)
    heap = [(-gain(j) / cand_cost[j], j) for j in range(n)]
    heapq.heapify(heap)
    chosen, gains, spent = [], [], 0.0
    while heap and (max_sites is None or len(chosen) < max_sites):
        neg_ratio, j = heapq.heappop(heap)
        if spent + cand_cost[j] > budget:
            continue                          # trop cher pour le budget restant
        g = gain(j)
        if g <= 0:
            continue
        ratio = g / cand_cost[j]
        # évaluation paresseuse : si le ratio est toujours le meilleur, on le prend
        if heap and ratio < -heap[0][0] - 1e-12:
            heapq.heappush(heap, (-ratio, j))
            continue
        chosen.append(j)
        gains.append(g)
        spent += cand_cost[j]
        w[cand_cells[j]] = 0.0                # ces cellules sont désormais desservies
    return np.array(chosen, dtype=int), np.array(gains), spent


def best_single(cand_cells, cand_value, cand_cost, cell_weight, budget):
    g = np.array([cand_value[j] * cell_weight[c].sum() if cand_cost[j] <= budget else -1
                  for j, c in enumerate(cand_cells)])
    return int(g.argmax()), float(g.max())


def optimize(cand_cells, cand_value, cand_cost, cell_weight, budget, max_sites=None):
    """Glouton + garde-fou du meilleur site unique (garantie d'approximation)."""
    chosen, gains, spent = greedy_budgeted_coverage(
        cand_cells, cand_value, cand_cost, cell_weight, budget, max_sites)
    j, g1 = best_single(cand_cells, cand_value, cand_cost, cell_weight, budget)
    if g1 > gains.sum():
        return np.array([j]), np.array([g1]), float(cand_cost[j])
    return chosen, gains, spent
