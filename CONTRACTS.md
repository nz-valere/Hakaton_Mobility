# Contrats d'interface entre modules (à respecter par tous les contributeurs)

Pipeline : `python -m src.<module>` dans cet ordre. Python 3.9 (`.venv/bin/python`),
paquets disponibles : numpy, pandas, pyarrow, scipy, scikit-learn, pyproj, matplotlib,
streamlit, pydeck, openpyxl. **Pas de geopandas / networkx / folium** : ne pas installer
de paquets lourds sans nécessité ; `pip install pytest` est autorisé.
Tous les paramètres chiffrés vont dans `Config.py` (importé `import Config as C`).
Géométrie commune : `src/geo.py` (projection, `walk_radius_m()`, `pairs_within()`).

| Étape | Module | Entrées | Sortie |
|---|---|---|---|
| 1 | `src/download.py` | internet | `data/raw/*` (fait) |
| 2 | `src/population.py` | raw INSEE | `data/interim/cells.parquet` |
| 3 | `src/offer.py` | raw GTFS/GBFS | `data/interim/offer.parquet` |
| 3b | `src/walk_calibration.py` | raw OSM + offer | `outputs/walk_calibration.json` |
| 4 | `src/accessibility.py` | cells, offer, calibration | `outputs/cells_access.parquet`, `outputs/stations_served.parquet` |
| 5 | `src/model.py` | cells_access, offer | `outputs/model_metrics.json`, `outputs/model_*.joblib`/pkl, fonction `predict_value()` |
| 6 | `src/optimize.py` (algo) + `src/recommend.py` (orchestration) | tout | `outputs/recommendations.csv` |
| 7 | `app.py` (Streamlit) | outputs | démo live |

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

## Confidentialité
Ne jamais exporter/afficher une agrégation de moins de `C.PRIVACY_MIN_HOUSEHOLDS` ménages
(Filosofi est déjà imputé/arrondi sous ce seuil ; on agrège à la maille d'affichage).
