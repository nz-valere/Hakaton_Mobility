# Mobili'Score dans Microsoft Fabric

Objectif : exécuter les notebooks dans Fabric et construire les visuels Power BI à partir de tables Delta.

## Ce qu'il faut créer et installer

| Quoi | Où | Pourquoi |
|---|---|---|
| Un **workspace** avec une capacité Fabric (ou d'essai) | portail Fabric | héberge le Lakehouse, les notebooks et le rapport |
| Un **Lakehouse** (ex. `mobiliscore_lh`) | workspace → *New item* → *Lakehouse* | stocke le projet (*Files*) et les tables Power BI (*Tables*) |
| Le **projet** dans `Files/mobiliscore/` | Lakehouse → *Files* → *Upload* | les notebooks importent `Config.py` et `src/` |
| Les **notebooks** `.ipynb` | workspace → *Import* → *Notebook* → *From this computer* | le code du pipeline |
| **`pyproj`** et **`openpyxl`** | rien à faire : la première cellule de chaque notebook les installe | absents du runtime Fabric par défaut |

Le reste (pandas, numpy, scipy, scikit-learn, pyarrow, matplotlib, requests, joblib) est déjà dans le runtime Fabric.
Le projet a été développé en Python 3.9 ; Fabric utilise une version plus récente, à vérifier au premier lancement.

Alternative à l'installation par cellule : créer un **Environment** (workspace → *New item* → *Environment*),
y ajouter `pyproj` et `openpyxl` dans *Public libraries*, le publier, puis le sélectionner dans chaque notebook.
Les installations sont alors faites une seule fois, au lieu de chaque session.

## Étapes

### 1. Uploader le projet dans le Lakehouse

Dans le Lakehouse, *Files* → créer un dossier `mobiliscore`, puis y uploader en gardant l'arborescence :

```
Files/mobiliscore/
├── Config.py
├── src/            (tout le dossier)
├── notebooks/      (facultatif : les notebooks s'importent à part, mais leur dossier doit exister)
└── outputs/        (seulement pour la voie rapide, voir plus bas)
```

Le chemin est fixé dans la première cellule de chaque notebook (`FABRIC_PROJECT = "/lakehouse/default/Files/mobiliscore"`).
Si vous choisissez un autre dossier, modifiez cette ligne.

### 2. Importer les notebooks et attacher le Lakehouse

1. Workspace → *Import* → *Notebook* → *From this computer* → sélectionner les fichiers de `notebooks/`.
2. Dans chaque notebook : panneau *Explorer* à gauche → *Add data items* → choisir le Lakehouse et le définir **par défaut**.
   Sans Lakehouse par défaut, le chemin `/lakehouse/default/` n'existe pas et la première cellule ne fait rien.

### 3. Produire les tables : deux voies

**Voie rapide (recommandée pour les visuels)** : uploader `outputs/` depuis une machine où le pipeline a déjà tourné
(fichiers `.parquet`, `.csv` et `.json`, environ 115 Mo sans `outputs/cache/`), puis lancer **seulement `08_export_fabric`**.

**Pipeline complet** : lancer les notebooks dans l'ordre :

`00_geo` → `01_download` → `02_population` → `03_offer` → `03b_walk_calibration` → `04_accessibility` → `05_model` → `05b_territories` → `06a_optimize` → `06b_recommend` → `06c_scenarios` → `07_figures` → `08_export_fabric`

`01_download` télécharge environ 700 Mo de données ouvertes (INSEE, data.gouv.fr, GBFS) : la session doit avoir accès à Internet.
Pour enchaîner automatiquement : *New item* → *Data pipeline*, une activité *Notebook* par étape, reliées *On success*.

### 4. Créer le rapport Power BI

1. Ouvrir le Lakehouse : les tables apparaissent sous *Tables* (actualiser si besoin).
2. *New semantic model* → cocher les tables.
3. Dans le modèle, créer les relations un-à-plusieurs `communes[com]` → `carreaux[com]` et `communes[com]` → `recommandations[com]`.
4. *New report* → construire les visuels.

## Tables exportées par `08_export_fabric`

| Table | Grain | Visuels suggérés |
|---|---|---|
| `carreaux` | carreau 200 m (≥ 11 ménages, secret statistique INSEE) | carte (`lat`, `lon`, couleur = `score`), filtres `decile_revenu`, `sans_option` |
| `communes` | commune | carte choroplèthe ou classement par `score_mean`, `share_pop_served` |
| `stations` | point d'offre existant | carte par `mode_libelle` |
| `recommandations` | site proposé × zone | carte des sites, tableau trié par `rank`, `cost_cum_eur` ; filtre `zone_nom` et `financeur` |
| `territoires_citiz` | intercommunalité | classement (`rank`), adhérents potentiels, risque |
| `acces_par_mode` | périmètre × mode | barres : part de la population desservie par mode |
| `acces_par_decile` | périmètre × décile de revenu | courbe en U : `part_sans_option` par `decile_revenu` |
| `modele_metriques` | type × modèle × métrique | qualité des modèles (ROC-AUC, PR-AUC) |
| `modele_importance` | type × variable | barres des variables les plus importantes |
| `scenarios_sites` | site × territoire × financeur × budget × λ | carte et liste des sites du scénario choisi par les curseurs |
| `scenarios_resume` | territoire × financeur × budget × λ | KPI du scénario, courbe « prix de l'équité » |

### Curseurs de l'app dans Power BI

Power BI n'exécute pas l'optimiseur : `06c_scenarios` (`python -m src.scenarios`) précalcule toute la grille des
curseurs de l'app sur les 10 premiers territoires du classement Citiz et l'Eurométropole de Strasbourg
(témoin, territoire par défaut) : budget de 0,1 à 5 M€ par pas de 0,1 M€, λ de 0 à 1 par pas
de 0,1, chaque financeur optimisé seul). Dans le rapport, trois paramètres *What-if* (*Modeling* → *New parameter*
→ *Numeric range*) reproduisent les curseurs, et des mesures filtrent `scenarios_sites` / `scenarios_resume`
sur le budget et le λ choisis ; un segment `zone_nom` choisit le territoire. Plus de territoires :
`python -m src.scenarios --top 20` (chaque territoire est mis en cache dans `outputs/cache/`).

À savoir :

- `carreaux` ne garde que les carreaux d'au moins 11 ménages (82 % de la population). Pour les chiffres nationaux,
  utiliser `acces_par_mode` et `acces_par_decile`, calculés sur tous les carreaux, plutôt que de sommer `carreaux`.
- Les figures PNG de `07_figures` ne passent pas dans Power BI : ce sont des images, à refaire avec les visuels.
- L'application Streamlit (`app.py`) ne tourne pas dans Fabric ; le rapport Power BI la remplace.
