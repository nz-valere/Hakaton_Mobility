# Notes orales – soutenance Mobili'Score (environ 10 min + démo)

Ouvrir `slides/presentation.html` dans un navigateur : ← → pour naviguer, `#n` dans l'URL pour aller à la slide n, impression possible en PDF.

**Répartition des rôles.** Les lettres sont à remplacer par les prénoms. Chacun doit savoir expliquer toute la démarche et répondre en profondeur sur sa partie.

| Orateur | Partie | Slides | Questions probables du jury |
|---|---|---|---|
| **A** – produit / métier | problème, chiffres, apport pour Citiz, suite | 1, 2, 3, 11, 14 (suite) | « Qu'est-ce que Citiz en fait concrètement ? » |
| **B** – données / accessibilité | carte, sources, calibration marche, équité | 4, 5, 6 | « Pourquoi 282 m ? Pourquoi pas le 2SFCA ? DROM ? » |
| **C** – modèle / optimisation | modèle, optimisation, recommandation, comparaison | 7, 8, 9, 10 | « Fuite spatiale ? Biais PU ? Garantie du glouton ? » |
| **D** – éthique / démo | éthique, limites, démo live | 12, 13, 14 (démo) | « Stigmatisation ? Vie privée ? CO2 ? » |

Tous les chiffres sont dans `outputs/` : `access_summary.json`, `walk_calibration.json`, `model_metrics.json`, `recommendations_summary.json` et `recommendations.csv`.

---

### 1. Titre (A, 20 s)
« Notre question est simple : qui a vraiment une option de transport à 5 minutes à pied de chez soi, et où faut-il en ajouter ? On y répond pour toute la France, puis on fait une recommandation chiffrée pour Strasbourg. »

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
- Résultat Citiz : PR-AUC de 0,46 contre 0,26 pour la population seule. On choisit la PR-AUC car seulement 8 % des carreaux sont positifs.
- **Honnêteté** : le modèle ne sait pas dire combien de voitures mettre. Pour la capacité, il ne bat pas la baseline. On l'a mesuré, et on ne le prétend pas.

### 8. Optimisation (C, 60 s)
- On maximise les habitants **nouvellement** desservis, pondérés par le besoin et par la valeur du modèle, à budget fixé. Les zones déjà desservies ne comptent pas.
- C'est un problème NP-difficile. On utilise un glouton paresseux avec une garantie théorique de (1 − 1/e)/2. **On l'a testé contre la force brute** : 97 % de l'optimum en moyenne.
- **Les enveloppes par financeur et le quota peu dense sont des choix politiques**, pas des sorties du modèle. Ils sont réglables dans `Config.py` et leur coût est chiffré (slide 10).

### 9. Recommandation Strasbourg (C, 60 s)
- Avec 2 M€ sur 5 ans, on obtient **28 sites** : 14 stations vélo, 12 stations Citiz et 2 arrêts de bus.
- **68 465 habitants** gagnent une option à 5 minutes, pour **29 € par habitant**.
- Environ **106 tonnes de CO2** sont évitées par an.
- **50,4 %** des nouveaux desservis sont dans les 3 déciles les plus modestes.
- Pourquoi Strasbourg : Citiz y est déjà très présent (46,5 % de la population à 5 minutes d'une station Citiz ou d'autopartage), les données y sont complètes (CTS, Vélhop, Citiz, OSM), et le territoire mêle un centre dense et du périurbain.

### 10. Avec ou sans l'outil (C, 45 s)
- À budget égal, la stratégie naïve « là où il y a du monde » ne dessert que 39 067 nouveaux habitants. Elle met des stations là où les gens en ont déjà.
- **Notre recommandation dessert 1,75 fois plus d'habitants**, et évite 106 t de CO2 contre 22 t.
- Transparence : sans les enveloppes et le quota, on pourrait atteindre 90 324 habitants, mais avec presque uniquement du vélo en centre-ville, 35 t de CO2 et moins de ménages modestes. C'est un arbitrage que la collectivité doit faire en connaissance de cause.

### 11. Ce que ça apporte à Citiz (A, 50 s)
- **Où** : 12 stations nommées, avec coordonnées. Elles touchent 28 320 nouveaux habitants à 5 minutes d'une voiture partagée.
- **Pourquoi** : chaque site est justifié par les habitants gagnés, le coût, le CO2 et le profil des ménages.
- **Partout** : `--dep 54` relance l'analyse sur la Meurthe-et-Moselle en quelques secondes.
- **Climat** : les stations Citiz pèsent 90 t sur les 106 t de CO2 évitées. Une voiture partagée remplace plusieurs voitures personnelles (ADEME/6t).

### 12. Éthique (D, 60 s)
- **CO2** : hypothèses prudentes. Le détour des bus est retranché ; en Meurthe-et-Moselle, deux arrêts ont un bilan négatif, et on l'affiche.
- **Équité** : les zones déjà desservies valent zéro, 15 % du budget va au peu dense, et λ règle la priorité sociale. On montre toujours la comparaison avec λ = 0.
- **Stigmatisation** : on parle d'« offre à développer », avec des rangs relatifs à la zone et aucun palmarès de communes.
- **Vie privée** : aucune statistique sociale sous 11 ménages. Seuls 23 % des carreaux atteignent ce seuil seuls, mais ils regroupent 82 % des habitants. Les autres sont lissés au km² ou masqués.

### 13. Limites (D, 45 s)
- Dire les limites avant que le jury les cite :
  - le cercle est calibré sur une seule ville ;
  - il n'y a pas de fréquence de passage ;
  - les coûts sont hypothétiques ;
  - la valeur du modèle est plafonnée sur les meilleurs sites, donc c'est la population qui départage ;
  - le modèle apprend des biais passés des opérateurs ;
  - il n'y a pas de free-floating à Strasbourg dans les flux publics ;
  - l'emprise est une boîte, pas la liste des communes.
- Renvoyer vers le document interne DEMARCHE.pdf, section 8.

### 14. Démo et suite (D pour la démo, A pour la suite ; 2-3 min de démo)
- Lancer `.venv/bin/python -m streamlit run app.py` **avant** la soutenance : le premier chargement est plus lent.
- Parcours de la démo :
  1. carte nationale ;
  2. zoom sur l'Eurométropole ;
  3. onglet « Qui est concerné » (stations et habitants servis) ;
  4. onglet « Où investir » : bouger le curseur λ et le budget, montrer que la liste et les indicateurs changent.
- Suite (A) :
  - confronter le modèle aux réservations Citiz réelles ;
  - pondérer par la fréquence ;
  - porter le pipeline sur Microsoft Fabric (lakehouse, notebooks, MLflow, Power BI). Si le jury demande pourquoi on ne l'a pas fait pendant le hackathon : reproductibilité, tests pytest et revue de code ; le découpage en Parquet rend le portage direct.

**Chronométrage** : environ 11 min de slides. Si le temps est serré, raccourcir les slides 4 et 8.
