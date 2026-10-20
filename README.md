# Mobili'Score

**Qui a vraiment une option de transport à 5 minutes de chez soi, et où en ajouter ?**
Mobili'Score croise l'offre ouverte (GTFS, GBFS) avec la population au carreau de 200 m (INSEE) pour cartographier l'accès à la mobilité en France, DROM couverts par Filosofi inclus.
Un modèle prédictif et un optimiseur sous budget choisissent ensuite **le territoire** où Citiz a le plus à gagner, puis y proposent deux listes priorisées, une par financeur : les stations Citiz (budget Citiz) et les stations vélo et arrêts de bus (budget de la collectivité). Chaque site vient avec son coût, les habitants gagnés et le CO2 évité.

Hackathon Mobility, Epitech x Citiz x Microsoft. Sources : [SOURCES.md](SOURCES.md). Contrats entre modules : [CONTRACTS.md](CONTRACTS.md). Présentation : [slides/presentation.html](slides/presentation.html).

## Résultats clés

Tous les chiffres viennent des fichiers de `outputs/` (pipeline relancé le 20/10/2026 avec les flux GBFS du jour).

**Diagnostic national** (`outputs/access_summary.json`, 63,8 M d'habitants, 2 324 577 carreaux habités, Métropole + Martinique + La Réunion)

- **36 %** des habitants n'ont **aucune** option de transport à 5 minutes de marche (Métropole 36,0 %, Martinique 24,3 %, La Réunion 40,5 %).
- Bus, tram et métro : 62,1 % de la population a au moins un arrêt à 5 min. Vélo en libre-service : 11,6 %. Free-floating : 9,9 %. Train : 4,7 %. **Citiz : 3,5 %**. Autre autopartage : 0,5 %.
- **Courbe en U selon le revenu** : 18 % sans option dans le 1er décile de revenu, 45 % dans le 6e, 25 % dans le 10e. Les ménages les plus exposés sont ceux des déciles intermédiaires, pas les plus modestes.
- Rayon « 5 minutes » : **282 m** à vol d'oiseau, soit 400 m sur le réseau piéton avec un détour de 1,42. Ce rayon est calibré sur le graphe OSM de Strasbourg (237 399 nœuds, 400 origines). Comparé au vrai réseau, il donne une précision de 0,92 et un rappel de 0,99 sur la population desservie (`outputs/walk_calibration.json`).

**Modèle de valeur d'un site** (`outputs/model_metrics.json`, validation croisée spatiale par département)

| Type | Modèle retenu | ROC-AUC | PR-AUC | PR-AUC « population seule » |
|---|---|---|---|---|
| Citiz | gradient boosting | 0,90 | 0,47 | 0,26 |
| Vélo | régression logistique | 0,87 | 0,64 | 0,53 |
| Bus | gradient boosting | 0,86 | 0,71 | 0,68 |

**Validation par l'usage réel** (`outputs/usage_validation.json`, `outputs/citiz_usage.csv`)

- Collecte des flux GBFS des 17 réseaux Citiz toutes les 5 min (`src/collect_gbfs.py`) : 1 512 stations suivies, 65 relevés du 19/10 (16 h 50) au 20/10 (12 h 25), avec des trous quand le PC était en veille.
- Occupation moyenne (part du temps-voiture réservé) par quintile de propension du modèle Citiz (hors pli) : **26,6 % dans le 1er quintile, 41,1 % dans le 5e**. Le modèle, appris seulement sur la présence des stations, sépare bien les stations peu et très utilisées.
- Mais pour classer l'usage station par station, il fait un peu moins bien que la population seule (Spearman 0,15 contre 0,18). Limite assumée : le modèle dit **où** Citiz réussit à s'implanter, pas encore **combien** une station roulera. Les données d'usage de Citiz permettraient de le recalibrer.
- **303 stations saturées** (voitures réservées plus de 60 % du temps relevé, 20 % du réseau) : une 2e voiture y coûte moins cher qu'une nouvelle station.
- Fenêtre courte, en partie pendant les vacances de la Toussaint ; sens exact de `is_reserved` à confirmer avec Citiz.

**Fréquence des lignes dans les zones d'étude** (`outputs/frequency_<zone>.json`, GTFS Lignes d'Azur, CTS et Fluo 67, mardi 17/11/2026, 7 h-20 h)

- Une ligne compte une fois même si elle passe à plusieurs arrêts proches ; une ligne toutes les 15 min ou mieux vaut 1 option pleine.
- **Nice Côte d'Azur** : 93 % des habitants ont un arrêt à 5 min, mais 80 % seulement ont au moins une option pleine. **13,5 % (≈ 74 000 habitants) ont un arrêt mais un service faible** : le comptage d'arrêts les classait comme desservis.
- **Strasbourg** : 85 % avec un arrêt, 82 % avec au moins une option pleine, 4,2 % en service faible.

**Où Citiz doit-il s'implanter ?** (`outputs/territories_summary.json`, `outputs/territories_citiz.csv`)

- Criblage des 99 intercommunalités de plus de 100 000 habitants (Île-de-France exclue : son autopartage est presque absent des flux GBFS publics), puis simulation de l'optimiseur avec le même budget Citiz (1 M€ sur 5 ans) sur les 10 premières.
- **Territoire prioritaire : Métropole Nice Côte d'Azur** (549 000 habitants, aucune station d'autopartage publiée ; Mobilize Share y a fermé fin juin 2026). 16 stations y desservent **86 117 habitants** et 7 513 adhérents potentiels. Suivent Toulon (4 101) et Montpellier (4 031) ; Lyon est 7e (3 027).
- **Strasbourg, territoire témoin** : Citiz y couvre déjà 45 % des habitants, et le même budget n'y dessert que 37 949 habitants (1 328 adhérents potentiels).
- **Modèle** : gradient boosting appris sur les 80 départements où l'autopartage existe. Test sur Strasbourg, avec le Bas-Rhin tenu hors de l'apprentissage : PR-AUC 0,68 contre 0,59 pour la population seule.

**Recommandation pour la Métropole Nice Côte d'Azur** (`outputs/recommendations_summary.json`, `outputs/recommendations.csv` : λ = 0,5, horizon 2040)

| Financeur | Budget | Sites | Habitants nouvellement desservis | € / habitant | CO2 évité |
|---|---|---|---|---|---|
| **Citiz** | 1 M€ | 16 stations Citiz (14 à Nice, Beaulieu-sur-Mer, Cap-d'Ail) | **86 117** | 11 € | 121 t/an |
| Collectivité / AOM | 1 M€ | 12 stations vélo, 1 arrêt de bus | 63 810 | 15 € | 4 t/an |

- **Effet de la fréquence des lignes**, à données identiques : sans elle, la collectivité obtenait 9 stations vélo et 2 arrêts de bus pour 48 494 habitants. Avec elle, un arrêt posé sur une ligne peu fréquente vaut moins, et le budget part vers des stations vélo : **63 810 habitants (+32 %)**, dont 40 % dans les 3 premiers déciles de revenu (contre 35 %).
- 43 % des nouveaux desservis par Citiz vivent dans les 3 premiers déciles de revenu de la métropole (48 % sans la fréquence : le besoin « faible accessibilité » repère maintenant les quartiers à service faible, qui ne sont pas toujours les plus modestes).
- Vélo Bleu (Nice) ne publie pas de flux GBFS : les stations vélo recommandées sont à confronter au réseau réel.

Mêmes sorties pour le témoin Strasbourg (`outputs/recommendations_ems.csv`, `recommendations_summary_ems.json`) et pour la Meurthe-et-Moselle (`--dep 54`, `recommendations_dep54.csv`). À Strasbourg, la stratégie naïve (population seule, sans regarder l'offre existante) dessert 2,7 fois moins d'habitants avec Citiz (13 800 contre 37 949). Le prix de l'équité de chaque territoire est dans `outputs/equity_curve*.json` (λ de 0 à 1, même budget).

## Installation

Python 3.9.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Pipeline (dans l'ordre)

Chaque étape est un module : `python -m src.<module>`. Tous les paramètres chiffrés sont dans `Config.py`.

| # | Commande | Rôle | Sortie |
|---|---|---|---|
| 1 | `python -m src.download` | télécharge les données ouvertes, avec cache | `data/raw/*` |
| 2 | `python -m src.population` | carreaux INSEE 200 m, motorisation RP 2021, projections Omphale | `data/interim/cells.parquet` |
| 3 | `python -m src.offer` | arrêts GTFS et stations GBFS classés par mode puis dédoublonnés | `data/interim/offer.parquet` |
| 3b | `python -m src.walk_calibration` | calibre le rayon 5 min sur le réseau piéton OSM | `outputs/walk_calibration.json`, `outputs/figures/walk_detour.png` |
| 4 | `python -m src.accessibility` | options à 5 min par carreau, population servie par point d'offre | `outputs/cells_access.parquet`, `stations_served.parquet`, `commune_access.parquet`, `access_summary.json` |
| 4b | `python -m src.frequency` | fréquence des lignes bus/tram/métro dans les zones d'étude (GTFS CTS, Fluo 67, Lignes d'Azur) | `outputs/frequency_cells_<zone>.parquet`, `outputs/frequency_<zone>.json` |
| 5 | `python -m src.model` | modèles de valeur d'un site (Citiz, vélo, bus) | `outputs/model_metrics.json`, `outputs/model_*.joblib`, `outputs/figures/model_*.png` |
| 5c | `python -m src.collect_gbfs` (en continu, PC allumé) puis `python -m src.usage` | usage réel des stations Citiz, validation du modèle par l'occupation | `data/gbfs/*`, `outputs/citiz_usage.csv`, `outputs/usage_validation.json` |
| 5b | `python -m src.territories` | classement national des intercommunalités pour Citiz (criblage + simulation) | `outputs/territories_citiz.csv`, `outputs/territories_summary.json` |
| 6 | `python -m src.recommend` | deux listes priorisées (Citiz ; collectivité vélo + bus), par défaut sur le territoire prioritaire ; variante « sans fréquence » et prix de l'équité (λ de 0 à 1) | `outputs/recommendations.csv`, `outputs/recommendations_summary.json`, `outputs/equity_curve.json` |
| 7 | `python -m src.figures` | figures de la présentation | `outputs/figures/slides_*.png` |

Options de `src.recommend` : `--area ems` (Strasbourg, témoin), `--area epci:<siren>` (toute intercommunalité), `--dep 54` (département), `--citiz-budget 1000000`, `--public-budget 1000000`, `--lambda 0.5` (poids de l'équité), `--no-split` (vélo et bus sans enveloppes). Une zone autre que le territoire prioritaire écrit des fichiers suffixés (`recommendations_ems.csv`…).

## Démo

```bash
.venv/bin/python -m streamlit run app.py
# ou, venv activé :
python -m streamlit run app.py
```

N'utilisez pas `.venv/bin/streamlit` : son shebang est cassé. Sous Windows : `.venv\Scripts\python -m streamlit run app.py`.

Dans l'onglet « Où investir », la liste est recalculée en direct quand un curseur bouge : le territoire est préparé une seule fois, puis seul le glouton est relancé. Les stratégies de comparaison ne sont calculées que si l'on active « Comparer avec les autres stratégies ». La courbe « Le prix de l'équité » relance l'optimisation pour λ = 0 ; 0,25 ; 0,5 ; 0,75 ; 1 avec le même budget.

## Tests

```bash
python -m pytest
```

30 tests passent en environ 6 s (Windows compris : tous les fichiers texte sont lus et écrits en UTF-8) :

- `tests/test_frequency.py` : départs/h depuis un GTFS synthétique, une ligne comptée une fois même si elle passe à plusieurs arrêts proches, jour de référence de repli, facteur de service des arrêts de bus.
- `tests/test_usage.py` : occupation et disponibilité des stations depuis des relevés synthétiques, collecteur qui ne garde que des totaux par station.

- `tests/test_accessibility.py` : comptage des options, population servie et score 0 des carreaux sans option.
- `tests/test_optimize.py` : comparaison du glouton à la force brute sur 40 petites instances. Il atteint en moyenne 97,3 % de l'optimum, et 88,4 % au minimum.
- `tests/test_recommend.py` : respect du budget, exclusion des carreaux déjà desservis, effet de λ, coût de détour des arrêts de bus.
- `tests/test_model.py` : variables autorisées, sommes sur grille, prédiction hors pli, backtest par département.
- `tests/test_territories.py` : rattachement des communes (et arrondissements de Paris, Lyon, Marseille) aux intercommunalités, criblage, séparation des financeurs.

## Temps d'exécution mesurés

Mesures sur un poste portable (macOS), relevées dans les fichiers de sortie :

| Étape | Durée |
|---|---|
| `walk_calibration` | 21,7 s |
| `accessibility` (2,3 M carreaux) | 15,7 s |
| `model` | 1 529 s (≈ 25 min), dont 1 291 s de calcul des variables (mises en cache dans `outputs/cache/`) |
| `recommend` (Strasbourg, avec cache) | 2,9 s |
| `recommend --dep 54` | 9,1 s |

Les durées de `download`, `population` et `offer` n'ont pas été mesurées dans les sorties.

## Arborescence

```
.
├── Config.py              # tous les paramètres et hypothèses chiffrées (coûts, CO2, budget, rayons…)
├── CONTRACTS.md           # schémas des fichiers échangés entre modules
├── SOURCES.md             # sources de données, licences, hypothèses
├── app.py                 # démo Streamlit
├── requirements.txt
├── src/
│   ├── download.py        # 1. téléchargements
│   ├── population.py      # 2. carreaux INSEE + motorisation + projections
│   ├── offer.py           # 3. offre GTFS/GBFS classée et dédoublonnée
│   ├── walk_calibration.py# 3b. calibration du rayon de marche (OSM)
│   ├── accessibility.py   # 4. indicateurs d'accessibilité
│   ├── model.py           # 5. modèles de valeur d'un site
│   ├── territories.py     # 5b. classement national des territoires pour Citiz
│   ├── optimize.py        # 6. glouton budgété (algorithme)
│   ├── recommend.py       # 6. orchestration de la recommandation
│   ├── figures.py         # figures de la présentation
│   ├── geo.py             # projections, rayon, voisinages
│   └── app_data.py        # préparation des données pour app.py
├── tests/                 # pytest
├── data/raw, data/interim # données (non versionnées)
├── outputs/               # résultats (json, csv, parquet, modèles, figures/)
└── slides/                # presentation.html + speaker_notes.md
```
