# Mobili'Score

**Qui a vraiment une option de transport à 5 minutes de chez soi, et où en ajouter ?**
Mobili'Score croise l'offre ouverte (GTFS, GBFS) avec la population au carreau de 200 m (INSEE) pour cartographier l'accès à la mobilité en France, DROM couverts par Filosofi inclus.
Un modèle prédictif et un optimiseur sous budget proposent ensuite une liste priorisée de stations Citiz, de stations vélo et d'arrêts de bus, avec leur coût, les habitants gagnés et le CO2 évité.

Hackathon Mobility, Epitech x Citiz x Microsoft. Sources : [SOURCES.md](SOURCES.md). Contrats entre modules : [CONTRACTS.md](CONTRACTS.md). Présentation : [slides/presentation.html](slides/presentation.html).

## Résultats clés

Tous les chiffres viennent des fichiers de `outputs/`.

**Diagnostic national** (`outputs/access_summary.json`, 63,8 M d'habitants, 2 324 577 carreaux habités, Métropole + Martinique + La Réunion)

- **36 %** des habitants n'ont **aucune** option de transport à 5 minutes de marche (Métropole 36,0 %, Martinique 24,3 %, La Réunion 40,5 %).
- Bus, tram et métro : 62,1 % de la population a au moins un arrêt à 5 min. Vélo en libre-service : 11,6 %. Free-floating : 9,9 %. Train : 4,7 %. **Citiz : 3,5 %**. Autre autopartage : 0,5 %.
- **Courbe en U selon le revenu** : 18 % sans option dans le 1er décile de revenu, 45 % dans le 6e, 25 % dans le 10e. Les ménages les plus exposés sont ceux des déciles intermédiaires, pas les plus modestes.
- Rayon « 5 minutes » : **282 m** à vol d'oiseau, soit 400 m sur le réseau piéton avec un détour de 1,42. Ce rayon est calibré sur le graphe OSM de Strasbourg (237 399 nœuds, 400 origines). Comparé au vrai réseau, il donne une précision de 0,92 et un rappel de 0,99 sur la population desservie (`outputs/walk_calibration.json`).

**Modèle de valeur d'un site** (`outputs/model_metrics.json`, validation croisée spatiale par département)

| Type | Modèle retenu | ROC-AUC | PR-AUC | PR-AUC « population seule » |
|---|---|---|---|---|
| Citiz | gradient boosting | 0,90 | 0,46 | 0,26 |
| Vélo | régression logistique | 0,87 | 0,64 | 0,53 |
| Bus | gradient boosting | 0,85 | 0,71 | 0,67 |

**Recommandation pour l'Eurométropole de Strasbourg** (`outputs/recommendations_summary.json` : budget de 2 M€ sur 5 ans, λ = 0,5, horizon 2040)

- **28 sites** : 14 stations vélo, 12 stations Citiz et 2 arrêts de bus, pour 1,98 M€.
- **68 465 habitants nouvellement desservis**, soit 71 574 à l'horizon 2040. Le coût revient à **29 € par nouvel habitant desservi**.
- Environ **106 t de CO2 évitées par an** (hypothèses ADEME, détaillées dans `Config.py` et `outputs/recommendations_summary.json`).
- **50,4 %** des nouveaux desservis vivent dans les 3 premiers déciles de revenu de la zone.
- À budget égal, la stratégie naïve « population seule » (sans modèle et sans tenir compte de l'offre existante) ne dessert réellement que 39 067 nouveaux habitants, pour 22 t de CO2 évitées par an.

Une seconde étude de cas, la Meurthe-et-Moselle (`--dep 54`), est disponible dans `outputs/recommendations_summary_dep54.json`.

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
| 5 | `python -m src.model` | modèles de valeur d'un site (Citiz, vélo, bus) | `outputs/model_metrics.json`, `outputs/model_*.joblib`, `outputs/figures/model_*.png` |
| 6 | `python -m src.recommend` | liste priorisée sous budget (par défaut : Eurométropole de Strasbourg) | `outputs/recommendations.csv`, `outputs/recommendations_summary.json` |
| 7 | `python -m src.figures` | figures de la présentation | `outputs/figures/slides_*.png` |

Options de `src.recommend` : `--dep 54` (autre territoire), `--budget 2000000`, `--lambda 0.5` (poids de l'équité), `--no-split` (pas d'enveloppes par type).

## Démo

```bash
.venv/bin/python -m streamlit run app.py
# ou, venv activé :
python -m streamlit run app.py
```

N'utilisez pas `.venv/bin/streamlit` : son shebang est cassé.

## Tests

```bash
python -m pytest
```

8 tests passent en environ 3,5 s :

- `tests/test_accessibility.py` : comptage des options, population servie et score 0 des carreaux sans option.
- `tests/test_optimize.py` : comparaison du glouton à la force brute sur 40 petites instances. Il atteint en moyenne 97,3 % de l'optimum, et 88,4 % au minimum.
- `tests/test_recommend.py` : respect du budget, exclusion des carreaux déjà desservis, effet de λ, coût de détour des arrêts de bus.

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
