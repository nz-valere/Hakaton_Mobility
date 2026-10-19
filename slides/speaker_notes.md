# Notes orales – soutenance Mobili'Score (environ 10 min + démo)

Ouvrir `slides/presentation.html` dans un navigateur : ← → pour naviguer, `#n` dans l'URL pour aller à la slide n, impression possible en PDF.

**Répartition des rôles.** Les lettres sont à remplacer par les prénoms. Chacun doit savoir expliquer toute la démarche et répondre en profondeur sur sa partie.

| Orateur | Partie | Slides | Questions probables du jury |
|---|---|---|---|
| **A** – produit / métier | problème, chiffres, apport pour Citiz, suite | 1, 2, 3, 12, 15 (suite) | « Qu'est-ce que Citiz en fait concrètement ? Pourquoi Nice ? » |
| **B** – données / accessibilité | carte, sources, calibration marche, équité | 4, 5, 6 | « Pourquoi 282 m ? Pourquoi pas le 2SFCA ? DROM ? » |
| **C** – modèle / optimisation | modèle, optimisation, choix du territoire, recommandation, comparaison | 7, 8, 9, 10, 11 | « Fuite spatiale ? Biais PU ? Garantie du glouton ? Modèle appris où ? » |
| **D** – éthique / démo | éthique, limites, démo live | 13, 14, 15 (démo) | « Stigmatisation ? Vie privée ? CO2 ? » |

Tous les chiffres sont dans `outputs/` : `access_summary.json`, `walk_calibration.json`, `model_metrics.json`, `territories_summary.json`, `territories_citiz.csv`, `recommendations_summary.json` et `recommendations.csv` (Nice), `recommendations_summary_ems.json` (Strasbourg, témoin).

---

### 1. Titre (A, 20 s)
« Notre question est simple : qui a vraiment une option de transport à 5 minutes à pied de chez soi, et où faut-il en ajouter ? On y répond pour toute la France, on choisit le territoire où Citiz a le plus à gagner (Nice), puis on y fait une recommandation chiffrée. »

### 2. Le problème (A, 45 s)
- Citiz a environ 2 800 voitures dans environ 280 villes et doit choisir où ouvrir. Une station mal placée immobilise une voiture.
- Les données sont ouvertes depuis la loi LOM, mais aucune source ne suffit seule.
- On répond aux trois objectifs : la carte, qui est concerné, où investir. Le troisième est le cœur du projet.

### 3. 36 % (A, 45 s)
- **36 % des habitants n'ont aucune option à 5 minutes.** On a analysé 63,8 millions d'habitants, en Métropole, en Martinique et à La Réunion.
- Le bus couvre 62 % de la population, le vélo en libre-service 12 %. **Citiz seulement 3,5 %** : la marge de développement est énorme.
- Transition : « Où sont ces gens ? »

### 4. La carte (B, 50 s)
- On croise quatre sources : population INSEE au carreau de 200 m (2,3 millions de carreaux), 207 973 arrêts et stations dédoublonnés, réseau piéton OSM, projections 2040.
- Le score va de 0 à 100. Gris = aucune option. Sinon, c'est le rang national : un score de 80 signifie mieux doté que 80 % des habitants desservis.
- **Si on demande « options par habitant »** : on compte les options accessibles depuis le domicile de chaque habitant. Le ratio offre/population (2SFCA) rendrait un hameau qui a un seul arrêt « plus chaud » que le centre de Strasbourg. On l'exporte quand même pour l'analyse de sensibilité.
- **DROM** : la Guadeloupe, la Guyane et Mayotte ne sont pas couvertes par les carreaux INSEE. Le dire franchement.

### 5. Courbe en U (B, 50 s)
- Message clé : **ce ne sont pas les plus modestes les plus exposés.** Le 1er décile n'a que 18 % de personnes sans option, contre 45 % pour le 6e et 25 % pour le 10e.
- Les ménages modestes vivent davantage dans des quartiers denses. Les classes moyennes, elles, vivent davantage dans le pavillonnaire. C'est notre interprétation, pas un résultat testé.
- Conséquence pour l'outil : le besoin combine pauvreté, absence de voiture et faible accès actuel. Le revenu seul ne suffit pas.
- Objectif 2 : chaque arrêt affiche sa population desservie. La médiane est de 289 habitants pour un arrêt de bus et de 1 750 pour une station Citiz.

### 6. Calibration marche (B, 60 s)
- 5 minutes à pied, c'est 400 m de trottoir, pas 400 m à vol d'oiseau. On a mesuré le détour réel sur le graphe piéton OSM de Strasbourg, à partir de 400 origines tirées selon la population.
- On retient **282 m** (détour 1,42) : c'est le rayon qui rend le **comptage** non biaisé. On compte des options, donc c'est le bon critère.
- Validation contre les vraies distances réseau : précision 0,92, rappel 0,99, biais de +5 %. **Un cercle naïf de 400 m doublerait le nombre d'options.**

### 7. Le modèle (C, 75 s)
- Idée : **l'offre existante révèle la demande.** Les opérateurs ont placé leurs stations là où ça marche. On apprend à reconnaître les carreaux qui ressemblent à ces sites.
- Rigueur, trois points :
  1. **Anti-fuite** : les modes cibles sont exclus des variables.
  2. **Positif-non étiqueté** : on n'apprend que dans les communes où le réseau existe, sinon une absence ne veut rien dire.
  3. **Validation croisée spatiale par département** : une validation aléatoire mesurerait surtout la proximité géographique.
- Résultat Citiz : PR-AUC de 0,48 contre 0,26 pour la population seule. On choisit la PR-AUC car seulement 8 % des carreaux sont positifs.
- **Quel modèle, appris où ?** Un gradient boosting (HistGradientBoosting de scikit-learn), retenu face à une régression logistique sur la PR-AUC. Il est appris sur les 80 départements où l'autopartage existe (107 672 carreaux), **pas sur Strasbourg seule** : 2 800 carreaux ne suffiraient pas, et le modèle doit être transposable à Nice. Strasbourg sert de **test** : avec le Bas-Rhin tenu hors de l'apprentissage, le modèle retrouve les carreaux réellement équipés avec une PR-AUC de 0,66 contre 0,59 pour la population seule. Il bat la population seule dans 55 départements sur 67. Pour Nice, chaque carreau est scoré par un modèle qui n'a pas vu les Alpes-Maritimes.
- **Honnêteté** : le modèle ne sait pas dire combien de voitures mettre. Pour la capacité, il ne bat pas la baseline. On l'a mesuré, et on ne le prétend pas.

### 8. Optimisation (C, 60 s)
- On maximise les habitants **nouvellement** desservis, pondérés par le besoin et par la valeur du modèle, à budget fixé. Les zones déjà desservies ne comptent pas.
- C'est un problème NP-difficile. On utilise un glouton paresseux avec une garantie théorique de (1 − 1/e)/2. **On l'a testé contre la force brute** : 97 % de l'optimum en moyenne.
- **Un budget par financeur** : Citiz ne gère que l'autopartage. On sépare donc 1 M€ Citiz (stations d'autopartage) et 1 M€ collectivité (vélo et bus), avec deux listes indépendantes.
- **Le quota peu dense (15 %) est un choix politique**, pas une sortie du modèle. Il est réglable dans `Config.py`.

### 9. Quel territoire ? (C, 75 s)
- Le sujet demande où Citiz doit s'implanter. Avant de placer des stations, on choisit **le territoire**.
- **Criblage** des 99 intercommunalités de plus de 100 000 habitants. Pour chacune, on calcule les habitants des quartiers denses sans aucun autopartage à 5 min, pondérés par la valeur du modèle.
- **Simulation** : sur les 10 premières, on lance le vrai optimiseur avec 1 M€ Citiz, et on classe par adhérents potentiels.
- **Nice arrive en tête** : 16 stations y desservent 85 573 habitants et 7 300 adhérents potentiels, contre 33 740 et 1 400 à Strasbourg. Suivent Lyon et Montpellier.
- **Pourquoi pas Strasbourg ?** Citiz y couvre déjà 45 % des habitants : il reste des quartiers moins denses. On garde Strasbourg comme **territoire témoin**, là où le modèle est le mieux validé.
- **Contexte terrain** : Mobilize Share (Renault), le principal autopartage en stations de la métropole niçoise, a fermé fin juin 2026. Le vide est récent.
- **Île-de-France exclue** : son autopartage (Getaround, Zity, Communauto) n'est presque pas publié en GBFS, d'où une couverture apparente de 1 %.

### 10. Recommandation Nice (C, 60 s)
- **Pour Citiz**, avec 0,96 M€ sur 5 ans : **16 stations**, dont 14 à Nice, une à Beaulieu-sur-Mer et une à Saint-Martin-du-Var (quota peu dense).
- **85 573 habitants** passent à 5 minutes d'une voiture partagée, pour **11 € par habitant** (28 € à Strasbourg).
- Environ **121 t de CO2** évitées par an ; **48 %** des nouveaux desservis sont dans les 3 déciles les plus modestes.
- **Pour la collectivité**, liste séparée : 9 stations vélo et 2 arrêts de bus, soit 48 494 nouveaux desservis pour 0,95 M€. Attention : Vélo Bleu existe mais ne publie pas de flux GBFS, ces stations vélo sont à confronter au réseau réel.

### 11. Avec ou sans l'outil (C, 45 s)
- On montre cette comparaison sur Strasbourg, car c'est là que l'offre existante pèse : à Nice, il n'y a rien à éviter.
- À budget Citiz égal, la stratégie naïve « là où il y a du monde » ne dessert que 13 800 nouveaux habitants, contre 33 740 : **2,4 fois moins**, car elle place des stations à côté des existantes.
- **Honnêteté sur le modèle** : sans lui, on toucherait 19 % d'habitants de plus (41 493), mais avec 28 % de CO2 évité en moins (94 t contre 120 t). Le modèle vise les sites où l'usage attendu est plus fort. C'est un arbitrage, pas un gain gratuit.

### 12. Ce que ça apporte à Citiz (A, 50 s)
- **Où s'implanter** : un classement national simulé à budget égal, avec Nice en tête, Lyon et Montpellier ensuite.
- **Où ouvrir** : 16 stations nommées, avec coordonnées, et pour chacune les habitants gagnés, la valeur du modèle, le coût et le CO2.
- **Combien de voitures** : la demande estimée justifierait jusqu'à environ 10 voitures par station. C'est une borne haute (pénétration nationale Citiz) : on recommande un pilote à 1-2 voitures par station, suivi des réservations.
- **Partout** : `--area epci:<siren>` ou `--dep 54` relance l'analyse en quelques secondes.

### 13. Éthique (D, 60 s)
- **CO2** : hypothèses prudentes. Le détour des bus est retranché ; en Meurthe-et-Moselle, deux arrêts ont un bilan négatif, et on l'affiche.
- **Équité** : les zones déjà desservies valent zéro, 15 % du budget va au peu dense, et λ règle la priorité sociale. On montre toujours la comparaison avec λ = 0.
- **Stigmatisation** : on parle d'« offre à développer », avec des rangs relatifs à la zone et aucun palmarès de communes. Le classement des territoires mesure un potentiel pour Citiz, pas un retard.
- **Vie privée** : aucune statistique sociale sous 11 ménages. Seuls 23 % des carreaux atteignent ce seuil seuls, mais ils regroupent 82 % des habitants. Les autres sont lissés au km² ou masqués.

### 14. Limites (D, 45 s)
- Dire les limites avant que le jury les cite :
  - le cercle est calibré sur une seule ville ;
  - il n'y a pas de fréquence de passage ;
  - les coûts sont hypothétiques ;
  - le modèle mesure une ressemblance avec les sites existants, pas une fréquentation ;
  - le modèle apprend des biais passés des opérateurs ;
  - l'offre non publiée en GBFS est invisible (Getaround, Vélo Bleu à Nice) : le classement des territoires est à confirmer sur le terrain ;
  - le nombre de voitures par station est une borne haute.
- Renvoyer vers EXPLICATIONS.md, section « Ce qu'il faut garder en tête ».

### 15. Démo et suite (D pour la démo, A pour la suite ; 2-3 min de démo)
- Lancer `.venv/bin/python -m streamlit run app.py` **avant** la soutenance : le premier chargement est plus lent.
- Parcours de la démo :
  1. carte nationale ;
  2. onglet « Où s'implanter (France) » : le classement, Nice en tête, Strasbourg en témoin ;
  3. territoire prioritaire (Nice), onglet « Qui est concerné » (stations et habitants servis) ;
  4. onglet « Où investir » : bouger le budget Citiz, le budget collectivité et λ, montrer que les deux listes changent ;
  5. si le temps le permet, basculer sur Strasbourg pour comparer.
- Suite (A) :
  - confronter le modèle aux réservations Citiz réelles ;
  - pondérer par la fréquence ;
  - porter le pipeline sur Microsoft Fabric (lakehouse, notebooks, MLflow, Power BI). Si le jury demande pourquoi on ne l'a pas fait pendant le hackathon : reproductibilité, tests pytest et revue de code ; le découpage en Parquet rend le portage direct.

**Chronométrage** : environ 11 min de slides. Si le temps est serré, raccourcir les slides 4 et 8.
