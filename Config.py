"""
Configuration centrale du projet « Mobili'Score » – Hackathon Mobility (Epitech x Citiz x Microsoft).

Tous les paramètres méthodologiques (vitesse de marche, coûts, facteurs CO2, budget…)
sont regroupés ici pour être discutables et modifiables sans toucher au code.
Chaque hypothèse chiffrée est accompagnée de sa source ou signalée comme hypothèse.
"""
import sys
from pathlib import Path

# Console Windows (cp1252) : sans cela, afficher « λ », « ≥ » ou « → » fait planter les scripts.
# Tous les fichiers texte du projet sont par ailleurs lus et écrits en UTF-8 explicitement.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# --------------------------------------------------------------------------- chemins
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"            # téléchargements bruts (jamais modifiés)
INTERIM = DATA / "interim"    # fichiers nettoyés intermédiaires (parquet)
OUT = ROOT / "outputs"        # résultats finaux (parquet, csv, figures, métriques)
FIG = OUT / "figures"
for _p in (RAW, INTERIM, OUT, FIG):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- sources
URLS = {
    # INSEE – Filosofi 2021, carreaux 200 m (métropole, Martinique, La Réunion)
    "filosofi": "https://www.insee.fr/fr/statistiques/fichier/8735162/Filosofi2021_carreaux_200m_csv.zip",
    # INSEE – Recensement 2021, base infracommunale Logement (motorisation des ménages)
    "rp_logement": "https://www.insee.fr/fr/statistiques/fichier/8268838/base-ic-logement-2021_csv.zip",
    # INSEE – Omphale, projections départementales 2018-2070 (scénario central)
    "omphale": "https://www.insee.fr/fr/statistiques/fichier/6652134/projections_scenario_central.xlsx",
    # data.gouv.fr – Arrêts de transport en France (agrégat national GTFS, non dédoublonné)
    "stops_fr": "https://www.data.gouv.fr/api/1/datasets/r/69cf54c6-6591-4920-b1d6-2a5292964606",
    # MobilityData – catalogue mondial des flux GBFS
    "gbfs_catalog": "https://raw.githubusercontent.com/MobilityData/gbfs/master/systems.csv",
    # transport.data.gouv.fr – API catalogue (métadonnées, validité des jeux)
    "pan_api": "https://transport.data.gouv.fr/api/datasets",
    # geo.api.gouv.fr (IGN Admin Express) – communes (nom, centre, population)
    "communes": "https://geo.api.gouv.fr/communes?fields=nom,code,codeDepartement,codeRegion,population,centre,surface&format=json",
    # geo.api.gouv.fr (IGN Admin Express / BANATIC) – intercommunalités (EPCI) et rattachement des communes
    "epcis": "https://geo.api.gouv.fr/epcis?fields=nom,code,population&format=json",
    "communes_epci": "https://geo.api.gouv.fr/communes?fields=code,codeEpci&format=json",
    # Étude de cas Strasbourg
    "gtfs_cts": "https://opendata.cts-strasbourg.eu/google_transit.zip",
    "gbfs_citiz_grandest": "https://backend.citiz.fr/public/provider/1/gbfs/v3.0/gbfs.json",
    "gbfs_velhop": "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_ae/gbfs.json",
    "overpass": "https://overpass-api.de/api/interpreter",
    # Nice Côte d'Azur (territoire prioritaire) – GTFS du réseau urbain Lignes d'Azur (PAN)
    "gtfs_lignes_azur": "https://chouette.enroute.mobi/api/v1/datas/OpendataRLA/gtfs.zip",
}
# Le GTFS Fluo 67 est résolu dynamiquement via l'API transport.data.gouv.fr
FLUO67_SLUG = "offre-de-transport-du-reseau-fluo-grand-est-bas-rhin-67"

# Emprise de l'étude de cas (Eurométropole de Strasbourg) – lon/lat
STRASBOURG_BBOX = (7.62, 48.47, 7.88, 48.66)   # (ouest, sud, est, nord)
STRASBOURG_DEPT = "67"
# Périmètre officiel de l'Eurométropole de Strasbourg (EPCI SIREN 246700488, 33 communes
# depuis 2017 ; liste BANATIC / INSEE), codes INSEE vérifiés dans data/raw/communes.json.
# Utilisé par src/recommend.py (zone "ems") à la place de la boîte englobante, qui incluait
# 7 communes hors EMS (~9 300 hab.) et en tronquait 9 (~16 000 hab., dont Vendenheim).
EMS_EPCI = "246700488"
EMS_COMMUNES = (
    "67001", "67043", "67049", "67065", "67118", "67119", "67124", "67131", "67137", "67152",
    "67182", "67204", "67212", "67218", "67247", "67256", "67267", "67268", "67296", "67309",
    "67326", "67343", "67350", "67363", "67365", "67378", "67389", "67447", "67471", "67482",
    "67506", "67519", "67551",
)   # Achenheim … Strasbourg, Vendenheim, La Wantzenau, Wolfisheim

# --------------------------------------------------------------------------- marche à pied
WALK_SPEED_KMH = 4.8          # vitesse piétonne usuelle (Cerema / littérature, 4,5-5 km/h)
WALK_MINUTES = 5
WALK_NETWORK_M = WALK_SPEED_KMH * 1000 / 60 * WALK_MINUTES   # = 400 m sur le réseau
# Coefficient de détour réseau / vol d'oiseau. Valeur par défaut remplacée par la
# calibration OSM (src/walk_calibration.py -> outputs/walk_calibration.json).
DEFAULT_DETOUR = 1.30

CELL = 200                    # taille des carreaux INSEE (m)

# --------------------------------------------------------------------------- typologie de l'offre
# Les catégories ci-dessous sont les "options de transport" comptées.
MODES = {
    "rail": "Train / RER",
    "transit": "Bus / Tram / Métro",
    "bike": "Vélo en libre-service",
    "scooter": "Free-floating (trottinette / vélo)",
    "carsharing": "Autopartage (hors Citiz)",
    "citiz": "Autopartage Citiz",
}
# Poids d'une option dans l'indice d'accessibilité (1 = toutes égales, choix par défaut
# conforme à l'énoncé « nombre d'options »). Modifiable pour une variante pondérée.
MODE_WEIGHT = {m: 1.0 for m in MODES}

# --------------------------------------------------------------------------- coûts (EUR)
# Coût total sur HORIZON_YEARS = investissement + exploitation annuelle * années.
# Ordres de grandeur issus de retours d'expérience publics ; ce sont des HYPOTHÈSES
# paramétrables, à faire valider par l'opérateur.
HORIZON_YEARS = 5
COSTS = {
    # Station Citiz 1 véhicule : véhicule citadine (~20 k€ amorti), télématique, marquage,
    # convention de stationnement ; exploitation : assurance, entretien, nettoyage, place.
    "citiz": {"capex": 25_000, "opex": 7_000, "label": "Station Citiz (1 véhicule)"},
    # Station vélo légère (type nextbike/Vélhop, 10 vélos) : borne + vélos + pose.
    # 60 k€ / 5 ans / 10 vélos = 1 200 €/vélo/an : bas de la fourchette Cerema 2005-2013
    # (1 100 à 3 200 € HT/vélo/an, investissement + fonctionnement) -> hypothèse basse.
    "bike": {"capex": 30_000, "opex": 6_000, "label": "Station vélo libre-service (10 vélos)"},
    # Arrêt de bus sur ligne existante : quai PMR + abri + signalétique.
    # + coût d'exploitation du détour, calculé selon la distance à l'arrêt existant.
    "bus": {"capex": 35_000, "opex": 2_000, "label": "Arrêt de bus (quai PMR + abri)"},
}
BUS_DETOUR = {
    "trips_per_day": 30,       # passages/jour sur la ligne déviée (hypothèse)
    "cost_per_km": 5.0,        # coût d'exploitation bus €/km (ordre de grandeur réseaux urbains)
    "max_dist_m": 1500,        # au-delà, ce n'est plus un arrêt mais une nouvelle ligne
}

def facility_cost(kind: str, extra_annual: float = 0.0) -> float:
    c = COSTS[kind]
    return c["capex"] + (c["opex"] + extra_annual) * HORIZON_YEARS

# --------------------------------------------------------------------------- impact / CO2
# impactco2.fr (ADEME, Base Empreinte) : voiture thermique 218 gCO2e/km,
# bus thermique 113 gCO2e/passager.km, vélo mécanique ~0, VAE 11 gCO2e/km.
CO2_G_PER_KM = {"car": 218, "bus": 113, "bike": 0, "ebike": 11}
# Autopartage : enquête nationale ADEME / 6t (2022) – une voiture partagée remplace
# 5 à 8 voitures personnelles ; les usagers réduisent fortement leurs km en voiture.
CARSHARING_CAR_KM_AVOIDED_PER_USER = 1_500   # km/an évités par usager actif (hypothèse prudente)
CITIZ_DRIVERS_FR = 130_000                   # énoncé du hackathon
CITIZ_CARS_FR = 2_800                        # énoncé du hackathon
BIKE_TRIPS_PER_STATION_DAY = 15              # hypothèse (station légère, ville moyenne)
BIKE_KM_PER_TRIP = 2.5
BIKE_CAR_SHIFT = 0.15                        # part des trajets vélo qui remplacent la voiture
BUS_CAR_SHIFT = 0.20
# Émission marginale d'un passager supplémentaire sur une ligne EXISTANTE : ~0 (le bus roule
# de toute façon). Les 113 g/passager.km d'impactco2 sont une moyenne qui inclut la marche du
# véhicule ; or le surplus de km-véhicule du détour est déjà compté explicitement
# (BUS_KGCO2_PER_VKM) -> les soustraire aussi serait un double comptage.
BUS_PASSENGER_MARGINAL_G_PER_KM = 0.0
# Vélo : la fréquentation d'une station croît avec son bassin. Trajets/jour =
# BIKE_TRIPS_PER_STATION_DAY × v × min(1, pop nouvellement desservie / BIKE_REF_POP), où
# BIKE_REF_POP = population médiane à 5 min des stations vélo existantes en France
# (outputs/stations_served.parquet, recalculée à l'exécution ; valeur de repli ci-dessous).
BIKE_REF_POP = 1_640

# --------------------------------------------------------------------------- optimisation
DEFAULT_BUDGET = 2_000_000    # € sur l'horizon
EQUITY_LAMBDA = 0.5           # 0 = efficacité pure, 1 = forte priorité aux ménages modestes / peu desservis
GROWTH_HORIZON = 2040         # année des projections Omphale utilisée
PRIVACY_MIN_HOUSEHOLDS = 11   # seuil de secret statistique INSEE : pas d'affichage individuel en dessous

RANDOM_STATE = 42

# ---- walk_calibration.py / accessibility.py
# Calibration du détour piéton sur le graphe OSM de l'Eurométropole de Strasbourg.
CALIB_N_ORIGINS = 400          # origines tirées (pondérées par la population des carreaux)
CALIB_DIST_BAND = (200, 600)   # bande de distances à vol d'oiseau retenue pour les ratios (m)
CALIB_SNAP_MAX_M = 60          # distance max carreau/arrêt -> nœud du graphe pour être retenu (m)
CALIB_DIJKSTRA_LIMIT_M = 1200  # borne du Dijkstra (m de réseau)
CALIB_BOOTSTRAP = 2000         # tirages bootstrap (rééchantillonnage par origine)
# Score 0-100 : rang-percentile national (pondéré population) parmi les carreaux desservis ;
# 0 réservé aux carreaux sans aucune option à 5 min. SCORE_BASIS choisit la grandeur classée :
# "n_options" (options accessibles depuis le domicile de chaque habitant) ou "access_2sfca"
# (offre par habitant corrigée de la concurrence, Luo & Wang 2003). Les deux sont exportées
# (score_options, score_2sfca) ; cf. docstring de src/accessibility.py pour le choix.
SCORE_BASIS = "n_options"
SCORE_MIN_SERVED = 1.0         # score plancher d'un carreau desservi (le distingue du 0)
# Free-floating (mode scooter) : les « stations » GBFS sont des zones de stationnement
# virtuelles (Paris : ~31 zones à 5 min d'un habitant moyen, 78 % de son n_options). Une
# option = un service utilisable : on compte les OPÉRATEURS free-floating distincts à 5 min,
# pas leurs zones (False = ancien comptage par zone). N'affecte pas offer.parquet.
FREEFLOAT_COUNT_BY_OPERATOR = True
# pop_catchment : part de la surface de chaque carreau voisin à ≤ r du centre (sous-grille
# CATCHMENT_SUBGRID² points, population supposée uniforme dans le carreau). Évite l'effet de
# seuil de la grille (diagonale 282,8 m ≈ r : 5 ou 9 carreaux entiers selon r à 1 m près).
CATCHMENT_SUBGRID = 32

# ---- model.py / recommend.py
# Modèle de « valeur d'un site » (src/model.py) : un modèle par type d'équipement.
MODEL_KINDS = ("citiz", "bike", "bus")
# Modes d'offre qui constituent la cible (= « déjà desservi ») de chaque type.
# Ces modes sont EXCLUS des variables explicatives du modèle correspondant (anti-fuite).
KIND_TARGET_MODES = {
    "citiz": ("citiz", "carsharing"),
    "bike": ("bike",),
    "bus": ("transit", "rail"),
}
# Modes retirés des variables explicatives (cible + modes trop liés : flottes GBFS mixtes
# vélo/trottinette ; les gares restent un contexte légitime pour le bus mais sont la cible).
# Free-floating (scooter) exclu partout : sa présence dans les flux GBFS publics est un
# indicateur de contrat municipal tout-ou-rien par ville (Lyon, Bordeaux, Marseille : oui ;
# Strasbourg, Nantes, Lille, Toulouse : 0 point), donc un effet « département » et un
# décalage de distribution vers la zone d'application (EMS : 0 point, d_scooter = 20 km
# partout). Mesuré en CV spatiale : Citiz PR-AUC 0,456 -> 0,478, bus inchangé (0,707 -> 0,709).
KIND_EXCLUDED_FEATURE_MODES = {
    "citiz": ("citiz", "carsharing", "scooter"),
    "bike": ("bike", "scooter"),
    "bus": ("transit", "rail", "scooter"),
}
MODEL_CONTEXT_HALF_M = (1000, 3000)   # demi-côtés (m) des fenêtres de contexte (carrés)
MODEL_CV_FOLDS = 5                    # GroupKFold spatial (groupe = département)
MODEL_MAX_TRAIN = 250_000             # sous-échantillon aléatoire max pour la CV
MODEL_HGB = dict(max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
                 min_samples_leaf=200, l2_regularization=1.0)
MODEL_PERM_SAMPLE = 30_000            # lignes (par pli) pour l'importance par permutation
MODEL_PERM_REPEATS = 3                # répétitions par variable et par pli
# Variables quasi colinéaires (r = 0,99 entre habitants et ménages à 5 min) : leur
# importance est aussi mesurée en les permutant ENSEMBLE (sinon l'une « vole » l'autre).
MODEL_PERM_GROUPS = {"population_5min (pop_r5+men_r5)": ("pop_r5", "men_r5")}
MODEL_FINAL_MAX_TRAIN = 500_000       # sous-échantillon max du modèle final (et de ses plis)

# Recommandation (src/recommend.py)
# Besoin d'un carreau ∈ [0,1] = moyenne pondérée de rangs-percentiles (dans la zone) :
NEED_WEIGHTS = {"poverty_rate": 0.4, "carfree_share": 0.2, "low_access": 0.4}
# Valeur relative d'un site = p_site / p_ref (p_ref = propension médiane des carreaux
# déjà desservis par ce type) bornée : 1 ≈ « aussi bon qu'un site existant typique ».
# Borne haute : 1,5 maintenue. Testé à 3,0 avec p_ref hors pli : la saturation des sites
# retenus tombe de 48 % à 0 % (EMS) et de 63 % à 7 % (dép. 54), mais les indicateurs
# indépendants du modèle se dégradent (sorties de « 0 option » −22 % EMS / −34 % dép. 54,
# part en déciles 1-3 −2 pts) ; seul le CO2, lui-même proportionnel à v, progresse.
VALUE_CLIP = (0.05, 1.5)
# Le multiplicateur d'USAGE (adhérents, trajets, montées -> CO2) est borné à 1,5 même si
# VALUE_CLIP est relevé : au-delà,
# les taux d'usage deviennent invraisemblables (ex. 0,45 montée/hab./jour pour un arrêt).
USAGE_VALUE_CAP = 1.5
# Bénéfice relatif d'un habitant nouvellement desservi, par type (1 = tous égaux).
KIND_BENEFIT = {"citiz": 1.0, "bike": 1.0, "bus": 1.0}
LOW_DENSITY_HAB_KM2 = 1500            # seuil « dense » INSEE (grille communale de densité)
NAIVE_LABEL = "population seule (sans modèle, sans offre existante, λ=0)"
# CO2 – autopartage : adhérents potentiels = pop. nouvellement desservie × pénétration
# nationale (CITIZ_DRIVERS_FR / pop. résidant à 5 min d'une station, calculée), bornée
# par la capacité d'1 véhicule (CITIZ_DRIVERS_FR / CITIZ_CARS_FR ≈ 46 adhérents).
CARSHARING_ACTIVE_SHARE = 0.5         # part d'adhérents réellement actifs (hypothèse prudente)
# CO2 – bus : déplacements/jour générés par habitant nouvellement desservi (hypothèse)
BUS_TRIPS_PER_RESIDENT_DAY = 0.15
BUS_KM_PER_TRIP = 4.0
BUS_KGCO2_PER_VKM = 1.1               # bus diesel standard ~1,1 kgCO2e/km-véhicule (ADEME)

# ---- offer.py
# Dédoublonnage des points d'offre : deux points du même mode à moins de ce rayon
# (quais de part et d'autre de la rue, même arrêt publié par plusieurs jeux GTFS)
# sont fusionnés en un seul point (centroïde). Hypothèse : ~50 m = largeur d'un carrefour.
DEDUP_RADIUS_M = 50
# Gares : les quais TER / TGV / Transilien d'une même gare sont publiés à des positions
# distinctes (jusqu'à ~150 m d'écart dans les grandes gares) -> rayon plus large.
DEDUP_RADIUS_RAIL_M = 150
# Free-floating (mode scooter) : zones de stationnement virtuelles très denses (Paris :
# ~1 tous les 50 m) et partagées entre opérateurs (Voi / Dott à quelques cm près) -> on ne
# fusionne que les quasi-doublons, sinon le chaînage agrège des quartiers entiers.
DEDUP_RADIUS_FREEFLOAT_M = 15
# Emprises lon/lat (ouest, sud, est, nord) considérées comme « France » ; hors de ces
# boîtes un point est écarté (coordonnées aberrantes, gares étrangères Eurostar/Flix…).
FRANCE_BBOXES = [
    (-5.5, 41.2, 10.0, 51.3),      # métropole + Corse (inclut quelques gares frontalières)
    (-61.9, 15.8, -60.9, 16.6),    # Guadeloupe
    (-61.3, 14.3, -60.7, 14.95),   # Martinique
    (-54.7, 2.0, -51.5, 6.0),      # Guyane
    (55.1, -21.5, 55.9, -20.8),    # La Réunion
    (44.9, -13.1, 45.4, -12.5),    # Mayotte
]
# Amplitude de la pondération d'équité : w = pop × (1 + EQUITY_SCALE·λ·besoin). Avec λ = 0,5,
# un carreau au besoin maximal pèse 3× un carreau au besoin nul (λ = 1 -> 5×).
EQUITY_SCALE = 4.0
# Enveloppes budgétaires par type (parts du budget). Sans enveloppes (None), l'optimiseur
# arbitre librement et, à Strasbourg, met presque tout sur le vélo (le moins cher par
# habitant desservi) ; les financeurs étant distincts (Citiz, réseau de bus, vélo), on
# réserve par défaut une part à chacun. Les parts non utilisables sont réallouées.
BUDGET_SPLIT = {"citiz": 0.4, "bike": 0.3, "bus": 0.3}
# Quota de budget réservé aux candidats en zone peu dense (< LOW_DENSITY_HAB_KM2) : sans
# lui, la couverture maximale ne sert que les zones denses (cf. recommendations_summary.json).
LOW_DENSITY_BUDGET_SHARE = 0.15
# Couverture en recommandation (src/recommend.py) : chaque carreau de 200 m est représenté par
# COVER_SUBSAMPLE² points (population répartie uniformément). Sans cela, candidats et carreaux
# étant tous deux des centres de grille, un site couvre exactement 5 carreaux tant que le rayon
# (282 m) reste sous la diagonale (282,8 m) et 9 au-delà : +42 % de « nouveaux desservis » pour
# +1,5 m de rayon. Avec 4×4 points, la couverture varie continûment avec le rayon.
COVER_SUBSAMPLE = 4
# Usage du modèle dans l'objectif : v_j = clip(p_j/p_ref, VALUE_CLIP) ** MODEL_VALUE_EXPONENT,
# et les candidats dont clip(p/p_ref) < MODEL_VALUE_MIN sont écartés (filtre « site
# invraisemblable »). Exposant 1 = facteur fort (historique), 0 = population seule.
# Choix 0,5 sans filtre (multiplicateur doux), évalué avec les prédictions HORS PLI : sur l'EMS
# et la Meurthe-et-Moselle, il domine l'exposant 1 sur les indicateurs indépendants du modèle
# (personnes distinctes nouvellement desservies, sorties de « 0 option », part en déciles 1-3) ;
# v = 1 (sans modèle) maximise la somme par type mais empile vélo et Citiz sur les mêmes
# carreaux denses (−10 % à −18 % de personnes distinctes). Un filtre 0,3 coûte ~3 000 personnes
# distinctes sur l'EMS sans gain mesurable : désactivé (0), paramètre conservé.
MODEL_VALUE_EXPONENT = 0.5
MODEL_VALUE_MIN = 0.0

# ---- territories.py / recommend.py : quel territoire, quel financeur
# Citiz n'exploite que des stations d'autopartage : son budget est distinct de celui de la
# collectivité (AOM), qui finance stations vélo et arrêts de bus. Montants sur HORIZON_YEARS.
CITIZ_BUDGET = 1_000_000      # ≈ 16 stations d'1 véhicule (60 k€ / 5 ans chacune)

# ---- frequency.py : fréquence des lignes de bus / tram / métro dans les zones d'étude (GTFS)
# L'agrégat national d'arrêts n'a pas d'horaires : un arrêt à 2 bus/jour y vaut une station de
# métro. Dans les zones où l'on recommande, on lit les GTFS des réseaux pour pondérer par le service.
# Zone (nom de recommend._area_bounds) -> fichiers GTFS de data/raw/ (téléchargés par src.download).
FREQ_FEEDS = {
    "ems": ("gtfs_cts.zip", "gtfs_fluo67.zip"),            # CTS (bus, tram) + cars Fluo 67
    "epci200030195": ("gtfs_lignes_azur.zip",),             # Métropole Nice Côte d'Azur : Lignes d'Azur
}
FREQ_REF_DATE = "20261117"     # mardi hors vacances scolaires ; à défaut, le mardi le plus chargé du GTFS
FREQ_HOURS = (7, 20)           # fréquence moyenne entre 7 h et 20 h
# Une ligne (dans un sens) passant toutes les 15 min ou mieux = 1 option pleine ; moins = fraction.
FULL_OPTION_DEP_H = 4.0
# Arrêt de bus recommandé : sa valeur est multipliée par la qualité de service de la ligne
# rattachée (min(1, départs/h / FULL_OPTION_DEP_H)), bornée en bas pour ne pas annuler un site.
FREQ_MIN_FACTOR = 0.1

# ---- collect_gbfs.py / usage.py : usage réel des stations Citiz (collecte GBFS toutes les 5 min)
# Sortie du collecteur (totaux par station, aucune position de véhicule). Variable d'environnement
# GBFS_COLLECT_DIR pour lire une collecte faite ailleurs (autre PC, autre dossier).
GBFS_COLLECT = Path(__import__("os").environ.get("GBFS_COLLECT_DIR", DATA / "gbfs"))
GBFS_COLLECT_INTERVAL_S = 300  # = TTL des flux Citiz
USAGE_MIN_SNAPSHOTS = 12       # station retenue pour la validation si au moins 12 relevés (1 h)
SATURATION_OCCUPANCY = 0.6     # « station saturée » : véhicules réservés plus de 60 % du temps relevé
PUBLIC_BUDGET = 1_000_000     # vélo + bus, réparti selon BUDGET_SPLIT (50/50 entre ces deux types)
# Classement national des intercommunalités (src/territories.py)
TERRITORY_MIN_POP = 100_000   # masse critique d'un réseau local d'autopartage (hypothèse)
# Île-de-France exclue : son autopartage (Getaround, Zity, Communauto, Free2Move) est presque
# absent des flux GBFS publics -> couverture apparente ~1 %, potentiel surestimé.
TERRITORY_EXCLUDED_DEPS = ("75", "77", "78", "91", "92", "93", "94", "95")
TERRITORY_SHORTLIST = 10      # EPCI du criblage simulées avec l'optimiseur (budget CITIZ_BUDGET)
