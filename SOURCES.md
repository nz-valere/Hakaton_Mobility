# Sources de données

Toutes les données sont ouvertes et téléchargées automatiquement par `python -m src.download`
(URL exactes dans `Config.py`, dictionnaire `URLS`). Fichiers bruts dans `data/raw/` (non versionnés).

| Donnée | Producteur | Format / maille | Licence | Usage dans le projet | Fichier |
|---|---|---|---|---|---|
| Revenus, pauvreté et niveau de vie – Filosofi 2021, carreaux 200 m | INSEE | CSV, carreaux 200 m (Métropole, Martinique, La Réunion) | Licence Ouverte 2.0 | Population résidente, ménages, revenus, âges, logement | `filosofi2021_200m_csv.zip` |
| Recensement 2021 – base infracommunale Logement | INSEE | CSV, IRIS → agrégé par commune | Licence Ouverte 2.0 | Part de ménages sans voiture / multi-motorisés | `rp2021_logement_iris_csv.zip` |
| Projections de population 2018-2070 (Omphale 2022, scénario central) | INSEE | XLSX, département | Licence Ouverte 2.0 | Croissance démographique à l'horizon 2040 | `omphale_scenario_central.xlsx` |
| Arrêts de transport en France (agrégat national GTFS, non dédoublonné) | transport.data.gouv.fr / data.gouv.fr | CSV, points | Licence Ouverte 2.0 / ODbL selon jeux | Arrêts bus, tram, métro, train | `arrets_france.csv` |
| Catalogue des jeux du Point d'Accès National | transport.data.gouv.fr (API) | JSON | Licence Ouverte 2.0 | Métadonnées des jeux, URL GTFS Fluo 67 et des jeux hors agrégat | `pan_datasets.json` |
| GTFS des jeux publiés sur le PAN mais absents de l'agrégat national (Tango Nîmes, Orizo Avignon, CITALIS, CarSud, agrégat Nouvelle-Aquitaine, ZOU !…, hors scolaire / TAD / maritime) | AOM via transport.data.gouv.fr | GTFS (`stops.txt`) | Licence Ouverte / ODbL selon jeux | Arrêts bus, tram, train manquants | `gtfs_extra/*.zip`, `gtfs_extra/manifest.json` |
| Arrêts du réseau TCL (bus, tram, métro, funiculaire) | SYTRAL Mobilités via data.grandlyon.com (WFS public) | GeoJSON, points | Licence Ouverte (Grand Lyon) | Le GTFS TCL exige un compte (HTTP 401) et manque à l'agrégat : sans ce flux la Métropole de Lyon paraissait sans transport en commun | `tcl_arrets.geojson` |
| Catalogue mondial des flux GBFS (`systems.csv`) | MobilityData | CSV | CC-BY 4.0 / Apache 2.0 | Liste des systèmes de partage français | `gbfs_systems.csv` |
| Flux GBFS des systèmes français (station_information, vehicle_types) | opérateurs (Citiz, nextbike, Bird, Vélhop…) | JSON GBFS v1–v3 | Licence propre à chaque flux (LOM, open data) | Stations vélo, trottinettes, autopartage | `gbfs_france.json` |
| GBFS Citiz Grand Est | Citiz | GBFS v3.0 | open data LOM | Stations Citiz (étude de cas Strasbourg) | `gbfs_citiz_grandest_station_information.json` |
| GBFS Vélhop (Strasbourg) | nextbike / Eurométropole | GBFS v2 | open data LOM | Stations vélo Strasbourg | `gbfs_velhop_station_information.json` |
| GTFS CTS (tram et bus de Strasbourg) | Compagnie des Transports Strasbourgeois | GTFS | Licence Ouverte / ODbL | Contrôle de l'offre, types de lignes (tram/bus) | `gtfs_cts.zip` |
| GTFS Fluo Grand Est 67 (cars interurbains Bas-Rhin) | Région Grand Est | GTFS | Licence Ouverte | Offre interurbaine autour de Strasbourg | `gtfs_fluo67.zip` |
| Communes (nom, code, centre, population, surface) | geo.api.gouv.fr (IGN Admin Express / INSEE) | JSON | Licence Ouverte 2.0 | Noms de communes, agrégations | `communes.json` |
| Intercommunalités (EPCI) et rattachement des communes | geo.api.gouv.fr (IGN Admin Express / BANATIC) | JSON | Licence Ouverte 2.0 | Classement national des territoires pour Citiz (`src/territories.py`) | `epcis.json`, `communes_epci.json` |
| Réseau piéton OpenStreetMap (Eurométropole de Strasbourg) | contributeurs OpenStreetMap via Overpass API | JSON | ODbL 1.0 | Calibration du coefficient de détour marche | `osm_walk_strasbourg.json` |
| GTFS Lignes d'Azur (réseau urbain de la Métropole Nice Côte d'Azur) | Métropole Nice Côte d'Azur, via transport.data.gouv.fr | GTFS (valide du 19/10 au 31/12/2026) | Licence Ouverte / ODbL | Fréquence des lignes dans le territoire prioritaire (`src/frequency.py`) | `gtfs_lignes_azur.zip` |
| Usage des stations Citiz : relevés `vehicle_status` toutes les 5 min | Citiz (GBFS 3.0, backend.citiz.fr, 17 réseaux), collecte de l'équipe | CSV, totaux par station | open data LOM | Taux d'occupation, validation du modèle par l'usage (`src/collect_gbfs.py`, `src/usage.py`) | `data/gbfs/citiz_status_*.csv` |

## Hypothèses chiffrées (non issues de jeux de données)

| Paramètre | Valeur | Source |
|---|---|---|
| Vitesse de marche | 4,8 km/h → 400 m en 5 min | Cerema, littérature piétonne (4,5–5 km/h) |
| Facteurs d'émission | voiture 218 gCO2e/km, bus 113 gCO2e/passager.km, VAE 11 gCO2e/km | ADEME – impactco2.fr (Base Empreinte) |
| Effet de l'autopartage | 1 voiture partagée remplace 5 à 8 voitures personnelles | ADEME / 6t, Enquête nationale sur l'autopartage (2022) |
| Taille du réseau Citiz | ~2 800 véhicules, ~280 villes, ~130 000 conducteurs | Énoncé du hackathon |
| Coûts d'investissement / exploitation | voir `Config.COSTS` | Ordres de grandeur publics, **hypothèses paramétrables** |
| Seuil de secret statistique | 11 ménages | INSEE (règles de diffusion Filosofi) |
| Option TC « pleine » | une ligne (dans un sens) toutes les 15 min ou mieux, 7 h-20 h, mardi 17/11/2026 | `Config.FULL_OPTION_DEP_H`, `Config.FREQ_REF_DATE`, seuil courant d'un « réseau fréquent » ; jour hors vacances de la Toussaint (17 oct.-2 nov. 2026, [Onisep](https://www.onisep.fr/vacances-scolaires-2026-2027)) |
| Station Citiz saturée | voitures réservées plus de 60 % du temps relevé | `Config.SATURATION_OCCUPANCY`, **hypothèse** |
| Budgets par financeur | Citiz 1 M€, collectivité 1 M€ sur 5 ans | `Config.CITIZ_BUDGET`, `Config.PUBLIC_BUDGET`, **hypothèses paramétrables** |
| Seuil de taille des territoires classés | 100 000 habitants par intercommunalité | `Config.TERRITORY_MIN_POP`, hypothèse de masse critique |

## Risque terrain des territoires (veille presse, octobre 2026 ; `Config.TERRITORY_RISK`)

| Territoire | Constat | Source |
|---|---|---|
| Nice | Auto Bleue : 68 stations, 2011-2018, DSP d'environ 1,4 M€/an, recettes déficitaires, fermé le 31/12/2018 | [Wikipédia – Auto Bleue](https://fr.wikipedia.org/wiki/Auto_Bleue), [France 3](https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-maritimes/nice/quel-bilan-auto-bleue-service-auto-partage-metropole-nice-7-ans-apres-1497199.html), [journalauto.com](https://journalauto.com/journal-des-flottes/nice-se-met-a-lauto-partage-100-ve/) |
| Nice | Mobilize Share (Renault) arrêté fin juin 2026, Renault sort de l'autopartage ; Getaround reste (environ 200 véhicules entre particuliers) | [electrive.com](https://www.electrive.com/2026/08/04/nice-opens-former-mobilize-share-charging-network-to-public/), [Auto Infos](https://www.auto-infos.fr/article/la-mobilite-et-l-autopartage-ne-font-pas-recette-la-marque-mobilize-de-renault-group-tire-sa-reverence.289947), [tesla-mag.com](https://www.tesla-mag.com/getaround-et-la-metropole-nice-cote-dazur-renforcent-leur-partenariat-pour-lautopartage-electrique/) |
| Lyon | Bluely fermé en 2020, Zity parti en 2024 ; Citiz LPA en boucle se développe avec la Métropole | [LyonMag](https://www.lyonmag.com/article/135876/autopartage-a-lyon-zity-c-est-fini), [Lyon Capitale](https://www.lyoncapitale.fr/actualite/a-lyon-le-boost-de-lautopartage-passera-par-le-developpement-de-citiz) |
| Montpellier | Modulauto (+ Communauto) : environ 100 stations en Occitanie, plus subventionné par la Métropole | [Communauto](https://communauto.com/modulauto-communauto-accelere-developpement-autopartage), [tesla-mag.com](https://www.tesla-mag.com/a-montpellier-le-choc-des-mobilites-cest-maintenant/), [Le Journal des entreprises](https://www.lejournaldesentreprises.com/article/modulauto-se-structure-pour-developper-lautopartage-2097370) |
| Toulouse | Citiz Occitanie retenu par la Métropole pour 2025-2030 (stations sur voirie) | [Toulouse Métropole](https://metropole.toulouse.fr/mon-quotidien/deplacements-stationnement/se-deplacer/se-deplacer-en-voiture) |
| Bordeaux | BlueCub (Bolloré) fermé en 2020 ; Citiz (ex-Autocool) maintenu | [Caradisiac](https://www.caradisiac.com/autopartage-fin-des-bluecar-de-bollore-a-bordeaux-et-lyon-le-31-aout-184737.htm) |
| Toulon | Aucun service public ; étude de faisabilité de l'association Var Autopartage sans suite | [tout-toulon.org](http://www.tout-toulon.org/var-auto-partage-1876.html) |
| Rouen | Projet Rouen Autopartage suspendu (2013) ; Normandy Mobility ; enquête métropolitaine 2024 | [blog Rouen Autopartage](http://rouenautopartage.blogspot.com/), [Normandy Mobility](https://normandymobility.com/qui-sommes-nous/), [Métropole Rouen Normandie](https://jeparticipe.metropole-rouen-normandie.fr/concertation-publique/et-vous-seriez-vous-pret-pour-lautopartage) |
| Clermont-Ferrand | Prêt entre particuliers (2017-2020), étude de potentiel 2021-2022 sans lancement | [SMTC – bilan PDU 2022](https://www.smtc-clermont-agglo.fr/wp-content/uploads/2023/07/PDU-Point-Etapes-2022-Action3-3.pdf) |
| Grenoble | Expérimentation Cité Lib by Ha:mo (Toyota, à partir de 2014) | [automobile-propre.com](https://www.automobile-propre.com/breves/autopartage-electrique-bilan-cite-lib-hamo-grenoble/) |
| Orléans, Tours | Orléans sans autopartage pendant 6 ans avant le retour de Citiz (2025) ; Citiz ouvre des stations à Tours | [Citiz – communiqué RNTP 2025](https://citiz.coop/media/7509/reference/2025-11-cp-salon-rntp.pdf) |
| Marseille | Totem Mobi (Twizy en free-floating), partenaire de Citiz | [Made in Marseille](https://madeinmarseille.net/actualite/47955-totem-mobi-deploie-lautopartage-comme-alternative-a-la-voiture-individuelle/) |

Les pondérations (`Config.TERRITORY_RISK_WEIGHTS`) sont des hypothèses. Cannes, Le Havre et Caen : aucun service public relevé, ou seulement Normandy Mobility (Caen).

## Contexte terrain (vérification qualitative)

| Information | Source |
|---|---|
| Fin du service Mobilize Share (Renault) dans la métropole niçoise fin juin 2026 ; les 86 bornes réservées reprises par la Métropole | [automobile-propre.com](https://www.automobile-propre.com/articles/nice-bornes-recharge-ex-mobilize-share-reseau-public/) |
| Vélo Bleu (Nice) : stations publiées en 2014 sur data.gouv.fr, pas de flux GBFS | [data.gouv.fr – Cartographie des stations Vélobleu](https://www.data.gouv.fr/datasets/cartographie-des-stations-velobleu) |
