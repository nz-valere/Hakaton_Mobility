# Contrats d'interface entre modules (à respecter par tous les contributeurs)

Pipeline : `python -m src.<module>` dans cet ordre. Python 3.9 (`.venv/bin/python`),
paquets disponibles : numpy, pandas, pyarrow, scipy, scikit-learn, pyproj, matplotlib,
streamlit, pydeck, openpyxl. **Pas de geopandas / networkx / folium** : ne pas installer
de paquets lourds sans nécessité ; `pip install pytest` est autorisé.
Tous les paramètres chiffrés vont dans `Config.py` (importé `import Config as C`).
Géométrie commune : `src/geo.py` (projection, `walk_radius_m()`, `pairs_within()`).

| Étape | Module | Entrées | Sortie |
|---|---|---|---|
| 1 | `src/download.py` | internet | `data/raw/*` |
| 2 | `src/population.py` | raw INSEE | `data/interim/cells.parquet` |
| 3 | `src/offer.py` | raw GTFS/GBFS | `data/interim/offer.parquet` |
| 3b | `src/walk_calibration.py` | raw OSM + offer | `outputs/walk_calibration.json` |
| 4 | `src/accessibility.py` | cells, offer, calibration | `outputs/cells_access.parquet`, `outputs/stations_served.parquet` |
| 4b | `src/frequency.py` | cells, cells_access, GTFS des zones (`C.FREQ_FEEDS`) | `outputs/frequency_cells_<zone>.parquet`, `outputs/frequency_<zone>.json` |
| 5 | `src/model.py` | cells_access, offer | `outputs/model_metrics.json`, `outputs/model_*.joblib`/pkl, fonction `predict_value()` |
| 5c | `src/collect_gbfs.py` (en continu) puis `src/usage.py` (avant 5b) | flux GBFS Citiz ; cache des variables, modèle Citiz | `data/gbfs/citiz_status_*.csv` ; `outputs/citiz_usage.csv`, `outputs/usage_validation.json` |
| 5b | `src/territories.py` | features, modèle Citiz, EPCI | `outputs/territories_citiz.csv`, `outputs/territories_summary.json` (territoire prioritaire `top`) |
| 6 | `src/optimize.py` (algo) + `src/recommend.py` (orchestration) | tout | `outputs/recommendations.csv` (colonne `financeur` : `citiz` / `collectivite`) |
| 6c | `src/scenarios.py` | recommend, territories | `outputs/fabric/scenarios_sites.parquet`, `scenarios_resume.parquet` (cache signé `outputs/cache/scenarios_<zone>.*`) |
| 7 | `src/figures.py` ; `app.py` (Streamlit, via `src/app_data.py`) | outputs | figures des slides ; démo live |
| 8 | `notebooks/08_export_fabric.ipynb` | outputs | tables Delta du Lakehouse Fabric (copie parquet dans `outputs/fabric/`), voir FABRIC.md |

## cells.parquet (une ligne par carreau 200 m habité)
`key` (int64 unique), `crs_id` (0 métropole, 1 Martinique, 2 Réunion), `x`,`y` (centre, mètres, CRS du territoire),
`lon`,`lat`, `com`, `dep`, `ind` (habitants, float), `men`, `pop_future`, `growth`,
`income_pc`, `poverty_rate`, `carfree_share`, `multicar_share`, `share_18_39`, `share_65p`,
`share_kids`, `share_1ind`, `share_coll`, `share_soc`, `share_owner`, `surf_pc`, `territory`, + colonnes brutes Filosofi.

## offer.parquet (une ligne par point d'offre dédoublonné)
| colonne | type | sens |
|---|---|---|
| `offer_id` | str | identifiant unique stable (`<mode>:<source>:<id>`) |
| `mode` | str | une clé de `C.MODES` : `rail`, `transit`, `bike`, `scooter`, `carsharing`, `citiz` |
| `name` | str | nom lisible |
| `lon`,`lat` | float | WGS84 |
| `crs_id`,`x`,`y` | int8/float | via `geo.project()` ; crs_id = -1 hors territoires Filosofi |
| `source` | str | jeu de données d'origine (titre dataset / système GBFS) |
| `operator` | str | réseau / opérateur |
| `capacity` | float | places (GBFS) ou NaN |

## outputs/cells_access.parquet
`key` + colonnes de cells utiles (`crs_id,x,y,lon,lat,com,dep,ind`) +
`n_<mode>` (nb de points d'offre de ce mode à ≤ 5 min de marche), `n_options` (somme pondérée par `C.MODE_WEIGHT`),
`n_modes` (nb de modes distincts accessibles), `pop_catchment` (habitants à ≤ 5 min du carreau),
`options_per_1000` (= 1000·n_options / pop_catchment), `score` (indice 0-100 froid→chaud, cf. docstring de `src/accessibility.py`),
`served_<mode>` (bool).

## outputs/stations_served.parquet
Colonnes d'offer + `pop_served` (habitants à ≤ 5 min), `pop_served_exclusive` (habitants dont c'est le seul point du mode),
`households_served`.

## outputs/frequency_cells_<zone>.parquet (une ligne par carreau habité de la zone)
`key`, `tc_freq_options` (Σ lignes à ≤ 5 min de min(1, départs/h du meilleur sens ÷ `C.FULL_OPTION_DEP_H`), chaque
ligne comptée une fois, les deux sens compris ; lignes scolaires et TAD exclues), `tc_lines` (lignes distinctes), `tc_dep_h` (départs/h cumulés), `freq_nearest`
(départs/h de la meilleure ligne de l'arrêt le plus proche), `n_options_count` / `n_transit_count` (méthode
nationale), `n_options_freq` (= `tc_freq_options` + points des autres modes). `<zone>` = `ems`, `epci<siren>`.
Lu par `src/recommend.py` (valeur des arrêts de bus, besoin) et l'app.

## data/gbfs/citiz_status_<jour>.csv (collecteur) et outputs/citiz_usage.csv
Collecte : `ts_utc`, `provider_id`, `station_id`, `n_vehicles`, `n_reserved`, `n_disabled` (totaux par station,
aucune donnée de véhicule). Usage : `provider_id`, `station_id`, `name`, `lon`, `lat`, `releves`, `vehicules`,
`occupation` (Σ réservées / Σ voitures), `disponibilite` (part des relevés avec ≥ 1 voiture libre), `saturee`,
`propension_oof`, `pop_5min`.

## Confidentialité
Ne jamais exporter/afficher une agrégation de moins de `C.PRIVACY_MIN_HOUSEHOLDS` ménages
(Filosofi est déjà imputé/arrondi sous ce seuil ; on agrège à la maille d'affichage).

## outputs/fabric/scenarios_resume.parquet (une ligne par territoire × financeur × budget × λ)
`zone` (clé sans « : », ex. `epci200046977`, `ems`), `epci` (SIREN), `zone_nom`, `rang_citiz` (-1 = témoin),
`ordre`, `zone_par_defaut` (territoire prioritaire), `financeur` (`citiz` / `collectivite`), `budget_eur`,
`budget_k_eur` et `lambda_x10` (entiers, clés des paramètres Power BI), `equity_lambda`, `n_sites`, `cost_eur`,
`pop_newly_served`, `pop_from_zero_option`, `eur_per_new_resident`, `co2_avoided_t_yr`, `part_modestes` (0-1).
`scenarios_sites.parquet` : mêmes clés + les colonnes de `recommendations.csv` (`com` au lieu de `code_commune`).

