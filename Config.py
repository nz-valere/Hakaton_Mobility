"""
Configuration centrale du projet « Mobili'Score » – Hackathon Mobility (Epitech x Citiz x Microsoft).

Tous les paramètres méthodologiques (vitesse de marche, coûts, facteurs CO2, budget…)
sont regroupés ici pour être discutables et modifiables sans toucher au code.
Chaque hypothèse chiffrée est accompagnée de sa source ou signalée comme hypothèse.
"""
from pathlib import Path

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
    # Étude de cas Strasbourg
    "gtfs_cts": "https://opendata.cts-strasbourg.eu/google_transit.zip",
    "gbfs_citiz_grandest": "https://backend.citiz.fr/public/provider/1/gbfs/v3.0/gbfs.json",
    "gbfs_velhop": "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_ae/gbfs.json",
    "overpass": "https://overpass-api.de/api/interpreter",
}
# Le GTFS Fluo 67 est résolu dynamiquement via l'API transport.data.gouv.fr
FLUO67_SLUG = "offre-de-transport-du-reseau-fluo-grand-est-bas-rhin-67"

# Emprise de l'étude de cas (Eurométropole de Strasbourg) – lon/lat
STRASBOURG_BBOX = (7.62, 48.47, 7.88, 48.66)   # (ouest, sud, est, nord)
STRASBOURG_DEPT = "67"

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
# paramétrables, discutées dans DEMARCHE.md (section Coûts).
HORIZON_YEARS = 5
COSTS = {
    # Station Citiz 1 véhicule : véhicule citadine (~20 k€ amorti), télématique, marquage,
    # convention de stationnement ; exploitation : assurance, entretien, nettoyage, place.
    "citiz": {"capex": 25_000, "opex": 7_000, "label": "Station Citiz (1 véhicule)"},
    # Station vélo légère (type nextbike/Vélhop, 10 vélos) : borne + vélos + pose.
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
KIND_EXCLUDED_FEATURE_MODES = {
    "citiz": ("citiz", "carsharing"),
    "bike": ("bike", "scooter"),
    "bus": ("transit", "rail"),
}
MODEL_CONTEXT_HALF_M = (1000, 3000)   # demi-côtés (m) des fenêtres de contexte (carrés)
MODEL_CV_FOLDS = 5                    # GroupKFold spatial (groupe = département)
MODEL_MAX_TRAIN = 250_000             # sous-échantillon aléatoire max pour la CV
MODEL_HGB = dict(max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
                 min_samples_leaf=200, l2_regularization=1.0)
MODEL_PERM_SAMPLE = 30_000            # lignes pour l'importance par permutation

# Recommandation (src/recommend.py)
# Besoin d'un carreau ∈ [0,1] = moyenne pondérée de rangs-percentiles (dans la zone) :
NEED_WEIGHTS = {"poverty_rate": 0.4, "carfree_share": 0.2, "low_access": 0.4}
# Valeur relative d'un site = p_site / p_ref (p_ref = propension médiane des carreaux
# déjà desservis par ce type) bornée : 1 ≈ « aussi bon qu'un site existant typique ».
VALUE_CLIP = (0.05, 1.5)
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
