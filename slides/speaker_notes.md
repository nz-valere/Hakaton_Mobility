# Notes orales – soutenance Mobili'Score (environ 13 min + démo)

Ouvrir `slides/presentation.html` dans un navigateur : ← → pour naviguer, `#n` dans l'URL pour aller à la slide n, impression possible en PDF.

**Répartition des rôles.** Les lettres sont à remplacer par les prénoms. Chacun doit savoir expliquer toute la démarche et répondre en profondeur sur sa partie.

| Orateur | Partie | Slides | Questions probables du jury |
|---|---|---|---|
| **A** – produit / métier | problème, chiffres, apport pour Citiz, suite | 1, 2, 3, 15, 18 (suite) | « Qu'est-ce que Citiz en fait concrètement ? Pourquoi Lyon et pas Nice ? » |
| **B** – données / accessibilité | carte, sources, calibration marche, équité, fréquence | 4, 5, 6, 7 | « Pourquoi 282 m ? Pourquoi pas le 2SFCA ? Et la fréquence ? DROM ? » |
| **C** – modèle / optimisation | modèle, usage réel, optimisation, territoire, recommandation, comparaison | 8, 9, 10, 11, 12, 14 | « Fuite spatiale ? Biais PU ? Le modèle prédit-il l'usage ? Garantie du glouton ? » |
| **D** – éthique / démo | prix de l'équité, éthique, limites, démo live | 13, 16, 17, 18 (démo) | « Stigmatisation ? Vie privée ? CO2 ? Combien coûte l'équité ? » |

Tous les chiffres sont dans `outputs/` : `access_summary.json`, `walk_calibration.json`, `frequency_epci200046977.json` (Lyon), `frequency_epci200030195.json` (Nice) et `frequency_ems.json`, `model_metrics.json`, `usage_validation.json`, `territories_summary.json`, `territories_citiz.csv`, `recommendations_summary.json`, `recommendations.csv` et `equity_curve.json` (Lyon), `recommendations_summary_ems.json` (Strasbourg, témoin). Pipeline relancé le 20/10/2026 avec les flux du jour.

---

### 1. Titre (A, 20 s)
« Notre question est simple : qui a vraiment une option de transport à 5 minutes à pied de chez soi, et où faut-il en ajouter ? On y répond pour toute la France, on choisit le territoire où Citiz a le plus à gagner (Lyon), puis on y fait une recommandation chiffrée. »

### 2. Le problème (A, 45 s)
- Citiz a environ 2 800 voitures dans environ 280 villes et doit choisir où ouvrir. Une station mal placée immobilise une voiture.
- Les données sont ouvertes depuis la loi LOM, mais aucune source ne suffit seule.
- On répond aux trois objectifs : la carte, qui est concerné, où investir. Le troisième est le cœur du projet.

### 3. 33 % (A, 45 s)
- **Un habitant sur trois (33,5 %) n'a aucune option à 5 minutes.** C'est une borne basse : notre cercle de 282 m dessert 89 % des Strasbourgeois, contre 84 % sur le vrai réseau ; sur le réseau, on serait plutôt à 38 %. On a analysé 63,8 millions d'habitants, en Métropole, en Martinique et à La Réunion.
- Le bus couvre 66 % de la population, le vélo en libre-service 12 %. **Citiz seulement 3,5 %** : la marge de développement est énorme.
- Transition : « Où sont ces gens ? »

### 4. La carte (B, 50 s)
- On croise quatre sources : population INSEE au carreau de 200 m (2,3 millions de carreaux), 220 666 arrêts et stations dédoublonnés, réseau piéton OSM, projections 2040.
- Le score va de 0 à 100. Gris = aucune option. Sinon, c'est le rang national : un score de 80 signifie mieux doté que 80 % des habitants desservis.
- **Si on demande « options par habitant »** : on compte les options accessibles depuis le domicile de chaque habitant. Le ratio offre/population (2SFCA) rendrait un hameau qui a un seul arrêt « plus chaud » que le centre de Strasbourg. On l'exporte quand même pour l'analyse de sensibilité.
- **DROM** : la Guadeloupe, la Guyane et Mayotte ne sont pas couvertes par les carreaux INSEE. Le dire franchement.

### 5. Qui est concerné (B, 50 s)
- Message clé : **ce ne sont pas les plus modestes les plus exposés.** Sur les carreaux où le revenu est mesuré (au moins 11 ménages), le 1er décile n'a que 11 % de personnes sans option, contre 29 % pour le 6e et 18 % pour le 10e. Si on nous oppose les 43 % : sur tous les carreaux, l'imputation INSEE des petits carreaux ruraux amplifie la bosse ; on publie la version prudente.
- Les ménages modestes vivent davantage dans des quartiers denses. Les classes moyennes, elles, vivent davantage dans le pavillonnaire. C'est notre interprétation, pas un résultat testé.
- Conséquence pour l'outil : le besoin combine pauvreté, absence de voiture et faible accès actuel. Le revenu seul ne suffit pas.
- Objectif 2 : chaque arrêt affiche sa population desservie. La médiane est de 293 habitants pour un arrêt de bus et de 1 750 pour une station Citiz.

### 6. Calibration marche (B, 60 s)
- 5 minutes à pied, c'est 400 m de trottoir, pas 400 m à vol d'oiseau. On a mesuré le détour réel sur le graphe piéton OSM de Strasbourg, à partir de 400 origines tirées selon la population.
- On retient **282 m** (détour 1,42) : c'est le rayon qui rend le **comptage** juste. Contrepartie assumée : pour la question binaire « au moins une option », il surestime un peu la desserte (89 % contre 84 % à Strasbourg).
- Validation contre les vraies distances réseau : précision 0,92, rappel 0,99, biais de +5 %. **Un cercle naïf de 400 m doublerait le nombre d'options.**

### 7. Un arrêt n'est pas un service (B, 60 s)
- Le piège classique : **compter des arrêts**. Un arrêt où passent 2 bus par jour y vaut une station de tram toutes les 5 minutes, et une même ligne qui passe à 3 arrêts autour de chez soi compte 3 fois.
- L'agrégat national n'a pas d'horaires. Dans nos zones d'étude, on lit les **GTFS des réseaux** : TCL à Lyon, Lignes d'Azur à Nice, CTS et Fluo 67 à Strasbourg. Jour de référence : mardi 17 novembre 2026, hors vacances de la Toussaint, de 7 h à 20 h.
- Règle : une ligne compte **une fois**, avec sa meilleure fréquence parmi les arrêts proches, même si l'on atteint ses deux quais (aller et retour). Lignes scolaires et transport à la demande exclus. Une ligne toutes les 15 min ou mieux vaut une option pleine ; moins fréquente, une fraction.
- Résultat Lyon : 93 % des habitants ont un arrêt à 5 min, 78 % au moins une option pleine. **14,6 %, environ 189 000 habitants, ont un arrêt mais un service faible** : le comptage les classait comme desservis. C'est pire à Nice (20,7 %), comparable à Strasbourg (14,6 %).
- Ce que ça change dans la recommandation (slide 12) : un arrêt de bus posé sur une ligne peu fréquente vaut moins, et le besoin « faible accès » repère les quartiers mal servis en vrai.

### 8. Le modèle (C, 75 s)
- Idée : **l'offre existante révèle la demande.** Les opérateurs ont placé leurs stations là où ça marche. On apprend à reconnaître les carreaux qui ressemblent à ces sites.
- Rigueur, trois points :
  1. **Anti-fuite** : les modes cibles sont exclus des variables.
  2. **Positif-non étiqueté** : on n'apprend que dans les communes où le réseau existe, sinon une absence ne veut rien dire.
  3. **Validation croisée spatiale par département** : une validation aléatoire mesurerait surtout la proximité géographique.
- Résultat Citiz : PR-AUC de 0,48 contre 0,26 pour la population seule. On choisit la PR-AUC car seulement 8 % des carreaux sont positifs.
- **Quel modèle, appris où ?** Un gradient boosting (HistGradientBoosting de scikit-learn), retenu face à une régression logistique sur la PR-AUC. Il est appris sur les 80 départements où l'autopartage existe (108 037 carreaux), **pas sur Strasbourg seule** : 2 800 carreaux ne suffiraient pas, et le modèle doit être transposable à d'autres territoires. Strasbourg sert de **test** : avec le Bas-Rhin tenu hors de l'apprentissage, le modèle retrouve les carreaux réellement équipés avec une PR-AUC de 0,67 contre 0,59 pour la population seule. Il bat la population seule dans 56 départements sur 67. Pour Lyon, chaque carreau est scoré par un modèle qui n'a pas vu le Rhône.
- **Honnêteté** : le modèle ne sait pas dire combien de voitures mettre. Pour la capacité, il ne bat pas la baseline. On l'a mesuré, et on ne le prétend pas. Transition : « Alors, est-ce qu'il prédit l'usage ? On l'a vérifié. »

### 9. L'usage réel (C, 70 s)
- Le modèle apprend la **présence** des stations. Pour savoir s'il dit quelque chose de l'**usage**, il faut un signal indépendant : on a relevé les flux GBFS des **17 réseaux Citiz toutes les 5 minutes**. La part du temps où les voitures d'une station sont réservées donne son taux d'occupation, pour 1 512 stations.
- Résultat : les stations que le modèle juge les plus favorables sont nettement plus occupées, **41 % contre 28 %** pour le quintile le moins favorable.
- Mais station par station, le modèle **ne fait pas mieux que la population seule** (Spearman 0,17 contre 0,18, écart non significatif). On le dit tel quel : il repère les secteurs où Citiz tourne, pas encore l'usage d'une station. Les réservations de Citiz permettraient de le recalibrer.
- Bonus opérationnel : **303 stations saturées** (réservées plus de 60 % du temps relevé, 20 % du réseau). Y ajouter une voiture coûte moins cher qu'ouvrir une station, et la demande y est démontrée.
- Limites à dire avant qu'on les demande : 65 relevés sur 235 possibles en un jour, en partie pendant les vacances de la Toussaint ; sens exact de `is_reserved` à confirmer avec Citiz ; c'est une validation, pas un apprentissage.
- Vie privée : on ne garde que des **totaux par station**, jamais un identifiant ou une position de voiture.

### 10. Optimisation (C, 60 s)
- On maximise les habitants **nouvellement** desservis, pondérés par le besoin et par la valeur du modèle, à budget fixé. Les zones déjà desservies ne comptent pas.
- C'est un problème NP-difficile. On utilise un glouton paresseux avec une garantie théorique de (1 − 1/e)/2. **On l'a testé contre la force brute** : 97 % de l'optimum en moyenne.
- **Un budget par financeur** : Citiz ne gère que l'autopartage. On sépare donc 1 M€ Citiz (stations d'autopartage) et 1 M€ collectivité (vélo et bus), avec deux listes indépendantes.
- **Le quota peu dense (15 %) est un choix politique**, pas une sortie du modèle. Il est réglable dans `Config.py`.
- **Une enveloppe est un plafond** : un site d'enveloppe 5 fois moins rentable que le meilleur n'est pas acheté, son budget repart au pot commun. Sans cette règle, augmenter le budget pouvait faire baisser la couverture.

### 11. Quel territoire ? (C, 75 s)
- Le sujet demande où Citiz doit s'implanter. Avant de placer des stations, on choisit **le territoire**.
- **Criblage** des 99 intercommunalités de plus de 100 000 habitants. Pour chacune, on calcule les habitants des quartiers denses sans aucun autopartage à 5 min, pondérés par la valeur du modèle.
- **Simulation** : sur les 20 premières, on lance le vrai optimiseur avec 1 M€ Citiz.
- **Risque terrain** : le modèle ne voit pas l'histoire. On a relevé, ville par ville, les échecs passés, l'autopartage non publié en GBFS et le soutien de la collectivité. Adhérents retenus = adhérents du modèle × (1 − risque).
- **Nice, 1ʳᵉ pour le modèle (7 500 adhérents), tombe au 11ᵉ rang** : Auto Bleue (68 stations, environ 1,4 M€/an de délégation, recettes déficitaires) a fermé fin 2018, puis Mobilize Share est parti en juin 2026. Deux échecs, dont un en stations, le modèle même de Citiz : risque 65 %. Nice ne repasserait en tête qu'avec un risque sous 49 %.
- **Montpellier** recule aussi : Modulauto y a environ 100 stations hors GBFS.
- **Lyon arrive en tête** : 49 477 habitants et 3 847 adhérents, mais **Toulouse est à 0,9 %** (3 814), grâce au soutien de sa Métropole. Si on nous le demande : les deux sont défendables, Lyon a le plus grand marché. Bluely et Zity y ont échoué, mais en free-floating ; Citiz LPA en boucle tient et la Métropole veut le développer. Suivent Toulouse, où la Métropole a retenu Citiz pour 2025-2030, puis Aix-Marseille.
- **Pourquoi pas Strasbourg ?** Citiz y couvre déjà 45 % des habitants : il reste des quartiers moins denses. On garde Strasbourg comme **territoire témoin**, là où le modèle est le mieux validé.
- **Île-de-France exclue** : son autopartage (Getaround, Zity, Communauto) n'est presque pas publié en GBFS, d'où une couverture apparente de 1 %.

### 12. Recommandation Lyon (C, 60 s)
- **Pour Citiz**, avec 0,96 M€ sur 5 ans : **16 stations**, dont 7 à Villeurbanne, 7 dans les 3ᵉ, 7ᵉ et 8ᵉ arrondissements, et deux en zone peu dense (Vernaison, Genay).
- **49 477 habitants** passent à 5 minutes d'une voiture partagée, pour **19 € par habitant** (24 € à Strasbourg).
- Environ **121 t de CO2** évitées par an, soit ≈ 7,6 t par station (une voiture plafonne à ≈ 46 adhérents) ; **40 %** des nouveaux desservis sont dans les 3 déciles les plus modestes.
- **À dire avant qu'on le demande** : presque aucun de ces habitants n'était « sans option » (110). Citiz densifie là où il y a déjà un bus : la voiture partagée remplace la 2ᵉ voiture. Les sans-option sont surtout en périphérie peu dense : c'est le rôle du budget collectivité.
- **Pour la collectivité**, liste séparée : 16 stations vélo en périphérie (Vaulx-en-Velin, Saint-Priest, Givors, Rillieux…), soit **46 869** nouveaux desservis pour 0,96 M€, dont 85 % de ménages modestes.
- **Pourquoi aucun arrêt de bus ?** Avec nos hypothèses (aménagement plus exploitation du détour), un arrêt coûte plus de 200 k€ sur 5 ans pour quelques centaines d'habitants, contre 60 k€ pour une station vélo qui en dessert plus de 2 000. Sur une ligne qui passe déjà devant, ce serait différent : à vérifier avec les tracés.
- Les stations sont à coordonner avec Citiz LPA, coopérative du réseau déjà présente à Lyon.

### 13. Le prix de l'équité (D, 50 s)
- La priorité sociale λ n'est pas un réglage caché : on montre ce qu'elle coûte. Chaque point est une optimisation complète avec la même enveloppe, de λ = 0 à λ = 1.
- **Collectivité** : la part des ménages modestes parmi les nouveaux desservis passe de 74 % à 85 %, **et le nombre d'habitants augmente** (44 616 à λ = 0, 46 869 à λ = 1). À Lyon, l'équité ne coûte rien.
- **Citiz** : de 38 % à 40 % de ménages modestes au mieux, pour 2 % d'habitants en moins. Dans une métropole dense, c'est la densité qui décide.
- C'est le décideur qui choisit le point sur la courbe. Dans la démo, chaque mouvement de curseur relance l'optimisation en environ 1 seconde.

### 14. Avec ou sans l'outil (C, 45 s)
- On montre cette comparaison sur Strasbourg, territoire témoin où l'offre existante pèse le plus et où le modèle est le mieux validé.
- À budget Citiz égal, la stratégie naïve « là où il y a du monde » ne dessert que 13 800 nouveaux habitants, contre 39 260 : **2,8 fois moins**, car elle place des stations à côté des existantes. À Lyon : 15 493 contre 49 477, 3,2 fois moins.
- **Honnêteté sur le modèle** : sans lui, on toucherait 6 % d'habitants de plus à Strasbourg (41 551), mais avec 15 % de CO2 évité en moins (102 t contre 119 t). À Lyon l'arbitrage est plus net : 61 259 habitants sans modèle, contre 49 477, mais 73 t de CO2 contre 121. Le modèle vise les sites où l'usage attendu est plus fort. C'est un arbitrage, pas un gain gratuit.

### 15. Ce que ça apporte à Citiz (A, 50 s)
- **Où s'implanter** : un classement national simulé à budget égal, corrigé du risque terrain : Lyon en tête, Toulouse et Aix-Marseille ensuite ; Nice écartée après deux échecs.
- **Où ouvrir** : 16 stations nommées, avec coordonnées, et pour chacune les habitants gagnés, la valeur du modèle, le coût et le CO2.
- **Combien de voitures** : la demande estimée justifierait environ 6 voitures par station en moyenne, jusqu'à 8. C'est une borne haute (pénétration nationale Citiz) : on recommande un pilote à 1-2 voitures par station, suivi de l'occupation. Et dès aujourd'hui, **303 stations saturées** : une 2e voiture avant une nouvelle station.
- **Partout** : `--area epci:<siren>` ou `--dep 54` relance l'analyse en quelques secondes.

### 16. Éthique (D, 60 s)
- **CO2** : hypothèses prudentes. Le détour des bus est retranché ; un arrêt peut avoir un bilan négatif, et on l'affiche.
- **Équité** : un carreau déjà desservi par un équipement vaut zéro pour ce type, 15 % du budget va au peu dense, et λ règle la priorité sociale. Le prix de l'équité est affiché (slide 13).
- **Stigmatisation** : on parle d'« offre à développer », avec des rangs relatifs à la zone et aucun palmarès de communes. Le classement des territoires mesure un potentiel pour Citiz, pas un retard.
- **Vie privée** : aucune statistique sociale sous 11 ménages. Seuls 23 % des carreaux atteignent ce seuil seuls, mais ils regroupent 82 % des habitants. Les autres sont agrégés à la maille d'affichage ou masqués. La collecte GBFS ne garde que des totaux par station.

### 17. Limites (D, 45 s)
- Dire les limites avant que le jury les cite :
  - le cercle est calibré sur une seule ville, et « 1 sur 3 sans option » est une borne basse ;
  - la fréquence n'est lue qu'à Lyon, Nice et Strasbourg : ailleurs, un car scolaire compte autant qu'un tram ;
  - les coûts sont hypothétiques (SOURCES.md), et le CO2 Citiz suit le nombre de stations ;
  - le choix de Lyon devant Toulouse tient à 0,9 % ;
  - le modèle mesure une ressemblance avec les sites existants : face à l'usage réel, il ne classe pas l'usage mieux que la population seule ;
  - le modèle apprend des biais passés des opérateurs ;
  - l'offre non publiée en GBFS est invisible (Getaround, Modulauto, Vélo Bleu à Nice) : corrigée par une veille presse dont les pondérations sont des hypothèses ;
  - le nombre de voitures par station est une borne haute.
- Renvoyer vers EXPLICATIONS.md, section « Ce qu'il faut garder en tête ».

### 18. Démo et suite (D pour la démo, A pour la suite ; 2-3 min de démo)
- Lancer l'app **avant** la soutenance, le premier chargement est plus lent : `.venv/bin/python -m streamlit run app.py` (Windows : `.venv\Scripts\python -m streamlit run app.py`). Garder le PC allumé si la collecte GBFS tourne.
- Parcours de la démo :
  1. carte nationale ;
  2. onglet « Où s'implanter (France) » : le classement corrigé du risque, Lyon en tête au coude-à-coude avec Toulouse, Nice 11ᵉ, Strasbourg en témoin ;
  3. Lyon, carte d'accessibilité : basculer de « nombre d'arrêts » à « fréquence des lignes », montrer les 14,6 % de service faible ;
  4. onglet « Où investir » : bouger le budget Citiz et λ ; la liste se recalcule en environ 1 s et la courbe du prix de l'équité suit ; montrer les stations Citiz saturées ;
  5. si le temps le permet, basculer sur Strasbourg pour comparer.
- Suite (A) :
  - remplacer notre courte collecte par les réservations Citiz pour recalibrer le modèle sur l'usage ;
  - étendre la fréquence GTFS à toute la France ;
  - Microsoft Fabric est **déjà porté** : 16 notebooks générés depuis `src/` (même code, testé par pytest), tables Delta dans le Lakehouse, rapport Power BI dont les curseurs budget et λ filtrent 12 100 scénarios précalculés (FABRIC.md). Suite : MLflow pour les modèles et collecte GBFS planifiée dans Fabric.

**Chronométrage** : environ 13 min de slides. Si le temps est serré, raccourcir les slides 4, 10 et 14.
