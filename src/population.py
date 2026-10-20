"""
Étape 2 – Population : carreaux INSEE 200 m (Filosofi 2021) + motorisation (RP 2021)
+ projections départementales (Omphale 2022).

Sortie : data/interim/cells.parquet, une ligne par carreau habité, avec
coordonnées projetées (centre du carreau), lon/lat, variables socio-démographiques,
taux de ménages sans voiture de la commune et facteur de croissance démographique.
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

# Codes CRS des carreaux INSEE : métropole (LAEA), Martinique (UTM 20N), La Réunion (UTM 40S)
CRS_ID = {3035: 0, 5490: 1, 2975: 2}
TERR = {0: "Métropole", 1: "Martinique", 2: "La Réunion"}

FILOSOFI_FILES = ["carreaux_200m_met.csv", "carreaux_200m_mart.csv", "carreaux_200m_reun.csv"]
NUM_COLS = ["ind", "men", "men_pauv", "men_1ind", "men_5ind", "men_prop", "men_fmp", "ind_snv",
            "men_surf", "men_coll", "men_mais", "log_soc", "ind_0_3", "ind_4_5", "ind_6_10",
            "ind_11_17", "ind_18_24", "ind_25_39", "ind_40_54", "ind_55_64", "ind_65_79", "ind_80p"]


def cell_key(crs_id, x, y):
    """Clé entière unique d'un carreau : (territoire, ligne, colonne) sur la grille 200 m."""
    return (np.asarray(crs_id, dtype=np.int64) * 10**12
            + (np.asarray(y, dtype=np.int64) // C.CELL) * 10**6
            + (np.asarray(x, dtype=np.int64) // C.CELL))


def to_lonlat(df):
    df["lon"] = np.nan
    df["lat"] = np.nan
    for epsg, cid in CRS_ID.items():
        m = df["crs_id"] == cid
        if m.any():
            t = Transformer.from_crs(epsg, 4326, always_xy=True)
            df.loc[m, "lon"], df.loc[m, "lat"] = t.transform(df.loc[m, "x"].values, df.loc[m, "y"].values)
    return df


def load_filosofi():
    zf = zipfile.ZipFile(C.RAW / "filosofi2021_200m_csv.zip")
    parts = []
    for name in FILOSOFI_FILES:
        df = pd.read_csv(zf.open(name), usecols=["idcar_200m", "i_est_200", "lcog_geo"] + NUM_COLS,
                         dtype={"lcog_geo": str})
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    # idcar : "CRS3035RES200mN2029400E4259000" -> CRS, Nord (y), Est (x) du coin sud-ouest
    ext = df["idcar_200m"].str.extract(r"CRS(\d+)RES200mN(\d+)E(\d+)").astype(np.int64)
    df["crs_id"] = ext[0].map(CRS_ID).astype(np.int8)
    df["x"] = ext[2] + C.CELL / 2          # centre du carreau
    df["y"] = ext[1] + C.CELL / 2
    df["key"] = cell_key(df["crs_id"], ext[2], ext[1])
    df["com"] = df["lcog_geo"].str[:5]     # un carreau à cheval -> 1re commune listée
    df["dep"] = np.where(df["com"].str.startswith("97"), df["com"].str[:3], df["com"].str[:2])
    df = df.drop(columns=["idcar_200m", "lcog_geo"])
    return to_lonlat(df)


def load_motorisation():
    """Part de ménages sans voiture par commune (RP 2021, agrégation des IRIS)."""
    zf = zipfile.ZipFile(C.RAW / "rp2021_logement_iris_csv.zip")
    rp = pd.read_csv(zf.open("base-ic-logement-2021.CSV"), sep=";",
                     usecols=["COM", "P21_RP", "P21_RP_VOIT1P", "P21_RP_VOIT2P"],
                     dtype={"COM": str}, decimal=".")
    g = rp.groupby("COM")[["P21_RP", "P21_RP_VOIT1P", "P21_RP_VOIT2P"]].sum()
    out = pd.DataFrame({
        "carfree_share": 1 - g["P21_RP_VOIT1P"] / g["P21_RP"],
        "multicar_share": g["P21_RP_VOIT2P"] / g["P21_RP"],
    }).clip(0, 1)
    # Paris, Lyon, Marseille : le RP est par arrondissement, Filosofi parfois par commune
    for city, prefix in (("75056", "751"), ("69123", "6938"), ("13055", "132")):
        sub = g[g.index.str.startswith(prefix)].sum()
        if sub["P21_RP"] > 0 and city not in out.index:
            out.loc[city] = [1 - sub["P21_RP_VOIT1P"] / sub["P21_RP"], sub["P21_RP_VOIT2P"] / sub["P21_RP"]]
    return out


def load_growth():
    """Facteur de croissance démographique 2021 -> horizon, par département (Omphale, scénario central)."""
    x = pd.read_excel(C.RAW / "omphale_scenario_central.xlsx", sheet_name="Population_DEP", header=5,
                      dtype={"DEP": str})
    x = x[x["DEP"].notna()]
    x["DEP"] = x["DEP"].str.strip()
    return (x[f"POP_{C.GROWTH_HORIZON}"] / x["POP_2021"]).rename("growth").set_axis(x["DEP"])


def build():
    print("Filosofi…")
    df = load_filosofi()
    print(f"  {len(df):,} carreaux habités, {df['ind'].sum() / 1e6:.2f} M habitants")
    mot = load_motorisation()
    df = df.join(mot, on="com")
    # communes absentes (fusions, codes historiques) -> moyenne départementale
    for c in ("carfree_share", "multicar_share"):
        df[c] = df[c].fillna(df.groupby("dep")[c].transform("mean")).fillna(df[c].mean())
    df = df.join(load_growth(), on="dep")
    df["growth"] = df["growth"].fillna(1.0)

    # variables dérivées (ratios par carreau)
    ind = df["ind"].clip(lower=1e-6)
    men = df["men"].clip(lower=1e-6)
    df["income_pc"] = df["ind_snv"] / ind                        # niveau de vie moyen (€/an)
    df["poverty_rate"] = (df["men_pauv"] / men).clip(0, 1)
    df["share_18_39"] = ((df["ind_18_24"] + df["ind_25_39"]) / ind).clip(0, 1)
    df["share_65p"] = ((df["ind_65_79"] + df["ind_80p"]) / ind).clip(0, 1)
    df["share_kids"] = ((df["ind_0_3"] + df["ind_4_5"] + df["ind_6_10"] + df["ind_11_17"]) / ind).clip(0, 1)
    df["share_1ind"] = (df["men_1ind"] / men).clip(0, 1)
    df["share_coll"] = (df["men_coll"] / men).clip(0, 1)
    df["share_soc"] = (df["log_soc"] / men).clip(0, 1)
    df["share_owner"] = (df["men_prop"] / men).clip(0, 1)
    df["surf_pc"] = df["men_surf"] / ind
    df["pop_future"] = df["ind"] * df["growth"]
    df["territory"] = df["crs_id"].map(TERR)
    out = C.INTERIM / "cells.parquet"
    df.to_parquet(out, index=False)
    print(f"  -> {out}")
    return df


if __name__ == "__main__":
    build()
