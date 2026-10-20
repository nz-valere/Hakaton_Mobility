# Mobili'Score dans Microsoft Fabric

Objectif : exécuter les notebooks dans Fabric et construire le rapport Power BI à partir de tables Delta.

## Ce qu'il faut créer et installer

| Quoi | Où | Pourquoi |
|---|---|---|
| Un **workspace** avec une capacité Fabric (ou d'essai) | portail Fabric | héberge le Lakehouse, les notebooks et le rapport |
| Un **Lakehouse** (ex. `mobiliscore_lh`) | workspace → *New item* → *Lakehouse* | stocke le projet (*Files*) et les tables Power BI (*Tables*) |
| Le **projet** dans `Files/mobiliscore/` | Lakehouse → *Files* → *Upload* | les notebooks importent `Config.py` et `src/` |
| Les **notebooks** `.ipynb` | workspace → *Import* → *Notebook* → *From this computer* | le code du pipeline (même code que `src/`) |
| Un **Environment** avec `pyproj` et `openpyxl` (recommandé) | workspace → *New item* → *Environment* → *Public libraries*, publier, puis le sélectionner dans chaque notebook | paquets absents du runtime ; installés une seule fois au lieu de chaque session |

Sans Environment, la première cellule de chaque notebook fait `pip install pyproj openpyxl` (accès PyPI nécessaire :
un workspace avec protection de l'accès sortant le bloque). Le reste (pandas, numpy, scipy, scikit-learn, pyarrow,
matplotlib, requests, joblib) est dans le runtime Fabric. Le projet est développé en Python 3.9 ; le code est
compatible 3.10/3.11.

## Étapes

### 1. Uploader le projet dans le Lakehouse

Dans le Lakehouse, *Files* → créer un dossier `mobiliscore`, puis y uploader en gardant l'arborescence :

```
Files/mobiliscore/
├── Config.py
├── src/            (tout le dossier)
└── outputs/        (seulement pour la voie rapide, voir plus bas ; sans outputs/cache/)
```

Le chemin est fixé dans la première cellule de chaque notebook (`FABRIC_PROJECT = "/lakehouse/default/Files/mobiliscore"`).
Si vous choisissez un autre dossier, modifiez cette ligne (`python notebooks/make_notebooks.py` la régénère partout).

### 2. Importer les notebooks et attacher le Lakehouse

1. Workspace → *Import* → *Notebook* → *From this computer* → sélectionner les 16 fichiers de `notebooks/`.
2. Dans chaque notebook : panneau *Explorer* → *Add data items* → choisir le Lakehouse et le définir **par défaut**.
   Sans Lakehouse par défaut, `/lakehouse/default/` n'existe pas et la première cellule ne fait rien.

### 3. Produire les tables : deux voies

**Voie rapide (recommandée pour le rapport)** : uploader `outputs/` depuis une machine où le pipeline a tourné
(sans `outputs/cache/`), puis lancer **seulement `08_export_fabric`**. Il ne recalcule rien : il relit les sorties
et écrit les tables Delta. Ne relancez pas `06b`/`06c` sur des modèles `.joblib` produits ailleurs : un pickle
scikit-learn / numpy 2 n'est pas garanti lisible par une autre version (relancer alors `05_model` dans Fabric).

**Pipeline complet**, dans cet ordre (chaque étape lit les sorties des précédentes) :

`00_geo` → `01_download` → `02_population` → `03_offer` → `03b_walk_calibration` → `04_accessibility` →
`04b_frequency` → `05_model` → `05c_usage` → `05b_territories` → `06a_optimize` → `06b_recommend` →
`06c_scenarios` → `07_figures` → `08_export_fabric`

- `01_download` télécharge environ 700 Mo de données ouvertes : la session doit avoir accès à Internet.
- `04b_frequency` doit précéder `05b` et `06b`, qui pondèrent l'offre de bus par la fréquence des lignes.
- `05c_collect_gbfs` est à part : un relevé par exécution, à **planifier toutes les 5 minutes** (de préférence
  en *Python notebook*, sans Spark, pour ne pas démarrer une session Spark à chaque relevé). `05c_usage` lit ces relevés.
- `06c_scenarios` est long (de l'ordre d'une heure sur 4 processus) ; son cache est signé (modèles, offre,
  accessibilité, fréquence, grille) et recalculé seulement si l'une de ces entrées change.
- Pour enchaîner automatiquement : *New item* → *Data pipeline*, une activité *Notebook* par étape, reliées *On success*.

### 4. Tables écrites par `08_export_fabric`

`08_export_fabric` écrit des **tables Delta** (`saveAsTable` dans un notebook Spark, `deltalake` dans un notebook
Python) : elles apparaissent sous *Tables* du Lakehouse. Une copie parquet reste dans `outputs/fabric/`.

| Table | Grain | Visuels |
|---|---|---|
| `carreaux` | carreau 200 m (≥ 11 ménages, secret statistique INSEE) | carte (`lat`, `lon`, couleur = `score`) ; filtrer par territoire (Azure Maps ≈ 30 000 points max) |
| `communes` | commune (`epci` ajouté, noms des arrondissements PLM) | choroplèthe, classement par `score_mean`, `share_pop_served` |
| `stations` | point d'offre existant | carte par `mode_libelle` |
| `recommandations` | site proposé × zone (budget 1 M€ par financeur, λ = 0,5) | carte, tableau trié par `rank` |
| `territoires_citiz` | intercommunalité | classement (`rank`), adhérents potentiels, risque |
| `acces_par_mode` | périmètre × mode | barres : part de la population desservie |
| `acces_par_decile` | périmètre × décile de revenu | courbe revenu / accès (préférer « France (secret statistique) ») |
| `modele_metriques`, `modele_importance` | modèle × métrique ; variable | qualité et variables des modèles |
| `scenarios_sites` | site × territoire × financeur × budget × λ | carte et liste du scénario choisi par les curseurs |
| `scenarios_resume` | territoire × financeur × budget × λ | KPI du scénario, courbe « prix de l'équité » |
| `dim_zone`, `dim_financeur` | territoire ; financeur | segments |
| `param_budget_citiz`, `param_budget_collectivite`, `param_lambda` | valeurs des curseurs | tables **déconnectées** des curseurs |

Clés : `zone` (ex. `epci200046977`, `ems`, `dep54`) relie `dim_zone`, `scenarios_*` et `recommandations` ;
`epci` (SIREN, 9 caractères ; Eurométropole = `246700488`) relie `dim_zone`, `communes` et `territoires_citiz` ;
`com` (code INSEE, 5 caractères) relie `communes` et `carreaux`. Les curseurs filtrent des **entiers**
(`budget_k_eur` de 100 à 5 000, `lambda_x10` de 0 à 10) : un λ décimal ne s'égalise pas de façon fiable en DAX.

La grille couvre les 10 premiers territoires du classement Citiz et l'Eurométropole de Strasbourg (témoin) ;
le territoire prioritaire (rang 1) est `zone_par_defaut`. Plus de territoires : `python -m src.scenarios --top 20`.

## 5. Rapport Power BI

1. Lakehouse → *New semantic model* → cocher les tables (mode Direct Lake).
2. Relations un-à-plusieurs, filtre simple :
   - `dim_zone[zone]` → `scenarios_resume[zone]`, `scenarios_sites[zone]`, `recommandations[zone]`
   - `dim_financeur[financeur]` → ces trois mêmes tables
   - `dim_zone[epci]` → `communes[epci]` ; `communes[com]` → `carreaux[com]`
   - `param_*` : aucune relation.
3. Mesures (les variables sont obligatoires : une mesure ne sert pas de prédicat dans `CALCULATE`) :

```dax
Budget Citiz (k€) = SELECTEDVALUE ( param_budget_citiz[budget_k_eur], 1000 )
Budget collectivité (k€) = SELECTEDVALUE ( param_budget_collectivite[budget_k_eur], 1000 )
Lambda x10 = SELECTEDVALUE ( param_lambda[lambda_x10], 5 )

Habitants nouvellement desservis =
VAR bc = [Budget Citiz (k€)]  VAR bp = [Budget collectivité (k€)]  VAR l = [Lambda x10]
RETURN
    CALCULATE ( SUM ( scenarios_resume[pop_newly_served] ), scenarios_resume[financeur] = "citiz",
                scenarios_resume[budget_k_eur] = bc, scenarios_resume[lambda_x10] = l,
                KEEPFILTERS ( VALUES ( dim_financeur[financeur] ) ) )
  + CALCULATE ( SUM ( scenarios_resume[pop_newly_served] ), scenarios_resume[financeur] = "collectivite",
                scenarios_resume[budget_k_eur] = bp, scenarios_resume[lambda_x10] = l,
                KEEPFILTERS ( VALUES ( dim_financeur[financeur] ) ) )
```

Même modèle pour `[Coût (€)]` (`cost_eur`), `[Sites]` (`n_sites`), `[CO2 évité (t/an)]` (`co2_avoided_t_yr`) et
`[Sortis de 0 option]` (`pop_from_zero_option`). Puis :

```dax
€ par habitant = DIVIDE ( [Coût (€)], [Habitants nouvellement desservis] )

-- filtre de visuel (= 1) des cartes et tableaux de sites
Site du scénario =
VAR f = SELECTEDVALUE ( scenarios_sites[financeur] )
VAR b = IF ( f = "citiz", [Budget Citiz (k€)], [Budget collectivité (k€)] )
RETURN IF ( SELECTEDVALUE ( scenarios_sites[budget_k_eur] ) = b
            && SELECTEDVALUE ( scenarios_sites[lambda_x10] ) = [Lambda x10], 1, 0 )

-- courbe « prix de l'équité » : axe X = scenarios_resume[lambda_x10], légende = financeur
Habitants (tous λ, budget choisi) =
VAR f = SELECTEDVALUE ( dim_financeur[financeur] )
VAR b = IF ( f = "citiz", [Budget Citiz (k€)], [Budget collectivité (k€)] )
RETURN CALCULATE ( SUM ( scenarios_resume[pop_newly_served] ), KEEPFILTERS ( scenarios_resume[budget_k_eur] = b ) )
```

4. Segments : `dim_zone[zone_nom]` (sélection unique, `zone_par_defaut` présélectionné), `dim_financeur[libelle]`,
   et les trois paramètres en curseurs (*Slicer* → style *Single value*).

À savoir :

- `carreaux` ne garde que les carreaux d'au moins 11 ménages (82 % de la population). Pour les chiffres nationaux,
  utiliser `acces_par_mode` et `acces_par_decile`, calculés sur tous les carreaux.
- Les figures PNG de `07_figures` ne passent pas dans Power BI : ce sont des images, à refaire avec les visuels.
- L'application Streamlit (`app.py`) ne tourne pas dans Fabric ; le rapport Power BI la remplace.
