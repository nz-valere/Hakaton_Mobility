# Démarche technique – Mobili'Score

Ce document s'adresse à un data scientist qui veut évaluer la méthode ou reprendre le travail. Toutes les valeurs citées viennent des fichiers de `outputs/`, et le fichier source est indiqué à chaque fois. Les paramètres sont dans `Config.py` (importé `C`) : les modifier ne demande aucun changement de code.

Sommaire :

1. Périmètre
2. Indicateur d'accessibilité
3. Offre de transport
4. Modèle de valeur d'un site
5. Optimisation
6. Coûts et CO2
7. Éthique
8. Limites reconnues
9. Pistes, dont Microsoft Fabric
10. Reprendre le travail

---

## 1. Périmètre

### Objectifs 1 et 2 (diagnostic) : France entière, DROM inclus quand les données le permettent

- **Population** : INSEE Filosofi 2021, carreaux de 200 m. Ce jeu couvre **la Métropole, la Martinique et La Réunion**. **Il ne couvre ni la Guadeloupe, ni la Guyane, ni Mayotte**. Les points d'offre situés dans ces trois territoires sont bien chargés (`C.FRANCE_BBOXES`), mais ils reçoivent `crs_id = -1` et n'entrent pas dans le calcul, faute de population au carreau. On n'a pas voulu substituer une population communale, qui aurait rendu l'indicateur incohérent d'un territoire à l'autre.
- Le diagnostic porte sur **2 324 577 carreaux habités** et **63,8 M d'habitants** : 62,6 M en Métropole, 0,31 M en Martinique et 0,88 M à La Réunion (`access_summary.json`).
- Projections : trois CRS métriques, EPSG:3035 (Métropole), EPSG:5490 (Martinique) et EPSG:2975 (La Réunion). Voir `src/geo.py`.

### Objectif 3 (recommandation) : étude de cas sur l'Eurométropole de Strasbourg (EMS)

L'énoncé autorise à restreindre le périmètre si le choix est justifié. Nos raisons :

1. **Citiz y est implanté**. On peut donc mesurer comment l'outil complète un réseau existant, pas seulement simuler une arrivée. Dans l'emprise, `offer.parquet` compte 184 points Citiz, 767 arrêts de bus et de tram, 38 stations vélo et 13 gares. **46,5 %** des 445 537 habitants de la zone sont déjà à 5 min d'une station Citiz ou d'autopartage (`recommendations_summary.json`, `zone.already_served_share`), contre 3,5 % au niveau national.
2. **Les données y sont exceptionnellement complètes** : GTFS CTS (tram et bus), GTFS Fluo 67 (cars interurbains), GBFS Vélhop, GBFS Citiz Grand Est. Ces sources servent de contrôle à l'agrégat national.
3. **Le réseau piéton OSM** de l'EMS sert de terrain de calibration du rayon de marche (section 2). La recommandation s'appuie donc sur un territoire où l'approximation est mesurée.
4. La zone **mêle un centre dense et des communes périurbaines peu denses**. C'est exactement la tension d'équité soulevée par l'énoncé.

**La méthode n'est pas propre à Strasbourg.** `python -m src.recommend --dep 54` produit la même analyse pour la Meurthe-et-Moselle (`recommendations_dep54.csv` et `recommendations_summary_dep54.json`). Les modèles sont entraînés sur toute la France.

---

## 2. Indicateur d'accessibilité

### 2.1 Le rayon « 5 minutes » : 282 m calibrés (`src/walk_calibration.py`)

Cinq minutes à 4,8 km/h représentent **400 m de réseau piéton** (`C.WALK_NETWORK_M`). Calculer une isochrone réseau pour 2,3 M de carreaux était hors de portée en 2,5 jours sans base de graphe. On approxime donc l'isochrone par un **cercle euclidien de rayon r = 400 / détour**, et on calibre le détour sur données réelles.

- **Graphe** : réseau piéton OSM de l'EMS, obtenu via Overpass. Il compte 237 399 nœuds et 264 566 arêtes ; on garde la plus grande composante connexe.
- **Origines** : 400 carreaux tirés **proportionnellement à la population**, ce qui mesure le détour vu des habitants. Le Dijkstra est borné à 1 200 m et produit 680 492 paires.
- **Trois estimateurs**, chacun avec un IC 95 % obtenu par bootstrap sur les origines :

| Estimateur | Rayon | IC 95 % |
|---|---|---|
| 400 / ratio médian réseau/vol d'oiseau (médiane 1,344) | 297,6 m | 295–300 m |
| frontière à 50 % : P(réseau ≤ 400 m \| euclidien = r) = 0,5 | 289,3 m | 285–293 m |
| **égalité des effectifs (retenu)** | **282 m** | 278–286 m |

- **Pourquoi l'égalité des effectifs** : notre indicateur est un **comptage** (nombre d'options, habitants servis). Le critère retenu choisit r tel que le cercle contienne en moyenne autant de nœuds que l'isochrone réseau. Les faux positifs (un arrêt proche mais derrière une voie ferrée) compensent alors les faux négatifs, et le comptage est sans biais. Le **détour retenu vaut 1,418** (IC 95 % : 1,399–1,439).
- **Validation sur les vrais points d'offre** (`walk_calibration.json` → `validation`) : 1 000 points d'offre de l'EMS et 2 398 carreaux, soit 435 398 habitants. Pour chaque couple, on calcule la vraie distance réseau et on compare au cercle :

| Rayon | Précision (pop.) | Rappel (pop.) | Biais de comptage | MAE comptage | Spearman |
|---|---|---|---|---|---|
| **282 m (retenu)** | **0,924** | **0,985** | **+5 %** | **0,82** | **0,844** |
| 308 m (détour par défaut 1,30) | 0,906 | 0,994 | +24 % | 1,00 | 0,832 |
| 400 m sans détour | 0,861 | 1,000 | +101 % | 3,14 | 0,741 |

  Un cercle de 400 m, choix naïf fréquent, **double** le nombre d'options comptées. Le rayon calibré ramène ce biais à +5 %. La part de population réellement desservie sur réseau est de 83,9 %, contre 89,4 % estimée par le cercle de 282 m.

### 2.2 Définition de l'indicateur (`src/accessibility.py`)

Pour chaque carreau i, on regarde les points d'offre à ≤ 282 m de son centre :

- `n_<mode>` : nombre de points du mode.
- `n_options` = Σ `C.MODE_WEIGHT[mode]` × `n_<mode>`. Les poids valent 1 par défaut, conformément à l'énoncé (« nombre d'options »).
- `n_modes` : diversité, c'est-à-dire le nombre de modes distincts.
- `pop_catchment` : habitants qui partagent ce voisinage.
- `access_2sfca` : *Two-Step Floating Catchment Area* (Luo & Wang 2003).
- **Score de 0 à 100**, du plus froid au plus chaud. Il vaut **0 s'il n'y a aucune option**. Sinon, il vaut 1 + 99 × le rang-percentile national (pondéré par la population) parmi les carreaux desservis. Un rang plutôt qu'une valeur brute, parce que les distributions sont à queue très lourde. Le rang se lit directement : « score 80 = mieux doté que 80 % des habitants desservis ».

### 2.3 Pourquoi `n_options` plutôt que le 2SFCA pour le score affiché

« Options par habitant » admet deux lectures :

- **options accessibles depuis le domicile de chaque habitant**, mesurées au carreau et pondérées par la population dans tous les agrégats. C'est **notre choix** (`C.SCORE_BASIS = "n_options"`).
- **offre divisée par la population qui la partage** (2SFCA). Sans fréquence ni capacité par arrêt, ce ratio pénalise la densité au lieu de mesurer une saturation. Un hameau qui a un arrêt pour 30 habitants devient « chaud », et le centre de Strasbourg « froid ». D'après la docstring de `accessibility.py`, le score moyen vaut 82 pour les carreaux desservis peu denses contre 28 pour Strasbourg en 2SFCA, et 23 contre 58 en `n_options`.

Les deux scores sont exportés (`score_options`, `score_2sfca`) pour l'analyse de sensibilité. Au niveau national, leurs moyennes sont presque identiques (32,3 et 32,3), mais elles divergent fortement en Martinique (37,3 contre 59,0).

### 2.4 Population servie par point d'offre (objectif 2)

Pour chaque point d'offre (`stations_served.parquet`), on calcule :

- `pop_served` : habitants à ≤ 282 m ;
- `households_served` ;
- `pop_served_exclusive` : habitants dont c'est le seul point du mode, donc ceux qui perdraient l'accès s'il fermait.

Population servie médiane par point (`access_summary.json`) :

| Mode | Population médiane servie |
|---|---|
| Arrêt de bus, tram ou métro | 289 |
| Gare | 285 |
| Autopartage hors Citiz | 453 |
| Station vélo | 1 643 |
| Station Citiz | 1 750 |
| Zone free-floating | 2 559 |

---

## 3. Offre de transport : classification et dédoublonnage (`src/offer.py`)

**207 973 points d'offre** après dédoublonnage :

| Mode | Points |
|---|---|
| bus, tram, métro | 174 047 |
| free-floating | 22 836 |
| vélo en libre-service | 5 711 |
| train | 3 392 |
| Citiz | 1 570 |
| autre autopartage | 417 |

- **GTFS** : on part de l'agrégat national transport.data.gouv.fr, qui n'est pas dédoublonné. On garde seulement les quais (`location_type` 0). On **exclut** ce qui n'est pas une offre de proximité ouverte à tous au quotidien : cars longue distance (FlixBus, BlaBlaCar Bus), ferries, covoiturage, TAD zonal (points virtuels sur réservation) et réseaux purement scolaires.
- **Train ou transit** : le fichier n'a pas de `route_type`. On s'appuie sur les jeux ferroviaires (SNCF, TER régionaux), sur les identifiants SNCF normalisés (`OCETrain`, `OCETGV`…) et sur les quais IDFM présents dans le jeu Transilien. Les autocars TER (`OCECar`) restent en transit.
- **GBFS** (catalogue MobilityData), quatre catégories :
  - nom contenant « Citiz » → `citiz` ;
  - autre système de voitures → `carsharing` (Getaround n'expose pas de stations) ;
  - opérateurs free-floating (Bird, Dott, Lime, Voi…) → `scooter`, quelle que soit la flotte. Leurs « stations » sont des zones virtuelles, qu'on isole pour que `bike` désigne bien le vélo à stations, objet des recommandations ;
  - autres systèmes vélo → `bike`.
- **Dédoublonnage par mode** : on relie par KD-tree les points du même mode trop proches, puis chaque composante connexe devient un point, son centroïde. Les seuils :
  - **50 m** en général (un carrefour, des quais de part et d'autre de la rue) ;
  - **150 m** pour les gares (quais TER, TGV et Transilien publiés à des positions distinctes) ;
  - **15 m** pour le free-floating (zones très denses partagées entre opérateurs).

  Le chaînage (*single linkage*) peut fusionner des points plus éloignés que le seuil. L'extension maximale des groupes est affichée pour contrôle.
- **Contrôle sur Strasbourg** : `check_strasbourg()` compare les arrêts de l'agrégat avec le GTFS CTS officiel.

---

## 4. Modèle de valeur d'un site (`src/model.py`)

### 4.1 Formulation : l'offre existante révèle la demande

On entraîne un modèle **par type d'équipement** : Citiz/autopartage, vélo, bus.

- **Cible** : le carreau a au moins un point du type à ≤ 282 m.
- **Lecture** : appliquée à un carreau **non** desservi, la probabilité prédite mesure à quel point il ressemble aux sites que les opérateurs ont choisis et font vivre. C'est la **valeur du site**.
- **Unité d'observation** : le carreau habité de 200 m.
- **29 variables** :
  - population et ménages à 5 min ;
  - densité, revenu, pauvreté, âges, logement collectif et social, propriétaires, dans des fenêtres de 1 et 3 km ;
  - population de la commune et distance à son centre ;
  - motorisation (RP 2021) ;
  - offre **des autres modes** : nombre de points à 5 min et à 1 km, distance au plus proche.
- **Anti-fuite** : les modes cibles sont exclus des variables (`C.KIND_EXCLUDED_FEATURE_MODES`), car « il y a déjà une station à côté » serait une fuite triviale. Le modèle vélo exclut aussi le free-floating, à cause des flottes GBFS mixtes.

### 4.2 Apprentissage positif-non étiqueté (PU)

Un carreau sans station n'est pas forcément un mauvais site : il est peut-être simplement hors du périmètre de l'opérateur. On n'apprend donc **que dans les communes où le réseau du type opère**, car là, l'absence est informative. Les effectifs (`model_metrics.json`) :

| Type | Carreaux d'apprentissage | Positifs | Départements |
|---|---|---|---|
| Citiz | 107 672 | 8,4 % | 80 |
| Vélo | 133 039 | 16,3 % | 66 |
| Bus | 250 000, sous-échantillonnés sur 1 715 294 éligibles | 28,7 % | 98 |

Il reste un biais PU résiduel. Sous l'hypothèse SCAR (Elkan & Noto 2008), le classement n'est pas affecté. On n'utilise donc la propension **qu'en relatif** : `v = p / p_ref`, où `p_ref` est la propension médiane des carreaux déjà desservis.

### 4.3 Évaluation : validation croisée **spatiale**

On utilise `GroupKFold` en 5 plis, **groupés par département**. Une validation aléatoire mesurerait surtout l'autocorrélation spatiale, puisque les carreaux voisins d'un même réseau seraient à la fois en apprentissage et en test. Trois modèles sont comparés : HistGradientBoosting, régression logistique, et une heuristique « population seule » (`pop_only`). Métriques agrégées sur les plis (*pooled*) :

| Type | Modèle | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|---|
| Citiz | **HGB (retenu)** | **0,896** | **0,456** | 0,0589 |
| | logistique | 0,884 | 0,436 | 0,0587 |
| | population seule | 0,815 | 0,262 | 0,0684 |
| Vélo | HGB | 0,866 | 0,613 | 0,0951 |
| | **logistique (retenue)** | **0,873** | **0,639** | 0,0904 |
| | population seule | 0,826 | 0,526 | 0,1042 |
| Bus | **HGB (retenu)** | **0,854** | **0,707** | 0,1352 |
| | logistique | 0,847 | 0,696 | 0,1375 |
| | population seule | 0,834 | 0,673 | 0,1434 |

- **Critère de sélection** : la PR-AUC agrégée. Elle est plus pertinente que la ROC-AUC quand les positifs sont rares (8 % pour Citiz).
- **Gain sur la baseline** : pour Citiz, la PR-AUC passe de 0,26 à 0,46. Le gain est net pour Citiz et le vélo, modeste pour le bus, où la population explique déjà l'essentiel.
- **Variabilité entre plis** : l'écart-type de la PR-AUC vaut 0,06 (Citiz), 0,12 (vélo) et 0,02 (bus). Les performances varient d'un territoire à l'autre.
- **Importance par permutation** (baisse de PR-AUC) : la variable dominante est toujours `men_r5`, les ménages à 5 min (0,28 pour Citiz, 0,21 pour le vélo, 0,35 pour le bus). Suivent, pour Citiz, la taille de la commune, la part des 18-39 ans et la distance au transport en commun.
- Figures : `outputs/figures/model_<type>_curves.png` (ROC, PR, calibration) et `model_<type>_importance.png`.

### 4.4 Ce que le modèle n'apporte PAS

- **La capacité Citiz** (nombre de véhicules à installer) n'est **pas** mieux prédite qu'une baseline. Spearman : 0,44 pour HGB contre 0,46 pour la population seule. MAE : 1,53 véhicule contre 1,49 pour la moyenne. On ne prétend donc pas dimensionner les stations : l'outil dit **où**, pas **combien de voitures**. Pour le vélo, en revanche, la capacité est mieux prédite (Spearman 0,74 contre 0,66 ; MAE 13,2 contre 18,7 places).
- La propension n'est **pas une fréquentation** : c'est une ressemblance avec les sites existants. Elle hérite donc des biais des choix passés des opérateurs (voir section 7).

---

## 5. Optimisation (`src/optimize.py`, `src/recommend.py`)

### 5.1 Problème

Il s'agit d'un **Budgeted Maximum Coverage**, problème NP-difficile. On choisit un ensemble S de sites (Citiz, vélo, bus) tel que coût(S) ≤ B, en maximisant :

```
Σ_carreaux  w_i · v_j · [i couvert par un site j de S, et i non déjà desservi par ce type]
w_i = pop_2040_i × (1 + C.EQUITY_SCALE · λ · besoin_i)          (λ = 0,5 → poids ×1 à ×3)
besoin_i = 0,4·rang(pauvreté) + 0,2·rang(ménages sans voiture) + 0,4·rang(faible accès actuel)
v_j = clip(p_j / p_ref, 0,05 ; 1,5)
```

- **Candidats** : centres des carreaux habités non desservis par le type. Un arrêt de bus n'est candidat qu'à ≤ 1 500 m d'un arrêt existant (un détour de ligne, pas une ligne nouvelle).
- **Offre existante** : un carreau déjà desservi par le type a un poids nul pour ce type. C'est la réponse à « taking the existing offer into account ».
- **Population projetée** : Omphale, scénario central, interpolé jusqu'en 2040.

### 5.2 Algorithme et garantie

L'objectif est **sous-modulaire monotone**. On applique un **glouton sur le ratio gain/coût** avec évaluation paresseuse (Minoux 1978), qu'on compare au **meilleur site unique**. Cette combinaison garantit au moins **(1 − 1/e)/2 ≈ 0,316** de l'optimum (Khuller, Moss & Naor 1999).

**Test contre la force brute** (`tests/test_optimize.py`, 40 instances aléatoires de 9 candidats) : le glouton atteint en moyenne **97,3 %** de l'optimum exact, et **88,4 %** au pire.

### 5.3 Enveloppes et quota : des choix normatifs, paramétrables

Sans contrainte, l'optimiseur met presque tout sur le vélo, qui est le moins cher par habitant desservi. Il ne sert alors que les zones denses. Sur Strasbourg, la variante `global_pool_no_split_no_quota` donne 31 stations vélo et 2 stations Citiz. On a donc introduit deux règles, appliquées en étapes successives (chaque étape voit les sites précédents comme offre existante) :

1. **Quota peu dense** : 15 % du budget (`C.LOW_DENSITY_BUDGET_SHARE`) est réservé aux candidats dont la densité à ~1 km est inférieure à 1 500 hab/km².
2. **Enveloppes par type** : 40 % pour Citiz, 30 % pour le vélo, 30 % pour le bus (`C.BUDGET_SPLIT`), parce que les financeurs sont distincts. Le reliquat est réalloué globalement.

**Ce sont des choix politiques, pas des résultats du modèle.** Ils sont exposés dans `Config.py`, et l'option `--no-split` les désactive. Leur coût est chiffré (`recommendations_summary.json`, Strasbourg, même budget) :

| Stratégie | Sites | Nouveaux desservis | €/nouvel habitant | CO2 évité (t/an) | Part dans les déciles 1-3 | Part en zone peu dense |
|---|---|---|---|---|---|---|
| **Recommandée** (λ = 0,5, enveloppes, quota) | 28 (14 vélo, 12 Citiz, 2 bus) | **68 465** | 28,9 | **105,6** | **50,4 %** | 5,8 % |
| λ = 0 (efficacité pure) | 28 | 67 794 | 29,2 | 105,6 | 47,6 % | 5,9 % |
| sans quota peu dense | 28 | 76 793 | 25,8 | 114,2 | 50,0 % | 0 % |
| sans enveloppes ni quota | 33 (31 vélo, 2 Citiz) | 90 324 | 21,9 | 35,2 | 36,7 % | 0 % |
| **naïve** (population seule, sans modèle ni offre existante) | 32 | 39 067 | 49,4 | 22,2 | 52,6 % | 0 % |

Ce tableau se lit ainsi :

- **Prendre en compte l'offre existante** est ce qui rapporte le plus. La stratégie naïve place des sites là où les habitants sont déjà desservis : elle n'atteint que 39 067 nouveaux habitants, contre 68 465.
- **Le quota peu dense** coûte environ 8 300 nouveaux desservis. Il garantit qu'une partie de l'investissement va aux communes périurbaines.
- **Les enveloppes** coûtent environ 13 500 nouveaux desservis (90 324 contre 76 793, sans quota dans les deux cas). En échange, le CO2 évité est multiplié par 3,2 (114,2 t contre 35,2 t), car l'autopartage évite beaucoup plus de km en voiture qu'une station vélo, et la part des déciles 1-3 progresse (50,0 % contre 36,7 %).
- **λ = 0,5** change peu le total : 67 794 contre 68 465 nouveaux desservis. En revanche, il augmente la part des déciles 1-3 de 47,6 % à 50,4 %.

---

## 6. Coûts et CO2

### 6.1 Coûts (`C.COSTS`, horizon de 5 ans)

Formule : coût = capex + opex × 5.

| Équipement | Capex | Opex/an | Coût sur 5 ans |
|---|---|---|---|
| Station Citiz (1 véhicule) | 25 000 € | 7 000 € | 60 000 € |
| Station vélo légère (10 vélos) | 30 000 € | 6 000 € | 60 000 € |
| Arrêt de bus (quai PMR + abri) | 35 000 € | 2 000 € | 45 000 € + détour |

Pour un arrêt de bus, le surcoût annuel d'exploitation du détour vaut 2·d/1000 km × 30 passages/jour × 365 × 5 €/km, où d est la distance à l'arrêt existant. Les deux arrêts recommandés à Strasbourg coûtent ainsi 207 412 € et 212 812 € (`recommendations.csv`).

**Ce sont des hypothèses d'ordre de grandeur, à valider par Citiz et l'Eurométropole.**

### 6.2 CO2 évité (`recommend.evaluate()`)

| Équipement | Formule |
|---|---|
| Citiz | adhérents = min(130 000 / 2 800 ≈ 46,4 par véhicule ; nouveaux desservis × pénétration × v) × 0,5 actifs × 1 500 km évités/an × 218 gCO2e/km |
| Vélo | 15 trajets/j × v × 365 × 2,5 km × 15 % de report modal × 218 g/km |
| Bus | nouveaux desservis × 0,15 montée/j × v × 365 × 4 km × 20 % de report × (218 − 113) g/km − km-véhicule du détour × 1,1 kg/km |

- La pénétration Citiz vaut 5,86 %. C'est le rapport entre les conducteurs Citiz et les 2 219 041 habitants à 5 min d'une station Citiz en France (`model_metrics.json`).
- Sources : impactco2.fr (ADEME, Base Empreinte) et l'enquête nationale sur l'autopartage ADEME/6t (2022). Le nombre de conducteurs et de véhicules Citiz vient de l'énoncé.
- **Bilan pour Strasbourg** : 105,6 t de CO2 évitées par an. Le détail par site est dans `recommendations.csv` : 89,9 t pour les 12 stations Citiz, 8,8 t pour les 14 stations vélo et 6,8 t pour les 2 arrêts de bus.
- Le bilan d'un arrêt de bus peut être **négatif** si le détour génère plus de km-véhicule que le report modal n'en évite. C'est le cas des deux arrêts retenus en Meurthe-et-Moselle (−1,75 et −1,24 t/an, `recommendations_dep54.csv`).

---

## 7. Éthique

### 7.1 Équité : la courbe en U

Part des habitants sans aucune option à 5 min, par décile national de revenu par habitant du carreau (`access_summary.json`) :

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---|---|---|---|---|---|---|---|---|
| 17,9 % | 28,6 % | 37,2 % | 42,6 % | 44,5 % | 44,9 % | 43,6 % | 40,1 % | 35,7 % | 25,2 % |

- **Les plus modestes ne sont pas les plus mal desservis.** Notre hypothèse, non testée : ils vivent davantage dans les quartiers denses, bien desservis par le bus.
- **Les déciles intermédiaires sont les plus exposés.** Hypothèse, également non testée : ils vivent davantage dans le pavillonnaire et le périurbain.

C'est pourquoi le besoin combine **pauvreté, absence de voiture et faible accès actuel**, et non le revenu seul. La recommandation est ensuite contrôlée sur deux indicateurs :

- la part des nouveaux desservis dans les 3 premiers déciles de la zone : 50,4 % ;
- la part en zone peu dense : 5,8 %, malgré un quota de 15 % du budget. Un site en zone peu dense couvre beaucoup moins d'habitants.

**Risque de ne servir que les zones déjà bien desservies.** Il est neutralisé de deux façons : les carreaux déjà desservis par un type ont un poids nul pour ce type, et le quota peu dense réserve une part du budget au périurbain.

**Biais du modèle.** Il apprend des choix passés des opérateurs, qui privilégient les zones denses, jeunes et aisées. Il pourrait reproduire ces choix. Trois garde-fous :

- la valeur est plafonnée (`VALUE_CLIP`) ;
- le poids d'équité agit indépendamment du modèle ;
- le tableau de la section 5.3 compare toujours avec λ = 0 et la stratégie naïve.

### 7.2 Stigmatisation

- **Vocabulaire** : l'interface parle d'**« offre à développer »** et de score « froid / chaud », jamais de quartier « mal desservi » ou « pauvre ».
- **Rangs relatifs** : les rangs de besoin sont calculés **à l'intérieur de la zone étudiée**. L'outil compare des quartiers d'un même territoire, sans étiquette absolue.
- **Pas de publication par commune** : aucune variable sociale n'est publiée au carreau, et aucun classement des communes « les moins bien loties » n'est mis en avant.

### 7.3 Vie privée : seuil de 11 ménages

- **Règle INSEE** : Filosofi impute déjà les caractéristiques des carreaux de moins de 11 ménages (`C.PRIVACY_MIN_HOUSEHOLDS`).
- **Indicateurs d'accessibilité** : ils sont purement géographiques (nombre d'arrêts) et peuvent être cartographiés au carreau.
- **Statistiques socio-économiques** : toute statistique de revenu, de pauvreté ou de motorisation n'est affichée qu'**agrégée sur au moins 11 ménages**. La colonne `privacy_ok` est fournie dans `cells_access.parquet`.
- **Ordre de grandeur** : seuls 22,7 % des carreaux habités atteignent ce seuil, mais ils regroupent 82,1 % de la population. Le reste correspond aux zones très peu denses, précisément celles que l'énoncé signale.
- **Dans l'application** (`src/app_data.py`), un carreau sous le seuil prend la moyenne de son carré de 1 km ; si ce carré est lui-même sous le seuil, il est masqué.
- **Dans la recommandation**, les parts (pauvreté, sans voiture) ne sont publiées que si la zone servie compte au moins 11 ménages.

### 7.4 Empreinte carbone

Voir la section 6.2. Les hypothèses sont prudentes : 50 % d'adhérents actifs et 1 500 km évités par an. Le bilan net des arrêts de bus est compté, détour inclus.

---

## 8. Limites reconnues

1. **Le rayon euclidien n'est pas le réseau.** Le détour est calibré à Strasbourg, puis appliqué partout. Dans les territoires au réseau moins maillé (rural, relief, DROM), il est probablement sous-estimé, et l'accès donc surestimé. Il faudrait refaire la calibration sur d'autres territoires.
2. **Saturation de `value_rel` à 1,5.** Sur les meilleurs sites, la valeur relative atteint le plafond : c'est le cas de 11 stations vélo sur 14, d'1 arrêt de bus sur 2 et d'1 station Citiz sur 12 (`recommendations.csv`). Le modèle ne départage alors plus les sites, et c'est la population qui décide. Le plafond limite l'influence d'une propension mal calibrée, mais écrase l'information en haut de la distribution.
3. **Usage Citiz plafonné.** Pour 11 stations Citiz sur 12, `usage_pred` atteint 46,4 adhérents (130 000 / 2 800), ce qui donne un CO2 identique (7,59 t/an) d'un site à l'autre. Le CO2 ne départage pas les sites Citiz. De même, la capacité Citiz n'est pas prédite mieux que la baseline (section 4.4).
4. **L'emprise EMS est une boîte englobante**, `C.STRASBOURG_BBOX`, et non la liste officielle des communes membres. Elle peut inclure des communes voisines hors Eurométropole et en tronquer d'autres en bordure. Il faudrait filtrer par code commune.
5. **Arrêts scolaires.** Les réseaux purement scolaires sont exclus, mais les réseaux « urbains et scolaires » et les agrégats régionaux ne permettent pas d'isoler les arrêts scolaires. Il en résulte une légère surestimation de l'accès en rural.
6. **Pas de fréquence.** Un arrêt avec 2 passages par jour compte autant qu'un tram toutes les 5 minutes. L'agrégat national d'arrêts n'a pas d'horaires. Une pondération par fréquence GTFS (`stop_times`) est la première amélioration à apporter.
7. **Free-floating.** Aucune donnée de trottinettes ou de vélos en free-floating n'est présente à Strasbourg dans les flux GBFS publics utilisés (`offer.parquet` : 0 point `scooter` dans l'emprise EMS). L'accès y est donc sous-estimé pour ce mode.
8. **Coûts hypothétiques.** Capex, opex, passages par jour et €/km sont des ordres de grandeur publics, **à valider par Citiz et l'autorité organisatrice**. Le classement est sensible au rapport de coûts entre types.
9. **Motorisation à la commune.** La part de ménages sans voiture (RP 2021) est agrégée par commune. Elle est donc identique pour tous les sites d'une même commune (0,386 pour tous les sites de Strasbourg).
10. **Biais PU et biais des choix passés.** Voir les sections 4.2 et 7.1. La propension mesure une ressemblance avec l'existant, pas une demande latente.
11. **DROM partiels.** La Guadeloupe, la Guyane et Mayotte sont absentes faute de carreaux Filosofi. La Martinique et La Réunion n'ont aucune station Citiz : la recommandation Citiz n'y est pas calibrée localement.
12. **Projections départementales.** Omphale donne un facteur de croissance par département, appliqué uniformément à tous les carreaux. La population à l'horizon reflète donc mal les dynamiques locales, comme les nouveaux quartiers.
13. **Dédoublonnage par chaînage.** Le *single linkage* peut fusionner des points distants de plus que le seuil dans les zones très denses.

---

## 9. Pistes

- **Fréquence et capacité** : pondérer `n_options` par les passages GTFS ou le nombre de véhicules GBFS (`C.MODE_WEIGHT` est prévu pour une pondération par mode).
- **Isochrones réseau partout** : calibrer le détour par type de territoire (grille communale de densité), ou calculer des isochrones exactes avec un moteur de routage (OSRM, Valhalla) sur l'extrait OSM Geofabrik.
- **Validation terrain** : confronter les propensions aux données d'usage internes de Citiz (réservations par station). C'est le seul moyen de passer de la ressemblance à une vraie demande.
- **Sensibilité** : tableaux de sensibilité automatisés sur λ, les enveloppes, le quota et les coûts. L'application permet déjà de faire varier budget et λ.

### Portage sur Microsoft Fabric

L'énoncé suggère Microsoft Fabric. Le pipeline s'y porte presque tel quel, parce qu'il est déjà découpé en étapes qui échangent des fichiers Parquet au schéma documenté (`CONTRACTS.md`) :

| Brique actuelle | Équivalent Fabric |
|---|---|
| `data/raw` puis `data/interim` puis `outputs/*.parquet` | **Lakehouse OneLake**, avec les couches *bronze* (brut), *silver* (`cells`, `offer`) et *gold* (`cells_access`, `stations_served`, `recommendations`) en tables Delta |
| `src/download.py` | **Data Factory** : pipeline planifié qui rafraîchit GTFS et GBFS, ou notebook planifié |
| `src/population.py`, `offer.py`, `accessibility.py` | **Notebooks** Spark ou Python. Les calculs de voisinage (KD-tree scipy) restent en pandas, partitionnés par département |
| `src/model.py` | **Fabric Data Science** : notebooks et suivi **MLflow** des expériences (métriques de CV spatiale, modèles versionnés) |
| `src/recommend.py` | notebook paramétré (zone, budget, λ) appelable depuis un pipeline |
| `app.py` (Streamlit) | rapport **Power BI** en Direct Lake sur les tables *gold* : carte de chaleur, points d'offre, liste priorisée. Le scénario interactif reste plus naturel dans une application Python |

**Pourquoi Python en local pour le hackathon :**

- **Reproductibilité** : un `git clone`, un `pip install -r requirements.txt` et la chaîne `python -m src.*` reproduisent tous les résultats, sans compte, sans capacité Fabric et sans accès réseau autre que le téléchargement des données ouvertes.
- **Tests et revue** : le code est versionné, testé (`pytest`) et lisible par un jury. Les notebooks se prêtent moins à la revue de code et aux tests unitaires.
- **Volumétrie** : 2,3 M de carreaux et 0,2 M de points tiennent en mémoire sur un portable. L'étape la plus lourde, le calcul des variables du modèle, prend environ 21 min et est mise en cache. Un cluster Spark n'apportait rien pendant les 2,5 jours du hackathon.
- **Portabilité** : la structure en modules et le format Parquet rendent le portage direct.

---

## 10. Reprendre le travail

- **Paramètres** : tout est dans `Config.py`, où chaque hypothèse est commentée avec sa source.
- **Interfaces** : `CONTRACTS.md` décrit les schémas des fichiers échangés. `model.build_features()` et `model.predict_value()` sont réutilisables pour scorer n'importe quel point candidat.
- **Nouveau territoire** : `python -m src.recommend --dep <code>`, ou une bbox via `recommend.recommend(area=(o, s, e, n))`.
- **Tests** : `python -m pytest`, 8 tests, dont le glouton contre la force brute.
- **Pièges connus** :
  - `src.model` prend environ 25 min au premier lancement. Le cache des variables est dans `outputs/cache/` ; il faut le supprimer si `offer.parquet` change. La signature `offer_source` est contrôlée.
  - Lancer l'application avec `python -m streamlit run app.py`.
