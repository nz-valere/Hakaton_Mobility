# Mobili'Score

**Qui a vraiment une option de transport à 5 minutes de chez soi, et où en ajouter ?**
Mobili'Score croise l'offre ouverte (GTFS, GBFS) avec la population au carreau de 200 m (INSEE) pour cartographier l'accès à la mobilité en France, DROM couverts par Filosofi inclus.
Un modèle prédictif et un optimiseur sous budget choisissent ensuite **le territoire** où Citiz a le plus à gagner, puis y proposent deux listes priorisées, une par financeur : les stations Citiz (budget Citiz) et les stations vélo et arrêts de bus (budget de la collectivité). Chaque site vient avec son coût, les habitants gagnés et le CO2 évité.

Hackathon Mobility, Epitech x Citiz x Microsoft. Sources : [SOURCES.md](SOURCES.md). Contrats entre modules : [CONTRACTS.md](CONTRACTS.md). Présentation : [slides/presentation.html](slides/presentation.html). Microsoft Fabric et Power BI : [FABRIC.md](FABRIC.md).

## Résultats clés

Tous les chiffres viennent des fichiers de `outputs/`. Le pipeline complet a été relancé d'un bloc le 20/10/2026 au soir : toutes les sorties proviennent de la même offre (220 666 points) et du même code.

**Diagnostic national** (`outputs/access_summary.json`, 63,8 M d'habitants, 2 324 577 carreaux habités, Métropole + Martinique + La Réunion)

- **33,5 %** des habitants n'ont **aucune** option de transport à 5 minutes de marche (Métropole 33,9 %, Martinique 24,3 %, La Réunion 9,2 %). C'est une **borne basse** : le cercle de 282 m dessert 89 % des Strasbourgeois, contre 84 % sur le vrai réseau piéton. Recalculée avec un rayon qui reproduit la desserte du vrai réseau (≈ 244 m), elle monte à environ 38 %.
- Bus, tram et métro : 65,9 % de la population a au moins un arrêt à 5 min. Vélo en libre-service : 11,6 %. Free-floating : 9,9 %. Train : 4,7 %. **Citiz : 3,5 %**. Autre autopartage : 0,5 %. Pour l'autopartage et le free-floating, on mesure ce qui est **publié en GBFS** : les opérateurs sans flux ouvert (Communauto, Getaround, Zity…) n'apparaissent pas.
- **Accès selon le revenu**, sur les carreaux d'au moins 11 ménages, dont le revenu est mesuré et non imputé par l'INSEE : 11 % sans option dans le 1er décile, 29 % dans le 6e, 18 % dans le 10e. Les ménages les plus exposés sont ceux des déciles intermédiaires, souvent périurbains, pas les plus modestes. Sur tous les carreaux (13 % / 43 % / 23 %), la bosse est amplifiée par l'imputation des petits carreaux ruraux.
- Rayon « 5 minutes » : **282 m** à vol d'oiseau, soit 400 m sur le réseau piéton avec un détour de 1,42. Ce rayon est calibré sur le graphe OSM de Strasbourg (400 origines) pour que le **nombre** d'options soit juste. Comparé au vrai réseau, il donne une précision de 0,92 et un rappel de 0,99 sur la population desservie (`outputs/walk_calibration.json`).

**Modèle de valeur d'un site** (`outputs/model_metrics.json`, validation croisée spatiale par département)

| Type | Modèle retenu | Variables | ROC-AUC | PR-AUC | PR-AUC « population seule » |
|---|---|---|---|---|---|
| Citiz | gradient boosting | 26 | 0,90 | 0,48 | 0,26 |
| Vélo | régression logistique | 29 | 0,87 | 0,64 | 0,53 |
| Bus | gradient boosting | 26 | 0,86 | 0,75 | 0,71 |

Le modèle apprend **où les opérateurs se sont déjà implantés** (présence d'une station), pas l'usage : c'est un apprentissage positif / non étiqueté, assumé.

**Validation par l'usage réel** (`outputs/usage_validation.json`, `outputs/citiz_usage.csv`)

- Collecte des flux GBFS des 17 réseaux Citiz toutes les 5 min (`src/collect_gbfs.py`) : 1 512 stations suivies, 65 relevés sur les 235 possibles du 19/10 (16 h 52) au 20/10 (12 h 23), avec des trous quand le PC était en veille.
- Occupation moyenne par quintile de propension du modèle Citiz (hors pli) : **28 % dans le 1er quintile, 41 % dans le 5e**. L'essentiel de l'écart se joue entre le 3e et le 4e quintile.
- Station par station, le modèle ne fait **pas mieux que la population seule** (Spearman 0,17 contre 0,18 ; écart non significatif). Lecture honnête : la propension repère les secteurs où une station tourne, au même niveau que la densité. Elle ne prédit pas encore l'usage d'une station. Les données d'usage de Citiz permettraient de la recalibrer.
- **303 stations saturées** (voitures réservées plus de 60 % du temps relevé, 20 % du réseau) : une 2e voiture y coûte bien moins cher qu'une nouvelle station. C'est le levier le plus immédiat pour Citiz.
- Fenêtre courte, pendant les vacances de la Toussaint ; sens exact de `is_reserved` à confirmer avec Citiz.

**Fréquence des lignes dans les zones d'étude** (`outputs/frequency_<zone>.json`, GTFS TCL, Lignes d'Azur, CTS et Fluo 67, mardi 17/11/2026, 7 h-20 h)

- Une ligne compte une fois, même si elle passe à plusieurs arrêts proches ou si l'on atteint ses deux quais (aller et retour). Une ligne toutes les 15 min ou mieux vaut 1 option pleine. Les lignes scolaires et le transport à la demande sont exclus.
- **Lyon** : 93 % des habitants ont un arrêt à 5 min, 78 % au moins une option pleine. **14,6 % (≈ 189 000 habitants) ont un arrêt mais un service faible** : le comptage d'arrêts les classait comme desservis.
- **Nice** : 93 % avec un arrêt, 72 % avec une option pleine, **20,7 % (≈ 113 000 habitants) en service faible**. **Strasbourg** : 85 %, 71 %, 14,6 % (≈ 67 000 habitants).

**Où Citiz doit-il s'implanter ?** (`outputs/territories_summary.json`, `outputs/territories_citiz.csv`)

- La méthode procède en trois temps :
  1. Criblage des 99 intercommunalités de plus de 100 000 habitants. L'Île-de-France est exclue : son autopartage est presque absent des flux GBFS publics.
  2. Simulation de l'optimiseur avec le même budget Citiz (1 M€ sur 5 ans) sur les 20 premières.
  3. Correction par le **risque terrain**, issu d'une veille presse (échecs passés, autopartage absent des flux GBFS, soutien de la collectivité ; `Config.TERRITORY_RISK`) : adhérents retenus = adhérents du modèle × (1 − risque).
- **Territoire prioritaire : Métropole de Lyon.** C'est une extension : Citiz LPA y couvre 35 % des habitants, et la Métropole planifie son développement d'ici 2030. 16 stations y desservent **49 477 habitants** et 3 847 adhérents potentiels.
- **Suivent Toulouse (3 814 ; Citiz est retenu par la Métropole pour 2025-2030), Aix-Marseille (3 397), Toulon (3 068) et Nantes (3 066).** L'écart entre Lyon et Toulouse n'est que de 0,9 %, et il tient au bonus de soutien de Toulouse (−10 % de risque). Les deux sont des choix défendables ; Lyon l'emporte aussi par la taille de son marché (1,3 M d'habitants).
- **Nice, 1ʳᵉ pour le modèle seul (7 519 adhérents), recule au 11ᵉ rang** : l'autopartage y a échoué deux fois (Auto Bleue, 68 stations sous DSP d'environ 1,4 M€/an, fermé fin 2018 ; Mobilize Share parti fin juin 2026), risque 65 %. Nice ne repasse en tête que si l'on fixe ce risque sous 49 %.
- **Montpellier** recule de la même façon : Modulauto y exploite environ 100 stations absentes des flux GBFS, ce n'est pas un territoire vierge.
- **Strasbourg, territoire témoin** : Citiz y couvre déjà 45 % des habitants. Le même budget y dessert 39 260 habitants, pour 1 359 adhérents potentiels.
- **Modèle** : gradient boosting appris sur les 80 départements où l'autopartage existe. Test sur Strasbourg, avec le Bas-Rhin tenu hors de l'apprentissage : PR-AUC 0,67 contre 0,59 pour la population seule. Le modèle bat la population dans 56 départements testés sur 67.

**Recommandation pour la Métropole de Lyon** (`outputs/recommendations_summary.json`, `outputs/recommendations.csv` : λ = 0,5, horizon 2040)

| Financeur | Budget | Sites | Habitants nouvellement desservis | € / habitant | CO2 évité |
|---|---|---|---|---|---|
| **Citiz** | 1 M€ | 16 stations Citiz (7 à Villeurbanne, 7 à Lyon 3ᵉ/7ᵉ/8ᵉ, Vernaison, Genay) | **49 477** | 19 € | 121 t/an |
| Collectivité / AOM | 1 M€ | 16 stations vélo (Vaulx-en-Velin, Saint-Priest, Givors, Rillieux…) | 46 869 | 20 € | 7 t/an |

- **Citiz densifie, la collectivité équipe la périphérie.** Les 49 477 nouveaux desservis par Citiz ont déjà un bus à 5 min : la voiture partagée y remplace la 2ᵉ voiture du ménage. Seuls 110 d'entre eux n'avaient aucune option. Les Lyonnais sans aucune option vivent surtout en périphérie peu dense : c'est le rôle du quota peu dense et du budget de la collectivité. Côté collectivité, 85 % des nouveaux desservis vivent dans les 3 premiers déciles de revenu de la métropole, contre 40 % côté Citiz.
- **Aucun arrêt de bus retenu** : avec nos hypothèses (35 k€ d'aménagement, plus le coût d'exploitation du détour de ligne), un arrêt coûte plus de 200 k€ sur 5 ans pour quelques centaines d'habitants, contre 60 k€ pour une station vélo qui en dessert plus de 2 000. L'optimiseur écarte désormais les sites d'enveloppe dont le rendement est inférieur à 20 % du meilleur (`Config.ENVELOPE_MIN_YIELD`). Un arrêt redeviendrait compétitif sur une ligne qui passe déjà devant (détour nul) : à vérifier avec le tracé des lignes.
- **Le CO2 de Citiz vaut ≈ 7,6 t/an par station** : la demande dépasse toujours la capacité d'une voiture (≈ 46 adhérents). Ce chiffre suit donc le nombre de stations et ne départage pas les sites.
- **Le prix de l'équité** (`outputs/equity_curve.json`, λ de 0 à 1, même budget) : pour la collectivité, la part de ménages modestes parmi les nouveaux desservis passe de 74 % à 85 %, et le nombre d'habitants **augmente** (44 616 → 46 869) ; pour Citiz, l'effet est faible (38 % → 40 %, −2 % d'habitants).
- **Le modèle a un prix** (`comparison` du résumé) : à budget égal, sans le modèle (valeur 1 pour tous les sites), Citiz desservirait 61 259 habitants, dont 83 % de ménages modestes, mais avec 73 t de CO2 évité au lieu de 121. Le modèle oriente Citiz vers les secteurs où une station est la plus probable et la plus utilisée, au prix de 19 % d'habitants en moins. C'est un arbitrage à trancher avec Citiz, pas une vérité du calcul.
- Les stations Citiz sont à coordonner avec Citiz LPA, coopérative du réseau déjà implantée à Lyon.
- Nice, pour comparaison : `recommendations_epci200030195.csv` et `recommendations_summary_epci200030195.json`. Vélo Bleu n'y publie pas de flux GBFS : les stations vélo recommandées peuvent doublonner l'existant.

Mêmes sorties pour le témoin Strasbourg (`outputs/recommendations_ems.csv`, `recommendations_summary_ems.json`) et pour la Meurthe-et-Moselle (`--dep 54`, `recommendations_dep54.csv`). À Strasbourg, la stratégie naïve (population seule, sans regarder l'offre existante) dessert 2,8 fois moins d'habitants avec Citiz (13 800 contre 39 260) ; à Lyon, 3,2 fois moins (15 493 contre 49 477).

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
| 4b | `python -m src.frequency` | fréquence des lignes bus/tram/métro dans les zones d'étude (GTFS TCL, Lignes d'Azur, CTS, Fluo 67) | `outputs/frequency_cells_<zone>.parquet`, `outputs/frequency_<zone>.json` |
| 5 | `python -m src.model` | modèles de valeur d'un site (Citiz, vélo, bus) | `outputs/model_metrics.json`, `outputs/model_*.joblib`, `outputs/figures/model_*.png` |
| 5b | `python -m src.territories` | classement national des intercommunalités pour Citiz (criblage + simulation) | `outputs/territories_citiz.csv`, `outputs/territories_summary.json` |
| 5c | `python -m src.collect_gbfs` (en continu, PC allumé ; ou notebook `05c_collect_gbfs` planifié toutes les 5 min dans Fabric) puis `python -m src.usage` | usage réel des stations Citiz, validation du modèle par l'occupation | `data/gbfs/*`, `outputs/citiz_usage.csv`, `outputs/usage_validation.json` |
| 6 | `python -m src.recommend` | deux listes priorisées (Citiz ; collectivité vélo + bus), par défaut sur le territoire prioritaire ; variante « sans fréquence » et prix de l'équité (λ de 0 à 1) | `outputs/recommendations.csv`, `outputs/recommendations_summary.json`, `outputs/equity_curve.json` |
| 6c | `python -m src.scenarios` | grille des curseurs (budget × λ × financeur) sur les 10 premiers territoires et Strasbourg, pour Power BI ; cache signé dans `outputs/cache/` | `outputs/fabric/scenarios_sites.parquet`, `scenarios_resume.parquet` |
| 7 | `python -m src.figures` | figures de la présentation | `outputs/figures/slides_*.png` |
| 8 | notebook `08_export_fabric` | tables Delta du Lakehouse (Power BI) ; en local, parquets dans `outputs/fabric/` | tables `carreaux`, `communes`, `recommandations`, `scenarios_*`, `dim_*`, `param_*`… |

Options de `src.recommend` : `--area ems` (Strasbourg, témoin), `--area epci:<siren>` (toute intercommunalité), `--dep 54` (département), `--citiz-budget 1000000`, `--public-budget 1000000`, `--lambda 0.5` (poids de l'équité), `--no-split` (vélo et bus sans enveloppes). Une zone autre que le territoire prioritaire écrit des fichiers suffixés (`recommendations_ems.csv`…).

**Microsoft Fabric** : `notebooks/` reprend chaque module cellule par cellule, une étape par notebook (`00_geo` … `08_export_fabric`, dont `04b_frequency`, `05c_collect_gbfs`, `05c_usage` et `06c_scenarios`). Mode d'emploi complet : [FABRIC.md](FABRIC.md). Le code est le même que dans `src/` : après une modification de `src/`, lancer `python notebooks/make_notebooks.py` pour les régénérer (`--check` signale un notebook périmé sans rien écrire). Dans Fabric, `05c_collect_gbfs` fait un seul relevé par exécution : planifié toutes les 5 minutes, il remplace la collecte sur un PC allumé.

## Démo

```bash
.venv/bin/python -m streamlit run app.py
# ou, venv activé :
python -m streamlit run app.py
```

N'utilisez pas `.venv/bin/streamlit` : son shebang est cassé. Sous Windows : `.venv\Scripts\python -m streamlit run app.py`.

Dans l'onglet « Où investir », la liste est recalculée en direct quand un curseur bouge : le territoire est préparé une seule fois, puis seul le glouton est relancé (≈ 1 s). Les stratégies de comparaison ne sont calculées que si l'on active « Comparer avec les autres stratégies ». La courbe « Le prix de l'équité » relance l'optimisation pour λ de 0 à 1 par pas de 0,1 avec le même budget (même grille que Power BI). Sur la carte, un bouton bascule entre « nombre d'arrêts » et « fréquence des lignes » dans les zones dont les GTFS sont lus.

## Tests

```bash
python -m pytest
```

60 tests passent en environ 6 s (Windows compris : les fichiers texte sont lus et écrits en UTF-8). Sur un clone neuf, sans `data/`, les tests qui lisent les données sont sautés au lieu d'échouer. `pip install -r requirements-dev.txt` installe pytest.

- `tests/test_geo.py` : projection et retour, distances métriques, voisinages comparés à la force brute, surface du disque de marche, lecture du rayon calibré.
- `tests/test_core_units.py` : clé des carreaux, rang pondéré, classement GBFS, dédoublonnage, jour de semaine indépendant de la locale, grille des scénarios, couleurs de l'app.

- `tests/test_frequency.py` : départs/h depuis un GTFS synthétique, une ligne comptée une fois même si elle passe à plusieurs arrêts proches ou dans les deux sens, jour de référence de repli, facteur de service des arrêts de bus.
- `tests/test_usage.py` : occupation et disponibilité des stations depuis des relevés synthétiques, collecteur qui ne garde que des totaux par station.

- `tests/test_accessibility.py` : comptage des options, population servie et score 0 des carreaux sans option.
- `tests/test_optimize.py` : comparaison du glouton à la force brute sur 40 petites instances. Il atteint en moyenne 97,3 % de l'optimum, et 88,4 % au minimum.
- `tests/test_recommend.py` : respect du budget, exclusion des carreaux déjà desservis, effet de λ, coût de détour des arrêts de bus.
- `tests/test_model.py` : variables autorisées, sommes sur grille, prédiction hors pli, backtest par département.
- `tests/test_territories.py` : rattachement des communes (et arrondissements de Paris, Lyon, Marseille) aux intercommunalités, criblage, risque terrain, séparation des financeurs.

## Temps d'exécution mesurés

Mesures sur un poste portable (macOS), relevées dans les fichiers de sortie :

| Étape | Durée |
|---|---|
| `walk_calibration` | 21,7 s |
| `accessibility` (2,3 M carreaux) | 16 à 31 s selon la machine |
| `territories` | ≈ 70 s |
| `model` | 1 529 s (≈ 25 min), dont 1 291 s de calcul des variables (mises en cache dans `outputs/cache/`) |
| `recommend` (Strasbourg, avec cache) | 2,9 s |
| `recommend --dep 54` | 9,1 s |
| `scenarios` (11 territoires × 1 100 optimisations, 4 processus) | ≈ 80 min |

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
│   ├── frequency.py       # 4b. fréquence des lignes dans les zones d'étude (GTFS)
│   ├── model.py           # 5. modèles de valeur d'un site
│   ├── territories.py     # 5b. classement national des territoires pour Citiz
│   ├── collect_gbfs.py    # 5c. collecte de l'usage réel des stations Citiz (GBFS, 5 min)
│   ├── usage.py           # 5c. validation du modèle par l'occupation réelle
│   ├── optimize.py        # 6. glouton budgété (algorithme)
│   ├── recommend.py       # 6. orchestration de la recommandation
│   ├── figures.py         # figures de la présentation
│   ├── geo.py             # projections, rayon, voisinages
│   └── app_data.py        # préparation des données pour app.py
├── notebooks/             # le pipeline en notebooks pour Microsoft Fabric (même code que src/)
├── tests/                 # pytest
├── data/raw, data/interim # données (non versionnées)
├── outputs/               # résultats (json, csv, parquet, modèles, figures/)
└── slides/                # presentation.html + speaker_notes.md
```
