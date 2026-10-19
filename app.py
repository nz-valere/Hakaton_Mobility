"""
Mobili'Score – démo live (Streamlit).  Lancement : .venv/bin/streamlit run app.py
Onglets : carte d'accessibilité · qui est concerné · où investir · méthode & limites.
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


def legend_score():
    st.markdown(
        f"""<div style="font-size:13px;color:{INK2};margin-top:4px">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="display:inline-block;width:16px;height:16px;background:rgb{ad.ZERO_COLOR};border-radius:3px"></span>
          Aucune option à 5 min (offre à développer)
        </div>
        <div style="margin-top:6px">Score d'accessibilité (0 → 100)</div>
        <div style="height:14px;border-radius:4px;background:{ad.ramp_css()}"></div>
        <div style="display:flex;justify-content:space-between"><span>froid · peu d'options par habitant</span>
        <span>chaud · beaucoup d'options par habitant</span></div></div>""",
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


# =========================================================================== barre latérale
with st.sidebar:
    st.title("Mobili'Score")
    st.caption("Qui a vraiment une option de mobilité à 5 min de chez soi, et où en ajouter ?")
    choices = ["ems", "fr", "972", "974", "dep"]
    labels = {**ad.ZONES, "dep": "Un département…"}
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
        size_m = st.select_slider("Maille d'agrégation", options=[5000, 10000], value=5000,
                                  format_func=lambda v: f"{v // 1000} km")
    else:
        n_cells = int(ad.dep_index(V).set_index("dep")["n_cells"].get(zone, 0)) if zone != "ems" else 2600
        auto = 200 if n_cells <= 30000 else 400
        size_m = st.select_slider("Maille d'affichage", options=[200, 400, 1000, 2000], value=auto,
                                  format_func=lambda v: f"{v} m" if v < 1000 else f"{v // 1000} km")
    st.divider()
    st.caption(f"Rayon 5 min de marche : **{geo.walk_radius_m():.0f} m** à vol d'oiseau "
               f"(= {C.WALK_NETWORK_M:.0f} m de réseau / détour {geo.detour_factor():.2f}).")
    st.caption("Données : INSEE Filosofi 2021 (carreaux 200 m), GTFS transport.data.gouv.fr, "
               "GBFS (MobilityData), RP 2021, Omphale, OpenStreetMap.")
    st.caption(f"Confidentialité : aucun agrégat de moins de {C.PRIVACY_MIN_HOUSEHOLDS} ménages n'est affiché.")

st.markdown(f"### {ad.zone_label(zone)}")
tab1, tab2, tab3, tab4 = st.tabs(["Carte d'accessibilité", "Qui est concerné", "Où investir",
                                  "Méthode & limites"])

# =========================================================================== 1. carte
with tab1:
    with st.spinner("Calcul de la carte…"):
        mc, masked_pop, prov = ad.map_cells(zone, size_m, V)
    if mc is None:
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
        if size_m <= C.CELL:
            notes.append(f"Carreaux de moins de {C.PRIVACY_MIN_HOUSEHOLDS} ménages : valeur lissée sur leur carré "
                         f"de 1 km ; masqués si le carré reste sous le seuil ({fmt(masked_pop)} hab. concernés).")
        else:
            notes.append(f"Carrés de moins de {C.PRIVACY_MIN_HOUSEHOLDS} ménages masqués ({fmt(masked_pop)} hab.).")
        notes.append("Le score compare l'offre (nombre d'options à 5 min, tous modes) rapportée aux habitants "
                     "qui la partagent ; il décrit une offre, pas un quartier.")
        for n in notes:
            st.caption(n)

# =========================================================================== 2. qui est concerné
with tab2:
    k = ad.zone_kpis(zone, V)
    if k is None:
        missing("L'accessibilité nationale", "python -m src.accessibility")
    else:
        st.markdown("#### Population couverte à 5 min de marche, par mode")
        cols = st.columns(len(ad.MODES) + 1)
        cols[0].metric("Aucune option", fmt(k["pop_no_option"]),
                       f"{100 * k['pop_no_option'] / k['population']:.1f} %", delta_color="off")
        for c, m in zip(cols[1:], ad.MODES):
            v = k["by_mode"].get(m)
            c.metric(C.MODES[m], fmt(v) if v is not None else "–",
                     f"{100 * v / k['population']:.0f} %" if v is not None else None, delta_color="off")

    if zone == "fr":
        st.info("Les points d'offre (~200 000) s'affichent par territoire : choisissez Strasbourg, "
                "un département ou un DROM dans le panneau de gauche.")
    else:
        with st.spinner("Population desservie par chaque point…"):
            sts, src = ad.zone_stations(zone, V)
        present = [m for m in ad.MODES if (sts["mode"] == m).any()]
        sel = st.multiselect("Types d'offre affichés", present, default=present, format_func=C.MODES.get)
        s = sts[sts["mode"].isin(sel)].copy()
        s["tip"] = ("<b>" + s["name"] + "</b><br/>" + s["mode_label"] + "<br/>" + s["operator"]
                    + "<br/>≈ " + s["pop_txt"] + " habitants à 5 min")
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
                   "Un habitant peut être compté par plusieurs points proches.")
        tbl = (s.groupby("mode_label").agg(points=("pop_served", "size"),
                                            habitants_median=("pop_served", "median"),
                                            habitants_max=("pop_served", "max")).round(0)
               .rename_axis("Mode").reset_index())
        with st.expander("Tableau par mode et points les plus utiles"):
            st.dataframe(tbl, hide_index=True)
            top = s.nlargest(20, "pop_served")[["name", "mode_label", "operator", "pop_served"]]
            st.dataframe(top.rename(columns={"name": "Point", "mode_label": "Mode", "operator": "Opérateur",
                                             "pop_served": "Habitants à 5 min"}).round(0),
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

# =========================================================================== 3. où investir
with tab3:
    area = ad.reco_area(zone)
    st.markdown("#### Où implanter les prochaines stations ? Liste priorisée sous budget")
    c1, c2, c3 = st.columns([1.2, 1, 1.4])
    budget = c1.slider("Budget sur 5 ans (€)", 100_000, 10_000_000, int(C.DEFAULT_BUDGET), step=100_000,
                       format="%d €")
    lam = c2.slider("Priorité équité λ", 0.0, 1.0, float(C.EQUITY_LAMBDA), 0.1,
                    help="0 = maximiser le nombre d'habitants desservis ; 1 = forte priorité aux ménages "
                         "modestes, sans voiture et aujourd'hui peu desservis.")
    kinds = c3.multiselect("Équipements", list(C.MODEL_KINDS), default=list(C.MODEL_KINDS),
                           format_func=ad.KIND_LABEL.get)
    if area is None:
        st.info("L'optimisation se lance sur un territoire : choisissez Strasbourg, un département ou un DROM.")
    elif not kinds:
        st.warning("Choisissez au moins un type d'équipement.")
    elif not ad.model_ready(kinds):
        missing("Le modèle de valeur des sites", "python -m src.model")
        if ad.exists(ad.F_RECO):
            st.caption("Dernière liste calculée (Strasbourg, paramètres par défaut) :")
            st.dataframe(pd.read_csv(ad.F_RECO), hide_index=True)
    else:
        try:
            with st.spinner("Optimisation en cours (premier calcul d'un territoire : ~5-30 s)…"):
                rec, summ = ad.run_recommend(area, budget, lam, tuple(kinds), V)
        except Exception as e:  # message clair plutôt qu'une trace
            st.error(f"Le calcul de recommandation a échoué : {e}")
            rec, summ = pd.DataFrame(), None
        if summ is not None and len(rec) == 0:
            st.warning("Aucun site retenu (budget trop faible ou territoire déjà entièrement desservi).")
        if summ is not None and len(rec):
            sel = summ["selected"]
            naive = summ.get("comparison", {}).get("naive_population_only", {})
            k1, k2, k3, k4 = st.columns(4)
            gain = sel["pop_newly_served"] / max(naive.get("pop_newly_served", 0), 1) - 1 if naive else None
            k1.metric("Habitants nouvellement desservis", fmt(sel["pop_newly_served"]),
                      f"{100 * gain:+.0f} % vs stratégie naïve" if gain is not None else None)
            k2.metric("CO₂ évité", f"{sel['co2_avoided_t_yr']:.0f} t/an")
            k3.metric("Coût (5 ans)", f"{sel['cost_eur'] / 1e6:.2f} M€",
                      f"{sel['n_sites']} sites", delta_color="off")
            k4.metric("Coût par habitant desservi", f"{sel['eur_per_new_resident']:.0f} €")

            sites = tuple((t, float(lo), float(la)) for t, lo, la in zip(rec["type"], rec["lon"], rec["lat"]))
            cov = ad.newly_served_cells(area, sites)
            pts = rec.assign(
                r=[ad.KIND_COLOR[t][0] for t in rec["type"]], g=[ad.KIND_COLOR[t][1] for t in rec["type"]],
                b=[ad.KIND_COLOR[t][2] for t in rec["type"]], label=rec["rank"].astype(str),
                tip=[f"<b>#{r} · {ad.KIND_LABEL[t]}</b><br/>{c}<br/>{fmt(p)} habitants nouvellement desservis"
                     f"<br/>{fmt(co)} € sur 5 ans · {e if pd.notna(e) else '–'} €/hab."
                     for r, t, c, p, co, e in zip(rec["rank"], rec["type"], rec["commune"],
                                                  rec["pop_newly_served"], rec["cost_eur"],
                                                  rec["eur_per_new_resident"])])
            off = ad.load_offer(V)
            w, s_, e_, n_ = pts["lon"].min() - .05, pts["lat"].min() - .03, pts["lon"].max() + .05, pts["lat"].max() + .03
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
            deck(layers, view_for(pts), height=600)
            leg = "".join(f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px">'
                          f'<span style="width:12px;height:12px;border-radius:50%;background:rgb{ad.KIND_COLOR[t]}">'
                          f'</span>{ad.KIND_LABEL[t]}</span>' for t in kinds)
            st.markdown(f'<div style="font-size:13px;color:{INK2}">{leg}<span style="margin-left:6px">'
                        f'· carrés clairs = carreaux nouvellement desservis · points gris = offre existante '
                        f'du même type</span></div>', unsafe_allow_html=True)

            st.markdown("##### Liste priorisée")
            show = pd.DataFrame({
                "Rang": rec["rank"], "Équipement": rec["type"].map(ad.KIND_LABEL), "Commune": rec["commune"],
                "Habitants nouvellement desservis": rec["pop_newly_served"],
                f"Habitants {C.GROWTH_HORIZON}": rec[f"pop_{C.GROWTH_HORIZON}"],
                "Usage prédit": rec["usage_pred"].astype(str) + " " + rec["usage_unit"],
                "Valeur relative (modèle)": rec["value_rel"],
                "Coût 5 ans (€)": rec["cost_eur"], "Cumul (€)": rec["cost_cum_eur"],
                "€ / habitant": rec["eur_per_new_resident"], "CO₂ évité (t/an)": rec["co2_avoided_t_yr"],
            })
            st.dataframe(show, hide_index=True, height=min(420, 38 + 35 * len(show)),
                         column_config={"Coût 5 ans (€)": st.column_config.NumberColumn(format="%d"),
                                        "Cumul (€)": st.column_config.NumberColumn(format="%d"),
                                        "Valeur relative (modèle)": st.column_config.ProgressColumn(
                                            min_value=0.0, max_value=1.5, format="%.2f")})
            st.download_button("Exporter la liste (CSV)", rec.to_csv(index=False).encode("utf-8"),
                               file_name=f"recommandations_{area}_{int(budget)}_{lam:.1f}.csv", mime="text/csv")

            c1, c2 = st.columns([1.3, 1])
            with c1:
                st.markdown("##### Comparaison des stratégies (même budget)")
                comp = summ.get("comparison", {})
                strat = [("Mobili'Score (λ = %.1f)" % lam, sel), ("Efficacité pure (λ = 0)", comp.get("lambda_0")),
                         ("Naïve : population seule", comp.get("naive_population_only"))]
                rows = [{"Stratégie": n, "Sites": d.get("n_sites"),
                         "Habitants nouvellement desservis": d.get("pop_newly_served", 0),
                         "€ / habitant": d.get("eur_per_new_resident"), "CO₂ évité (t/an)": d.get("co2_avoided_t_yr"),
                         "% déciles 1-3": 100 * d.get("share_new_in_income_deciles_1_3", np.nan),
                         "% zone peu dense": 100 * d.get("share_new_in_low_density", np.nan)}
                        for n, d in strat if d]
                cdf = pd.DataFrame(rows)
                st.altair_chart(alt.Chart(cdf).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                                .encode(y=alt.Y("Stratégie:N", sort=None, title=None),
                                        x=alt.X("Habitants nouvellement desservis:Q"),
                                        color=alt.condition(alt.datum["Stratégie"] == rows[0]["Stratégie"],
                                                            alt.value("#2a78d6"), alt.value("#b5b4ae")),
                                        tooltip=list(cdf.columns))
                                .properties(height=150), use_container_width=True)
                st.dataframe(cdf.round(1), hide_index=True)
                st.caption("Stratégie naïve : " + C.NAIVE_LABEL + ". Tous les indicateurs sont recalculés "
                           "sur la population réellement NON desservie aujourd'hui.")
            with c2:
                cz = rec[rec["type"] == "citiz"]
                existing_citiz = int(((off["mode"] == "citiz") & off["lon"].between(w, e_)
                                      & off["lat"].between(s_, n_)).sum())
                with st.container(border=True):
                    st.markdown("##### Pour Citiz")
                    if len(cz) == 0:
                        st.write("Aucune station Citiz retenue avec ces paramètres (essayez de cocher seulement "
                                 "« Station Citiz » ou d'augmenter le budget).")
                    else:
                        a, b = st.columns(2)
                        a.metric("Nouvelles stations", len(cz), f"{existing_citiz} existantes à proximité",
                                 delta_color="off")
                        b.metric("Conducteurs potentiels", fmt(cz["usage_pred"].sum()))
                        a.metric("Habitants à 5 min", fmt(cz["pop_newly_served"].sum()))
                        b.metric("Investissement", f"{cz['cost_eur'].sum() / 1e6:.2f} M€")
                        st.caption(f"Conducteurs = habitants nouvellement desservis × taux d'adhésion national "
                                   f"Citiz observé autour des stations existantes × valeur du site, plafonné à "
                                   f"{C.CITIZ_DRIVERS_FR / C.CITIZ_CARS_FR:.0f} adhérents par véhicule "
                                   f"({C.CITIZ_DRIVERS_FR:,} conducteurs / {C.CITIZ_CARS_FR:,} voitures). "
                                   f"Top 3 : " + ", ".join(cz["commune"].head(3)) + ".")
            with st.expander("Hypothèses de ce calcul"):
                st.json(summ.get("hypotheses", {}), expanded=False)
                st.caption(f"Temps de calcul : {summ.get('runtime_s')}")

# =========================================================================== 4. méthode
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
        "- **Offre ≠ service** : un arrêt compte même si la fréquence est faible (GTFS non pondéré par les horaires).\n"
        "- **Distance de marche** : rayon euclidien corrigé par un détour calibré sur Strasbourg, "
        "appliqué partout (plus fort en zone peu maillée).\n"
        "- **Modèle positive-unlabeled** : il apprend où les opérateurs se sont déjà implantés ; il reproduit "
        "donc en partie leurs choix passés. Le terme d'équité λ et la stratégie naïve servent de garde-fous.\n"
        "- **Données GBFS** incomplètes (certains opérateurs ne publient pas), free-floating = zones virtuelles.\n"
        "- **Impact CO₂** : ordres de grandeur sous hypothèses explicites, pas une mesure.\n"
        "- **Coûts** : retours d'expérience publics, à ajuster par l'opérateur ou la collectivité.\n"
        f"- **Confidentialité** : agrégats < {C.PRIVACY_MIN_HOUSEHOLDS} ménages lissés ou masqués ; vocabulaire "
        "centré sur l'offre (« offre à développer ») pour ne pas stigmatiser un territoire.")
