"""
Mobili'Score – démo live (Streamlit).  Lancement : python -m streamlit run app.py  (ou .venv/bin/python -m streamlit run app.py)
Onglets : carte d'accessibilité · qui est concerné · où s'implanter (France) · où investir (une liste
par financeur : Citiz / collectivité) · méthode & limites.
Toutes les données lourdes passent par src/app_data.py (cache, agrégation, confidentialité).
"""
import json
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import Config as C  # noqa: E402
from src import app_data as ad  # noqa: E402
from src import geo  # noqa: E402

st.set_page_config(page_title="Mobili'Score", page_icon="🚲", layout="wide")

BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
INK2 = "#52514e"
V = ad.versions()


def fmt(v, unit=""):
    return ad.fmt_int(v) + (f" {unit}" if unit else "")


def view_for(df, zoom=None):
    if df is None or len(df) == 0:
        return pdk.ViewState(longitude=2.4, latitude=46.6, zoom=5)
    lon, lat = float(df["lon"].median()), float(df["lat"].median())
    if zoom is None:
        span = max(df["lon"].quantile(.98) - df["lon"].quantile(.02),
                   (df["lat"].quantile(.98) - df["lat"].quantile(.02)) * 1.5, 1e-3)
        zoom = float(np.clip(np.log2(360 / span) - 0.6, 4.5, 13.5))
    return pdk.ViewState(longitude=lon, latitude=lat, zoom=zoom, pitch=0)


def square_layer(df, opacity=0.75, lid="cells", pickable=True):
    """Carrés (ColumnLayer à 4 côtés tourné de 45°) : léger, une position par carré."""
    return pdk.Layer("ColumnLayer", df, id=lid, get_position="[lon, lat]", get_elevation=0,
                     radius=float(df["radius"].iloc[0]) if len(df) else 100, disk_resolution=4,
                     angle=45, extruded=False, get_fill_color="[r, g, b]", opacity=opacity,
                     pickable=pickable, stroked=False)


def deck(layers, view, tooltip=True, height=600):
    tt = {"html": "{tip}", "style": {"fontSize": "13px", "backgroundColor": "#1a1a19",
                                     "color": "#f0efec", "maxWidth": "320px"}} if tooltip else None
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style=BASEMAP,
                             tooltip=tt), height=height, use_container_width=True)


SCORE_READING = ("Nombre d'options de transport accessibles à 5 min à pied depuis le domicile de chaque "
                 "habitant ; score = rang parmi les habitants desservis ; gris = aucune option.")
if getattr(C, "SCORE_BASIS", "n_options") != "n_options":
    SCORE_READING = ("Options à 5 min rapportées aux habitants qui les partagent (2SFCA) ; "
                     "score = rang parmi les habitants desservis ; gris = aucune option.")

EQUITY_OFF = "Sans pondération d'équité (λ = 0)"
EQUITY_OFF_HELP = ("λ = 0 retire seulement la pondération d'équité : chaque habitant non desservi pèse "
                   "selon sa population et la valeur du site (modèle). Ce n'est PAS « maximiser le nombre "
                   "d'habitants desservis » : avec les enveloppes par type, le quota peu dense et "
                   "l'optimisation gloutonne, λ = 0 peut desservir moins de monde qu'un λ positif.")
NO_MODEL = "Offre existante, sans modèle (v = 1)"
USAGE_HELP = ("Usage estimé à partir d'hypothèses explicites, pas une prédiction observée : habitants "
              "nouvellement desservis × taux d'usage de référence (constantes Config.py) × valeur relative "
              "du site, avec des plafonds (adhérents par véhicule Citiz, trajets par station vélo). "
              "Ordre de grandeur pour comparer les sites entre eux.")


def legend_score():
    st.markdown(
        f"""<div style="font-size:13px;color:{INK2};margin-top:4px">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="display:inline-block;width:16px;height:16px;background:rgb{ad.ZERO_COLOR};border-radius:3px"></span>
          Aucune option à 5 min (offre à développer)
        </div>
        <div style="margin-top:6px">Score d'accessibilité (0 → 100)</div>
        <div style="height:14px;border-radius:4px;background:{ad.ramp_css()}"></div>
        <div style="display:flex;justify-content:space-between"><span>froid · peu d'options à 5 min</span>
        <span>chaud · beaucoup d'options à 5 min</span></div>
        <div style="margin-top:4px">{SCORE_READING}</div></div>""",
        unsafe_allow_html=True)


def legend_modes(modes):
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:rgb{ad.MODE_COLOR[m]}"></span>'
        f'{C.MODES[m]}</span>' for m in modes)
    st.markdown(f'<div style="font-size:13px;color:{INK2}">{items}</div>', unsafe_allow_html=True)


def missing(what, cmd):
    st.info(f"**{what}** n'est pas encore disponible. Il sera affiché automatiquement dès que "
            f"`{cmd}` aura produit ses sorties (rechargez la page).")


FUNDER_TITLE = {"citiz": "Pour Citiz : stations d'autopartage",
                "collectivite": "Pour la collectivité / AOM : stations vélo et arrêts de bus"}
FUNDER_SHORT = {"citiz": "Citiz", "collectivite": "collectivité"}


def funder_block(key, rec, summ, off, bbox, lam, area):
    """KPIs, liste priorisée et comparaison des stratégies pour un financeur."""
    sel = summ.get("selected") or {}
    ref = ad.strategy(summ, "no_model")
    distinct = ad.field(sel, "distinct")
    zero1 = ad.field(sel, "zero_to_one")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Habitants nouvellement desservis", fmt(sel.get("pop_newly_served")),
              f"{fmt(distinct)} personnes distinctes" if distinct is not None and key != "citiz" else None,
              delta_color="off",
              help="Somme sur les types d'équipement : un habitant nouvellement desservi à la fois par une "
                   "station vélo et un arrêt de bus compte deux fois.")
    co2 = sel.get("co2_avoided_t_yr")
    k2.metric("CO₂ évité", f"{co2:.0f} t/an" if co2 is not None else "–")
    k3.metric("Coût (5 ans)", f"{sel.get('cost_eur', 0) / 1e6:.2f} M€", f"{sel.get('n_sites', len(rec))} sites",
              delta_color="off")
    epr = sel.get("eur_per_new_resident")
    k4.metric("Coût par habitant desservi", f"{epr:.0f} €" if epr is not None else "–")
    if key == "citiz":
        w, s_, e_, n_ = bbox
        existing = int(((off["mode"] == "citiz") & off["lon"].between(w, e_) & off["lat"].between(s_, n_)).sum())
        a, b, c = st.columns(3)
        a.metric("Stations Citiz existantes à proximité", existing)
        b.metric("Conducteurs (usage estimé, hypothèses)", fmt(rec["usage_pred"].sum()), help=USAGE_HELP)
        c.metric("Véhicules justifiés par la demande", fmt(rec["vehicles_suggested"].sum()),
                 f"{fmt(rec['demand_potential'].sum())} adhérents potentiels", delta_color="off")
        st.caption(f"Estimation sous hypothèses, pas une prédiction : adhérents = habitants nouvellement desservis × "
                   f"taux d'adhésion national Citiz observé autour des stations existantes × valeur du site ; "
                   f"conducteurs plafonnés à {C.CITIZ_DRIVERS_FR / C.CITIZ_CARS_FR:.0f} par véhicule "
                   f"({C.CITIZ_DRIVERS_FR:,} conducteurs / {C.CITIZ_CARS_FR:,} voitures).".replace(",", " "))
        u = ad.citiz_usage(V)
        if u is not None:
            uz = u[u["lon"].between(w, e_) & u["lat"].between(s_, n_)]
            sat = uz[uz["saturee"]].sort_values("occupation", ascending=False)
            if len(uz):
                st.markdown(f"**Usage réel des stations Citiz existantes** (collecte GBFS) : {len(uz)} stations, "
                            f"occupation médiane {100 * uz['occupation'].median():.0f} % ; **{len(sat)} saturées** "
                            f"(voitures réservées plus de {100 * C.SATURATION_OCCUPANCY:.0f} % du temps relevé).")
                if len(sat):
                    st.dataframe(pd.DataFrame({
                        "Station": sat["name"], "Voitures": sat["vehicules"],
                        "Occupation (%)": (100 * sat["occupation"]).round(0),
                        "Au moins une voiture libre (% du temps)": (100 * sat["disponibilite"]).round(0),
                        "Relevés": sat["releves"]}), hide_index=True, height=min(300, 38 + 35 * len(sat)))
                    st.caption("Ajouter une voiture dans une station saturée coûte moins cher qu'ouvrir une station et "
                               "la demande y est déjà démontrée : à arbitrer avec les nouvelles stations ci-dessous.")
    lines = []
    if zero1 is not None and key != "citiz":
        lines.append(f"Dont **{fmt(zero1)} personnes** qui passent de 0 à au moins 1 option à 5 min.")
    if ref:
        lines.append(f"Même budget, même offre existante : Mobili'Score (modèle de valeur) "
                     f"**{fmt(sel.get('pop_newly_served'))}** habitants nouvellement desservis · {NO_MODEL} "
                     f"**{fmt(ref.get('pop_newly_served'))}**. La référence sans modèle traite tous les sites comme "
                     "également utilisés ; le modèle arbitre vers les sites où l'usage attendu est plus fort.")
    for ln in lines:
        st.caption(ln)
    show = pd.DataFrame({
        "Rang": rec["rank"], "Équipement": rec["type"].map(ad.KIND_LABEL), "Commune": rec["commune"],
        "Habitants nouvellement desservis": rec["pop_newly_served"],
        f"Habitants {C.GROWTH_HORIZON}": rec[f"pop_{C.GROWTH_HORIZON}"],
        "Usage estimé (hypothèses)": rec["usage_pred"].astype(str) + " " + rec["usage_unit"],
        "Valeur relative (modèle)": rec["value_rel"],
        "Coût 5 ans (€)": rec["cost_eur"], "Cumul (€)": rec["cost_cum_eur"],
        "€ / habitant": rec["eur_per_new_resident"], "CO₂ évité (t/an)": rec["co2_avoided_t_yr"],
    })
    if key == "citiz":
        show["Véhicules justifiés"] = rec["vehicles_suggested"]
    st.dataframe(show, hide_index=True, height=min(420, 38 + 35 * len(show)),
                 column_config={"Usage estimé (hypothèses)": st.column_config.TextColumn(help=USAGE_HELP),
                                "Coût 5 ans (€)": st.column_config.NumberColumn(format="%d"),
                                "Cumul (€)": st.column_config.NumberColumn(format="%d"),
                                "Valeur relative (modèle)": st.column_config.ProgressColumn(
                                    min_value=0.0, max_value=1.5, format="%.2f")})
    st.download_button(f"Exporter la liste {FUNDER_SHORT[key]} (CSV)", rec.to_csv(index=False).encode("utf-8"),
                       file_name=f"recommandations_{key}_{area}_{lam:.1f}.csv".replace(":", "_"),
                       mime="text/csv", key=f"dl_{key}")
    with st.expander("Comparaison des stratégies (même budget)"):
        strat = [("Mobili'Score (λ = %.1f)" % lam, sel), (NO_MODEL, ad.strategy(summ, "no_model")),
                 (EQUITY_OFF, ad.strategy(summ, "no_equity")),
                 ("Sans la fréquence des lignes", ad.strategy(summ, "no_frequency")),
                 ("Naïve : population seule", ad.strategy(summ, "naive"))]

        def _pct(d, k):
            v = d.get(k)
            return 100 * v if v is not None else np.nan

        rows = []
        for n, d in strat:
            if not d:
                continue
            r = {"Stratégie": n, "Sites": d.get("n_sites"),
                 "Habitants nouvellement desservis": d.get("pop_newly_served", 0)}
            if key != "citiz":
                r["Personnes distinctes"] = ad.field(d, "distinct")
            r.update({"De 0 à ≥ 1 option": ad.field(d, "zero_to_one"),
                      "€ / habitant": d.get("eur_per_new_resident"), "CO₂ évité (t/an)": d.get("co2_avoided_t_yr"),
                      "% déciles 1-3": _pct(d, "share_new_in_income_deciles_1_3"),
                      "% zone peu dense": _pct(d, "share_new_in_low_density")})
            rows.append(r)
        cdf = pd.DataFrame(rows)
        if len(cdf):
            st.altair_chart(alt.Chart(cdf).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(y=alt.Y("Stratégie:N", sort=None, title=None),
                                    x=alt.X("Habitants nouvellement desservis:Q"),
                                    color=alt.condition(alt.datum["Stratégie"] == rows[0]["Stratégie"],
                                                        alt.value("#2a78d6"), alt.value("#b5b4ae")),
                                    tooltip=list(cdf.columns))
                            .properties(height=40 + 34 * len(cdf)), use_container_width=True)
            st.dataframe(cdf.round(1), hide_index=True)
        st.caption(f"{NO_MODEL} : même optimisation et même offre existante, mais chaque site a la même valeur "
                   "(pas de modèle). " + EQUITY_OFF + " : " + EQUITY_OFF_HELP + " Stratégie naïve : "
                   + C.NAIVE_LABEL + ". Tous les indicateurs sont recalculés sur la population réellement NON "
                   "desservie aujourd'hui.")
    with st.expander("Hypothèses de ce calcul"):
        st.json(summ.get("hypotheses", {}), expanded=False)
        st.caption(f"Temps de calcul : {summ.get('runtime_s')}")


# =========================================================================== barre latérale
with st.sidebar:
    st.title("Mobili'Score")
    st.caption("Qui a vraiment une option de mobilité à 5 min de chez soi, et où en ajouter ?")
    choices = ["top", "ems", "fr", "972", "974", "dep"]
    if ad.top_epci() is None:
        choices.remove("top")
    labels = {**ad.ZONES, "dep": "Un département…"}
    labels["top"] = ad.zone_label("top")
    zsel = st.radio("Territoire", choices, format_func=labels.get, index=0)
    if zsel == "dep":
        deps = ad.dep_index(V)
        deps = deps[~deps["dep"].isin(["972", "974"])]
        lab = st.selectbox("Département", deps["label"].tolist(),
                           index=int(np.flatnonzero(deps["dep"].values == "67")[0]))
        zone = lab.split(" – ")[0]
    else:
        zone = zsel
    if zone == "fr":
        size_m = st.select_slider("Maille d'agrégation", options=[1000, 2000, 5000, 10000], value=5000,
                                  format_func=lambda v: f"{v // 1000} km")
        if size_m < 5000:
            st.caption("⚠️ Maille fine sur toute la France : plusieurs centaines de milliers de carrés, "
                       "affichage lent sur un ordinateur modeste.")
    else:
        n_cells = (int(ad.dep_index(V).set_index("dep")["n_cells"].get(zone, 0)) if zone not in ("ems", "top")
                   else ad.zone_n_cells(zone, V))
        auto = 200 if n_cells <= 30000 else 400
        size_m = st.select_slider("Maille d'affichage", options=[200, 400, 1000, 2000], value=auto,
                                  format_func=lambda v: f"{v} m" if v < 1000 else f"{v // 1000} km")
    st.divider()
    st.caption(f"Rayon 5 min de marche : **{geo.walk_radius_m():.0f} m** à vol d'oiseau "
               f"(= {C.WALK_NETWORK_M:.0f} m de réseau / détour {geo.detour_factor():.2f}).")
    st.caption("Données : INSEE Filosofi 2021 (carreaux 200 m), GTFS transport.data.gouv.fr, "
               "GBFS (MobilityData), RP 2021, Omphale, OpenStreetMap.")
    st.caption(f"Confidentialité : revenu, pauvreté et motorisation ne sont affichés que sur des agrégats "
               f"d'au moins {C.PRIVACY_MIN_HOUSEHOLDS} ménages ; l'accessibilité, purement géographique, "
               f"est affichée au carreau.")

st.markdown(f"### {ad.zone_label(zone)}")
tab1, tab2, tab_fr, tab3, tab4 = st.tabs(["Carte d'accessibilité", "Qui est concerné",
                                          "Où s'implanter (France)", "Où investir", "Méthode & limites"])

# =========================================================================== 1. carte
FREQ_LABELS = {"freq": "la fréquence des lignes (GTFS du réseau)", "count": "le nombre d'arrêts (méthode nationale)"}
with tab1:
    fq_df, fq_sum = ad.zone_frequency(zone, V)
    measure = "count"
    if fq_df is not None:
        measure = st.radio("Bus, tram et métro mesurés par", ["freq", "count"], format_func=FREQ_LABELS.get,
                           horizontal=True,
                           help="Fréquence : une ligne compte une fois même si elle passe à plusieurs arrêts proches, "
                                f"et une ligne toutes les 15 min ou mieux vaut 1 option pleine ({C.FULL_OPTION_DEP_H:g} "
                                "départs/h, entre 7 h et 20 h un mardi hors vacances). Nombre d'arrêts : méthode "
                                "nationale, sans horaires.")
    if measure == "freq":
        cmp_ = (fq_sum or {}).get("comparaison") or {}
        pop_z = float(fq_df["ind"].sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Habitants", fmt(pop_z))
        c2.metric("Un arrêt à 5 min (comptage)", f"{100 * cmp_.get('part_pop_arret_tc_5min', 0):.0f} %")
        c3.metric("Au moins 1 option pleine (fréquence)",
                  f"{100 * cmp_.get('part_pop_au_moins_1_option_tc_pleine', 0):.0f} %")
        weak = cmp_.get("part_pop_arret_mais_service_faible", 0)
        c4.metric("Un arrêt, mais service faible", f"{100 * weak:.1f} %", f"≈ {fmt(weak * pop_z)} habitants",
                  delta_color="off", help=cmp_.get("lecture"))
        deck([square_layer(fq_df)], view_for(fq_df), height=620)
        legend_score()
        days = ", ".join(f"{k} : {d['jour']}" for k, d in ((fq_sum or {}).get("jour_reference") or {}).items())
        st.caption(f"Score = rang des options à 5 min, bus/tram/métro pondérés par la fréquence (autres modes comptés "
                   f"comme dans la méthode nationale). Jour de référence {days}. « Service faible » : un arrêt existe à "
                   f"5 min mais il passe moins d'un bus toutes les 15 min en cumulé ; le comptage d'arrêts classe ces "
                   f"habitants comme desservis.")
        mc = None
    else:
        with st.spinner("Calcul de la carte…"):
            mc, masked_pop, prov = ad.map_cells(zone, size_m, V)
    if measure == "freq":
        pass
    elif mc is None:
        missing("La carte nationale d'accessibilité", "python -m src.accessibility")
        st.caption("En attendant, choisissez un territoire (Strasbourg, un département, un DROM) : "
                   "l'accessibilité y est recalculée à la volée.")
    else:
        k = ad.zone_kpis(zone, V)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Habitants", fmt(k["population"]))
        c2.metric("Sans aucune option à 5 min", fmt(k["pop_no_option"]),
                  f"{100 * k['pop_no_option'] / k['population']:.1f} % de la population", delta_color="off")
        c3.metric("Score moyen (pondéré population)", f"{k['mean_score']:.0f} / 100")
        c4.metric("Carrés affichés", fmt(len(mc)))
        deck([square_layer(mc)], view_for(mc), height=620)
        legend_score()
        notes = []
        if prov:
            notes.append("Score **provisoire** : rang percentile calculé à l'intérieur du territoire affiché "
                         "(le score national sera utilisé dès que `outputs/cells_access.parquet` existera).")
        notes.append(f"Le score est géographique (options à 5 min) et affiché pour chaque carré, y compris "
                     f"peu peuplé. Revenu, pauvreté et motorisation n'apparaissent dans l'infobulle que pour les "
                     f"carrés d'au moins {C.PRIVACY_MIN_HOUSEHOLDS} ménages ({fmt(masked_pop)} hab. vivent dans "
                     f"des carrés où ils sont masqués).")
        notes.append("Le score décrit une offre de transport, pas un quartier.")
        for n in notes:
            st.caption(n)

# =========================================================================== 2. qui est concerné
with tab2:
    k = ad.zone_kpis(zone, V)
    if k is None:
        missing("L'accessibilité nationale", "python -m src.accessibility")
    else:
        st.markdown("#### Population couverte à 5 min de marche, par mode")
        items = [("Aucune option", k["pop_no_option"], f"{100 * k['pop_no_option'] / k['population']:.1f} %")]
        for m in ad.MODES:
            v = k["by_mode"].get(m)
            items.append((C.MODES[m], v, f"{100 * v / k['population']:.0f} %" if v is not None else None))
        per_row = 4   # 4 par ligne : nombres et libellés entiers, sans troncature
        for i in range(0, len(items), per_row):
            cols = st.columns(per_row)
            for c, (lab, v, d) in zip(cols, items[i:i + per_row]):
                c.metric(lab, fmt(v) if v is not None else "–", d, delta_color="off")

    show_pts = True
    if zone == "fr":
        show_pts = st.checkbox("Afficher les ~200 000 points d'offre de toute la France (lourd)", value=False,
                               help="Désactivé au lancement pour ne pas surcharger le navigateur. "
                                    "Pour une vue plus légère, choisissez un territoire dans le panneau de gauche.")
    if show_pts:
        with st.spinner("Population desservie par chaque point…"):
            sts, src = ad.zone_stations(zone, V)
    if show_pts and sts is None:
        missing("Les points d'offre nationaux", "python -m src.accessibility")
    elif show_pts:
        present = [m for m in ad.MODES if (sts["mode"] == m).any()]
        sel = st.multiselect("Types d'offre affichés", present, default=present, format_func=C.MODES.get)
        s = sts[sts["mode"].isin(sel)].copy()
        s["tip"] = ("<b>" + s["name"] + "</b><br/>" + s["mode_label"] + "<br/>" + s["operator"]
                    + "<br/>≈ " + s["pop_txt"] + " habitants à 5 min"
                    + "<br/>dont ≈ " + s["excl_txt"] + " perdraient tout accès à ce mode si ce point fermait")
        # petits points (arrêts de bus) dessous, offre partagée par-dessus
        order = {"transit": 0, "rail": 1, "scooter": 2, "bike": 3, "carsharing": 4, "citiz": 5}
        s = s.sort_values("mode", key=lambda x: x.map(order))
        layer = pdk.Layer("ScatterplotLayer", s[["lon", "lat", "r", "g", "b", "radius", "tip"]], id="stations",
                          get_position="[lon, lat]", get_radius="radius", radius_units="meters",
                          radius_min_pixels=2, radius_max_pixels=30, get_fill_color="[r, g, b, 190]",
                          get_line_color=[255, 255, 255], line_width_min_pixels=1, stroked=True, pickable=True)
        deck([layer], view_for(sts), height=560)
        legend_modes(sel)
        st.caption(f"Taille du point ∝ √(habitants à 5 min). Source de la population desservie : {src}. "
                   "Un habitant peut être compté par plusieurs points proches ; « perdraient tout accès » = "
                   "habitants dont c'est le seul point de ce mode à 5 min.")
        tbl = (s.groupby("mode_label").agg(points=("pop_served", "size"),
                                            habitants_median=("pop_served", "median"),
                                            habitants_max=("pop_served", "max")).round(0)
               .rename_axis("Mode").reset_index())
        with st.expander("Tableau par mode et points les plus utiles"):
            st.dataframe(tbl, hide_index=True)
            top = s.nlargest(20, "pop_served")[["name", "mode_label", "operator", "pop_served",
                                                 "pop_served_exclusive"]]
            st.dataframe(top.rename(columns={"name": "Point", "mode_label": "Mode", "operator": "Opérateur",
                                             "pop_served": "Habitants à 5 min",
                                             "pop_served_exclusive": "Sans autre point du mode"}).round(0),
                         hide_index=True)

    st.markdown("#### Équité : accès selon le niveau de revenu des habitants")
    eq = ad.equity_deciles(zone, V)
    if eq is None:
        st.caption("Données insuffisantes pour ce territoire.")
    else:
        c1, c2 = st.columns(2)
        base = alt.Chart(eq).encode(
            x=alt.X("Décile:N", sort=list(eq["Décile"]), title="Décile de revenu / habitant (D1 = plus modestes)"),
            tooltip=[alt.Tooltip("Décile:N"), alt.Tooltip("score_moyen:Q", format=".0f", title="Score moyen"),
                     alt.Tooltip("part_sans_option:Q", format=".1f", title="% sans option"),
                     alt.Tooltip("pop:Q", format=",.0f", title="Habitants")])
        c1.altair_chart(base.mark_bar(color="#2a78d6", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                        .encode(y=alt.Y("score_moyen:Q", title="Score moyen (0-100)"))
                        .properties(height=260, title="Score d'accessibilité moyen"), use_container_width=True)
        c2.altair_chart(base.mark_bar(color="#eb6834", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                        .encode(y=alt.Y("part_sans_option:Q", title="% des habitants"))
                        .properties(height=260, title="Part sans aucune option à 5 min"), use_container_width=True)
        st.caption("Déciles calculés sur les habitants du territoire affiché (Filosofi 2021). "
                   "Lecture : en zone dense, les ménages modestes vivent souvent près des lignes ; "
                   "l'enjeu d'équité porte alors sur les périphéries peu denses.")
    summ = ad.read_json(ad.F_SUMMARY)
    if summ:
        with st.expander("Synthèse nationale (access_summary.json)"):
            st.json(summ, expanded=False)

# =========================================================================== 3. où s'implanter (France)
with tab_fr:
    st.markdown("#### Où Citiz doit-il s'implanter en priorité ?")
    tr = ad.territories_ranking(V)
    if tr is None:
        missing("Le classement national des territoires", "python -m src.territories")
    else:
        ts = ad.read_json(ad.F_TERR_SUM) or {}
        top = tr.iloc[0]
        ref = tr[tr["reference"]]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Territoire prioritaire", top["territoire"], top["statut"], delta_color="off")
        k2.metric("Habitants à 5 min des nouvelles stations", fmt(top["sim_pop_newly_served"]),
                  f"{int(top['sim_sites'])} stations · {C.CITIZ_BUDGET / 1e6:.1f} M€ sur {C.HORIZON_YEARS} ans",
                  delta_color="off")
        k3.metric("Adhérents potentiels", fmt(top["sim_members_potential"]),
                  f"≈ {int(top['sim_vehicles_suggested'])} véhicules justifiés", delta_color="off", help=USAGE_HELP)
        if len(ref):
            r0 = ref.iloc[0]
            k4.metric("Même budget à Strasbourg (témoin)", fmt(r0["sim_pop_newly_served"]) + " hab.",
                      f"{fmt(r0['sim_members_potential'])} adhérents potentiels", delta_color="off")
        st.caption(
            f"Méthode en deux temps. 1) **Criblage** des {ts.get('n_epci_eligible', '')} intercommunalités "
            f"de plus de {C.TERRITORY_MIN_POP:,} habitants : habitants des quartiers denses sans autopartage à "
            "5 min, pondérés par la valeur du site prédite par le modèle (entraîné sur les stations Citiz et "
            "d'autopartage existantes, propensions hors pli départemental). 2) **Simulation** : sur les "
            f"{C.TERRITORY_SHORTLIST} premières, l'optimiseur place les stations Citiz que permet le même budget ; "
            "classement par adhérents potentiels. Île-de-France exclue : son autopartage est presque absent des "
            "flux GBFS publics.".replace(",", " "))
        sh = tr[tr["rank"].notna() | tr["reference"]].copy()
        sh["Territoire"] = sh["territoire"] + np.where(sh["reference"], " (témoin)", "")
        st.altair_chart(
            alt.Chart(sh).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
            .encode(y=alt.Y("Territoire:N", sort="-x", title=None),
                    x=alt.X("sim_members_potential:Q", title="Adhérents potentiels (même budget Citiz)"),
                    color=alt.Color("statut:N", title=None,
                                    scale=alt.Scale(domain=["nouveau territoire", "extension"],
                                                    range=["#eb6834", "#2a78d6"])),
                    tooltip=[alt.Tooltip("Territoire:N"), alt.Tooltip("statut:N"),
                             alt.Tooltip("population:Q", format=",.0f", title="Habitants"),
                             alt.Tooltip("sim_pop_newly_served:Q", format=",.0f", title="Nouveaux desservis"),
                             alt.Tooltip("sim_members_potential:Q", format=",.0f", title="Adhérents potentiels"),
                             alt.Tooltip("sim_top_communes:N", title="Communes")])
            .properties(height=40 + 30 * len(sh)), use_container_width=True)
        tbl = pd.DataFrame({
            "Rang": sh["rank"], "Territoire": sh["Territoire"], "Statut Citiz": sh["statut"],
            "Habitants": sh["population"],
            "Couverts par l'autopartage (%)": (100 * sh["share_carsharing_served"]).round(1),
            "Ménages sans voiture (%)": (100 * sh["share_carfree_households"]).round(0),
            "Potentiel (criblage)": sh["potential"], "Stations": sh["sim_sites"],
            "Nouveaux desservis": sh["sim_pop_newly_served"], "Adhérents potentiels": sh["sim_members_potential"],
            "CO₂ évité (t/an)": sh["sim_co2_t_yr"]})
        st.dataframe(tbl, hide_index=True)
        with st.expander("Criblage complet (toutes les intercommunalités éligibles)"):
            st.dataframe(tr[tr["eligible"]][["screen_rank", "territoire", "statut", "population",
                                              "share_carsharing_served", "share_citiz_served", "pop_dense_unserved",
                                              "mean_value_unserved", "potential"]], hide_index=True)
        st.caption("« Nouveau territoire » : aucune station Citiz aujourd'hui. Strasbourg, où Citiz est déjà bien "
                   "implanté, sert de témoin : le même budget y rapporte beaucoup moins, car les quartiers denses "
                   "y sont déjà couverts. Limite : un autopartage local qui ne publie pas de flux GBFS n'est pas vu.")

# =========================================================================== 4. où investir
with tab3:
    area = ad.reco_area(zone)
    st.markdown("#### Où implanter les prochaines stations ? Une liste par financeur")
    c1, c2, c3 = st.columns(3)
    b_citiz = c1.slider("Budget Citiz sur 5 ans (€)", 0, 5_000_000, int(C.CITIZ_BUDGET), step=100_000,
                        format="%d €", help="Stations d'autopartage, financées et exploitées par Citiz.")
    b_public = c2.slider("Budget collectivité sur 5 ans (€)", 0, 5_000_000, int(C.PUBLIC_BUDGET), step=100_000,
                         format="%d €", help="Stations vélo et arrêts de bus, financés par la collectivité / AOM.")
    lam = c3.slider("Priorité équité λ", 0.0, 1.0, float(C.EQUITY_LAMBDA), 0.1,
                    help="0 = sans pondération d'équité (chaque habitant pèse selon la population et la "
                         "valeur du site ; ce n'est pas un maximum du nombre de personnes desservies) ; "
                         "1 = forte priorité aux ménages modestes, sans voiture et aujourd'hui peu desservis.")
    if area is None:
        st.info("L'optimisation se lance sur un territoire : choisissez le territoire prioritaire, Strasbourg, "
                "un département ou un DROM.")
    elif b_citiz + b_public <= 0:
        st.warning("Indiquez au moins un budget.")
    elif not ad.model_ready():
        missing("Le modèle de valeur des sites", "python -m src.model")
        if ad.exists(ad.F_RECO):
            st.caption("Dernière liste calculée (territoire prioritaire, paramètres par défaut) :")
            st.dataframe(pd.read_csv(ad.F_RECO), hide_index=True)
    else:
        compare = st.toggle("Comparer avec les autres stratégies (plus lent)", value=False,
                            help="Désactivé : seule la stratégie recommandée est recalculée, en direct à chaque "
                                 "mouvement de curseur. Activé : sans modèle, sans équité, naïve… (même budget).")
        secs = None
        try:
            with st.spinner("Optimisation en cours (premier calcul d'un territoire : ~5-30 s)…"):
                if compare:
                    rec, full = ad.run_recommend_funders(area, b_citiz, b_public, lam, V)
                else:
                    rec, full, secs = ad.run_recommend_fast(area, b_citiz, b_public, lam, V)
        except Exception as e:  # message clair plutôt qu'une trace
            st.error(f"Le calcul de recommandation a échoué : {e}")
            rec, full = pd.DataFrame(), None
        if secs is not None:
            st.caption(f"Liste recalculée en {secs:.1f} s (contexte du territoire gardé en mémoire : seul "
                       "l'algorithme glouton est relancé).")
        if full is not None and len(rec) and st.toggle("Afficher le prix de l'équité", value=True):
            with st.spinner(f"Prix de l'équité : {len(ad.EQUITY_LAMBDAS)} optimisations…"):
                eqc = ad.equity_curve(area, b_citiz, b_public, V)
            if len(eqc):
                eqc["Financeur"] = eqc["financeur"].map(FUNDER_SHORT)
                eqc["actuel"] = np.isclose(eqc["λ"], lam)
                base = alt.Chart(eqc).encode(
                    x=alt.X("part_modestes:Q", title="% des nouveaux desservis dans les 3 premiers déciles de revenu",
                            scale=alt.Scale(zero=False)),
                    y=alt.Y("habitants:Q", title="Habitants nouvellement desservis", scale=alt.Scale(zero=False)),
                    color=alt.Color("Financeur:N", scale=alt.Scale(domain=["Citiz", "collectivité"],
                                                                     range=["#eb6834", "#2a78d6"])),
                    tooltip=[alt.Tooltip("Financeur:N"), alt.Tooltip("λ:Q", format=".2f"),
                             alt.Tooltip("habitants:Q", format=",.0f"), alt.Tooltip("part_modestes:Q", format=".1f"),
                             alt.Tooltip("co2:Q", format=".0f", title="CO₂ évité (t/an)"), alt.Tooltip("sites:Q")])
                chart = (base.mark_line(strokeWidth=2)
                         + base.mark_circle().encode(size=alt.condition(alt.datum.actuel, alt.value(220), alt.value(60)))
                         + base.mark_text(dy=-12, fontSize=11).encode(text=alt.Text("λ:Q", format=".2f")))
                st.altair_chart(chart.properties(height=260, title="Le prix de l'équité (λ de 0 à 1, même budget)"),
                                use_container_width=True)
                st.caption("Chaque point est une optimisation complète avec la priorité d'équité λ indiquée (gros point "
                           "= λ choisi). Vers la droite : plus de ménages modestes parmi les nouveaux desservis ; vers le "
                           "bas : moins d'habitants au total. La pente est le prix de l'équité, que le décideur choisit.")
        if full is not None and len(rec) == 0:
            st.warning("Aucun site retenu (budget trop faible ou territoire déjà entièrement desservi).")
        if full is not None and len(rec):
            funders = full.get("funders") or {}
            sites = tuple((t, float(lo), float(la)) for t, lo, la in zip(rec["type"], rec["lon"], rec["lat"]))
            cov = ad.newly_served_cells(area, sites)
            pts = rec.assign(
                r=[ad.KIND_COLOR[t][0] for t in rec["type"]], g=[ad.KIND_COLOR[t][1] for t in rec["type"]],
                b=[ad.KIND_COLOR[t][2] for t in rec["type"]], label=rec["rank"].astype(str),
                tip=[f"<b>#{r} · {ad.KIND_LABEL[t]}</b> ({FUNDER_SHORT[f]})<br/>{c}<br/>{fmt(p)} habitants "
                     f"nouvellement desservis<br/>{fmt(co)} € sur 5 ans · {e if pd.notna(e) else '–'} €/hab."
                     for f, r, t, c, p, co, e in zip(rec["financeur"], rec["rank"], rec["type"], rec["commune"],
                                                     rec["pop_newly_served"], rec["cost_eur"],
                                                     rec["eur_per_new_resident"])])
            off = ad.load_offer(V)
            w, s_, e_, n_ = pts["lon"].min() - .05, pts["lat"].min() - .03, pts["lon"].max() + .05, pts["lat"].max() + .03
            kinds = sorted(rec["type"].unique())
            ex_modes = sorted({m for kd in kinds for m in C.KIND_TARGET_MODES[kd]})
            ex = off[off["mode"].isin(ex_modes) & off["lon"].between(w, e_) & off["lat"].between(s_, n_)].copy()
            ex["tip"] = "Offre existante : " + ex["mode"].map(C.MODES) + "<br/>" + ex["name"].fillna("")
            layers = []
            if len(cov):
                layers.append(square_layer(cov, opacity=0.35, lid="cov"))
            layers += [
                pdk.Layer("ScatterplotLayer", ex[["lon", "lat", "tip"]], id="existing", get_position="[lon, lat]",
                          get_radius=3, radius_units="pixels", get_fill_color=[110, 110, 110, 140], pickable=True),
                pdk.Layer("ScatterplotLayer", pts[["lon", "lat", "r", "g", "b", "tip"]], id="sites",
                          get_position="[lon, lat]", get_radius=11, radius_units="pixels",
                          get_fill_color="[r, g, b, 235]", get_line_color=[255, 255, 255], stroked=True,
                          line_width_min_pixels=2, pickable=True),
                pdk.Layer("TextLayer", pts[["lon", "lat", "label", "tip"]], id="labels", get_position="[lon, lat]",
                          get_text="label", get_size=12, get_color=[255, 255, 255], font_weight=700,
                          get_alignment_baseline="'center'", pickable=False),
            ]
            deck(layers, view_for(pts), height=560)
            leg = "".join(f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px">'
                          f'<span style="width:12px;height:12px;border-radius:50%;background:rgb{ad.KIND_COLOR[t]}">'
                          f'</span>{ad.KIND_LABEL[t]}</span>' for t in kinds)
            st.markdown(f'<div style="font-size:13px;color:{INK2}">{leg}<span style="margin-left:6px">'
                        f'· numéros = rang dans la liste de chaque financeur · carrés clairs = carreaux nouvellement '
                        f'desservis · points gris = offre existante du même type</span></div>', unsafe_allow_html=True)

            for key in ("citiz", "collectivite"):
                summ = funders.get(key)
                part = rec[rec["financeur"] == key]
                if not summ:
                    continue
                st.divider()
                st.markdown(f"### {FUNDER_TITLE[key]}")
                if len(part) == 0:
                    st.write("Aucun site retenu avec ce budget.")
                    continue
                kz = ad.zone_kpis(zone, V) if key == "collectivite" else None
                if kz and kz["by_mode"].get("bike", 1) == 0 and (part["type"] == "bike").any():
                    st.warning("Aucune station vélo publiée en GBFS sur ce territoire : si un service existe sans "
                               "flux ouvert (à Nice, Vélo Bleu), ces stations vélo peuvent doublonner l'existant. "
                               "À vérifier avec la collectivité avant toute décision.")
                funder_block(key, part, summ, off, (w, s_, e_, n_), lam, area)

# =========================================================================== 5. méthode
with tab4:
    st.markdown("#### Comment c'est calculé")
    calib = ad.read_json(ad.F_CALIB)
    c1, c2, c3 = st.columns(3)
    c1.metric("5 min de marche", f"{C.WALK_NETWORK_M:.0f} m de réseau", f"{C.WALK_SPEED_KMH} km/h", delta_color="off")
    if calib:
        ci = calib.get("detour_ci95", [np.nan, np.nan])
        c2.metric("Coefficient de détour (OSM Strasbourg)", f"{calib['detour']:.2f}",
                  f"IC95 {ci[0]:.2f}-{ci[1]:.2f}", delta_color="off")
        c3.metric("Rayon équivalent à vol d'oiseau", f"{geo.walk_radius_m():.0f} m",
                  f"{calib.get('graph', {}).get('nodes', 0):,} nœuds piétons".replace(",", " "), delta_color="off")
        st.caption(calib.get("method", ""))
    else:
        c2.metric("Coefficient de détour", f"{C.DEFAULT_DETOUR:.2f}", "valeur par défaut", delta_color="off")
        missing("La calibration OSM du détour", "python -m src.walk_calibration")

    st.markdown("#### Modèle de valeur d'un site (validation croisée spatiale)")
    mm = ad.read_json(ad.F_METRICS)
    if not mm:
        missing("Les métriques du modèle", "python -m src.model")
    else:
        st.caption(f"{mm.get('cv', '')} · {mm.get('pu_note', '')}")
        bt = ((mm["kinds"].get("citiz") or {}).get("within_dep_backtest") or {}).get("hgb", {})
        b67 = (bt.get("by_dep") or {}).get("67")
        if b67:
            st.caption(f"Modèle Citiz appris sur {mm['kinds']['citiz'].get('n_departements', '')} départements où "
                       f"l'autopartage existe, dont le "
                       f"Bas-Rhin. Test sur Strasbourg (Bas-Rhin tenu hors de l'apprentissage) : il retrouve les "
                       f"carreaux réellement équipés avec une PR-AUC de {b67['ap_model']:.2f}, contre "
                       f"{b67['ap_pop']:.2f} pour la population seule ; il bat la population seule dans "
                       f"{bt.get('model_beats_pop_ap')} départements sur {bt.get('n_deps')}.")
        rows = []
        mlab = {"hgb": "Gradient boosting", "logit": "Régression logistique", "pop_only": "Population seule"}
        for kd, r in mm["kinds"].items():
            for m, v in r["models"].items():
                fm, fs = v.get("fold_mean", {}), v.get("fold_std", {})
                rows.append({"Équipement": ad.KIND_LABEL.get(kd, kd), "Modèle": mlab.get(m, m),
                             "ROC-AUC": f"{fm.get('roc_auc', np.nan):.3f} ± {fs.get('roc_auc', np.nan):.3f}",
                             "PR-AUC": f"{fm.get('pr_auc', np.nan):.3f} ± {fs.get('pr_auc', np.nan):.3f}",
                             "Brier": f"{fm.get('brier', np.nan):.3f}",
                             "Taux de positifs": f"{100 * r.get('positive_rate', np.nan):.1f} %",
                             "Carreaux / départements": f"{r.get('n_train', 0):,} / {r.get('n_departements', 0)}"
                             .replace(",", " ")})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        caps = [{"Équipement": ad.KIND_LABEL.get(kd, kd), "Unité": r["capacity"]["unit"],
                 "Spearman modèle": round(r["capacity"]["spearman_hgb"], 3),
                 "Spearman population seule": round(r["capacity"]["spearman_pop_only"], 3),
                 "MAE modèle": round(r["capacity"]["mae_hgb"], 2),
                 "MAE médiane": round(r["capacity"]["mae_mean_baseline"], 2)}
                for kd, r in mm["kinds"].items() if "capacity" in r]
        if caps:
            st.markdown("Cible secondaire : capacité installée (proxy d'intensité d'usage)")
            st.dataframe(pd.DataFrame(caps), hide_index=True)
        kd = st.selectbox("Importance des variables (permutation, PR-AUC)", list(mm["kinds"]),
                          format_func=ad.KIND_LABEL.get)
        pi = pd.Series(mm["kinds"][kd].get("permutation_importance", {})).head(12)
        if len(pi):
            pdf = pi.rename("importance").rename_axis("variable").reset_index()
            st.altair_chart(alt.Chart(pdf).mark_bar(color="#2a78d6", cornerRadiusTopRight=4,
                                                    cornerRadiusBottomRight=4)
                            .encode(y=alt.Y("variable:N", sort=None, title=None),
                                    x=alt.X("importance:Q", title="Baisse de PR-AUC si la variable est brouillée"),
                                    tooltip=["variable", alt.Tooltip("importance:Q", format=".3f")])
                            .properties(height=320), use_container_width=True)
        figs = sorted(C.FIG.glob(f"model_{kd}_*.png"))
        if figs:
            with st.expander("Courbes ROC / PR / calibration"):
                for f in figs:
                    st.image(str(f), width="stretch")

    st.markdown("#### Validation par l'usage réel (collecte GBFS Citiz)")
    uv = ad.usage_validation()
    if not uv:
        missing("La validation par l'usage réel", "python -m src.collect_gbfs puis python -m src.usage")
    else:
        per = uv.get("periode", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Stations Citiz suivies", fmt(uv.get("stations_validees")),
                  f"{fmt(per.get('releves'))} relevés toutes les 5 min", delta_color="off")
        c2.metric("Lien modèle ↔ occupation (Spearman)", f"{uv.get('spearman_modele_occupation', 0):+.2f}",
                  f"population seule : {uv.get('spearman_population_occupation', 0):+.2f}", delta_color="off")
        sat = uv.get("saturation", {})
        c3.metric("Stations saturées", fmt(sat.get("stations_saturees")),
                  f"occupation ≥ {100 * sat.get('seuil_occupation', 0):.0f} %", delta_color="off")
        q = pd.DataFrame(uv.get("occupation_par_quintile_de_propension", []))
        if len(q):
            q["occupation_moyenne"] = 100 * q["occupation_moyenne"]
            st.altair_chart(alt.Chart(q).mark_bar(color="#eb6834", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                            .encode(x=alt.X("quintile:N", title="Quintile de propension du modèle (hors pli)"),
                                    y=alt.Y("occupation_moyenne:Q", title="Occupation moyenne (%)"),
                                    tooltip=["quintile", alt.Tooltip("occupation_moyenne:Q", format=".1f"), "stations"])
                            .properties(height=220), use_container_width=True)
        st.caption(uv.get("lecture", "") + " Période : " + str(per.get("debut", ""))[:16] + " → "
                   + str(per.get("fin", ""))[:16] + ". Limites : " + " ; ".join(uv.get("limites", [])) + ".")

    st.markdown("#### Fréquence des lignes dans les zones d'étude")
    for name in C.FREQ_FEEDS:
        fs = ad.read_json(C.OUT / f"frequency_{name}.json")
        if fs and fs.get("comparaison"):
            cp = fs["comparaison"]
            st.markdown(f"- **{name}** : arrêt à 5 min pour {100 * cp['part_pop_arret_tc_5min']:.0f} % des habitants, "
                        f"mais au moins une option pleine (une ligne toutes les 15 min) pour "
                        f"{100 * cp['part_pop_au_moins_1_option_tc_pleine']:.0f} % ; **service faible** pour "
                        f"{100 * cp['part_pop_arret_mais_service_faible']:.1f} %.")
    st.caption("Calculé par src/frequency.py à partir des GTFS des réseaux (CTS + Fluo 67 à Strasbourg, Lignes d'Azur "
               "à Nice). La valeur d'un nouvel arrêt de bus est multipliée par la qualité de service de sa ligne, et le "
               "besoin « faible accessibilité » utilise ces options pondérées.")

    st.markdown("#### Hypothèses de coûts et d'impact (Config.py)")
    cost_df = pd.DataFrame([{"Équipement": v["label"], "Investissement (€)": v["capex"],
                             "Exploitation (€/an)": v["opex"],
                             f"Total {C.HORIZON_YEARS} ans (€)": C.facility_cost(k)} for k, v in C.COSTS.items()])
    st.dataframe(cost_df, hide_index=True)
    st.caption(f"Arrêt de bus : + coût du détour de ligne = 2 × distance à l'arrêt existant × "
               f"{C.BUS_DETOUR['trips_per_day']} passages/j × 365 × {C.BUS_DETOUR['cost_per_km']} €/km "
               f"(au-delà de {C.BUS_DETOUR['max_dist_m']} m, ce serait une nouvelle ligne).")
    st.markdown(
        f"- **CO₂** (impactco2.fr / ADEME) : voiture {C.CO2_G_PER_KM['car']} g/km, bus {C.CO2_G_PER_KM['bus']} "
        f"g/passager.km ; autopartage : {C.CARSHARING_CAR_KM_AVOIDED_PER_USER} km voiture évités par usager actif "
        f"et par an, {100 * C.CARSHARING_ACTIVE_SHARE:.0f} % d'adhérents actifs ; vélo : "
        f"{C.BIKE_TRIPS_PER_STATION_DAY} trajets/j × {C.BIKE_KM_PER_TRIP} km, {100 * C.BIKE_CAR_SHIFT:.0f} % "
        f"report modal depuis la voiture.\n"
        f"- **Besoin** (pondération équité λ) : rangs dans le territoire de " +
        ", ".join(f"{k} ({v})" for k, v in C.NEED_WEIGHTS.items()) + ".\n"
        f"- **Population future** : projections Omphale {C.GROWTH_HORIZON} (scénario central), appliquées par département.\n"
        f"- **Optimisation** : couverture maximale sous budget, glouton paresseux sur gain/coût, "
        f"garantie (1 − 1/e)/2 de l'optimum.")
    st.markdown("#### Limites reconnues")
    st.markdown(
        "- **Offre ≠ service** : à l'échelle nationale, un arrêt compte même si la fréquence est faible (agrégat sans "
        "horaires). Corrigé dans les zones d'étude (Strasbourg, Nice) par les GTFS des réseaux (src/frequency.py).\n"
        "- **Distance de marche** : rayon euclidien corrigé par un détour calibré sur Strasbourg, "
        "appliqué partout (plus fort en zone peu maillée).\n"
        "- **Modèle positive-unlabeled** : il apprend où les opérateurs se sont déjà implantés ; il reproduit "
        "donc en partie leurs choix passés. Le terme d'équité λ et la comparaison avec la référence sans modèle (v = 1) servent de garde-fous.\n"
        "- **Données GBFS** incomplètes (certains opérateurs ne publient pas), free-floating = zones virtuelles.\n"
        "- **Impact CO₂** : ordres de grandeur sous hypothèses explicites, pas une mesure.\n"
        "- **Coûts** : retours d'expérience publics, à ajuster par l'opérateur ou la collectivité.\n"
        f"- **Confidentialité** : revenu, pauvreté, motorisation jamais affichés sur moins de "
        f"{C.PRIVACY_MIN_HOUSEHOLDS} ménages (l'accessibilité, géographique, reste au carreau) ; vocabulaire "
        "centré sur l'offre (« offre à développer ») pour ne pas stigmatiser un territoire.")
