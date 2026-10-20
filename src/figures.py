"""
Figures dédiées à la présentation (slides/presentation.html).

Lit uniquement des sorties existantes (aucun recalcul) :
    outputs/access_summary.json            -> part sans option par décile de revenu, part desservie par mode
    outputs/recommendations_summary.json   -> stratégie recommandée vs alternatives (même budget Citiz)
    outputs/territories_citiz.csv          -> classement national des territoires pour Citiz

Sorties : outputs/figures/slides_deciles.png, slides_modes.png, slides_strategies.png,
          slides_territories.png, slides_map_france.png, slides_map_top.png (territoire prioritaire),
          slides_map_ems.png (témoin) ; lisent aussi cells_access.parquet, recommendations*.csv
Usage : python -m src.figures
"""
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Config as C  # noqa: E402

BG = "#fbfaf8"
INK = "#1f2328"
MUTED = "#6b7280"
GRID = "#e5e7eb"
BLUE = "#2b76d6"
ORANGE = "#e8743b"
GREY = "#b8c2cc"


def _style(ax):
    ax.set_facecolor(BG)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _fig(w=10, h=5):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    return fig, ax


def deciles(acc):
    d = acc["by_income_decile"]
    keys = sorted(d, key=int)
    vals = [100 * d[k]["share_no_option"] for k in keys]
    nat = 100 * acc["national"]["share_no_option"]
    fig, ax = _fig()
    colors = [ORANGE if v == max(vals) else BLUE for v in vals]
    bars = ax.bar(range(len(keys)), vals, color=colors, width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.8, f"{v:.0f} %", ha="center", color=INK, fontsize=10)
    ax.axhline(nat, color=MUTED, linestyle=":", linewidth=1)
    ax.text(len(keys) - 0.5, nat + 0.8, f"France : {nat:.0f} %", ha="right", color=MUTED, fontsize=9)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels([f"D{k}" for k in keys], color=INK)
    ax.set_xlabel("décile de revenu par habitant du carreau (D1 = 10 % les plus modestes)", color=MUTED)
    ax.set_ylabel("% d'habitants sans aucune option à 5 min", color=MUTED)
    ax.set_ylim(0, max(vals) * 1.18)
    ax.set_title("Qui est concerné ? Surtout les déciles de revenu intermédiaires (courbe en U)",
                 loc="left", color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(C.FIG / "slides_deciles.png", facecolor=BG)
    plt.close(fig)


def modes(acc):
    sh = acc["national"]["share_served_by_mode"]
    order = sorted(sh, key=lambda m: sh[m])
    vals = [100 * sh[m] for m in order]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    colors = [ORANGE if m == "citiz" else BLUE for m in order]
    bars = ax.barh(range(len(order)), vals, color=colors, height=0.6)
    for b, v in zip(bars, vals):
        ax.text(v + 0.8, b.get_y() + b.get_height() / 2, f"{v:.1f} %".replace(".", ","), va="center", color=INK, fontsize=10)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([C.MODES[m] for m in order], color=INK)
    ax.set_xlabel("% de la population (France + Martinique + La Réunion) ayant ≥ 1 point du mode à 5 min",
                  color=MUTED)
    ax.set_xlim(0, max(vals) * 1.15)
    ax.set_title("Accès à 5 min de marche, par mode", loc="left", color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(C.FIG / "slides_modes.png", facecolor=BG)
    plt.close(fig)


def _num(v, dec=0):
    """Nombre au format français (virgule décimale, zéros inutiles retirés)."""
    t = f"{float(v):.{dec}f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t.replace(".", ",")


def _strategy(rec, exact, words):
    """Bloc de comparaison sous l'un des noms possibles (schéma évolutif), sinon None."""
    comp = rec.get("comparison") or {}
    for k in exact:
        if isinstance(comp.get(k), dict):
            return comp[k]
    for k, v in comp.items():
        if isinstance(v, dict) and all(w in k.lower() for w in words):
            return v
    return None


def strategies(full):
    """Stratégies comparées, volet Citiz d'un territoire (même budget Citiz)."""
    rec = (full.get("funders") or {}).get("citiz") or full
    sel = rec.get("selected") or {}
    lam = rec.get("equity_lambda", C.EQUITY_LAMBDA)
    rows = [
        (f"Recommandée\n(modèle, λ = {_num(lam, 1)},\nquota peu dense)", sel, True),
        ("Offre existante,\nsans modèle (v = 1)",
         _strategy(rec, ["existing_offer_no_model", "no_model_value_1", "no_model"], ["no_model"]), False),
        ("Sans pondération\nd'équité (λ = 0)",
         _strategy(rec, ["no_equity_weight", "lambda_0_no_equity", "no_equity", "lambda_0"], ["equity"]), False),
        ("Naïve\n(population seule)", _strategy(rec, ["naive_population_only"], ["naive"]), False),
    ]
    rows = [r for r in rows if r[1]]
    metrics = [
        ("pop_newly_served", "Habitants nouvellement\ndesservis", lambda v: f"{v:,.0f}".replace(",", " ")),
        ("co2_avoided_t_yr", "CO2 évité (t/an)", lambda v: f"{v:.0f}"),
        ("share_new_in_income_deciles_1_3", "Part des nouveaux desservis\ndans les déciles 1-3 (%)",
         lambda v: f"{v:.0f}"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(4.4 * max(len(rows), 3), 4.8), dpi=150)
    fig.patch.set_facecolor(BG)
    for ax, (key, title, fmt) in zip(axes, metrics):
        _style(ax)
        vals = [(r[1].get(key) or 0) * (100 if key.startswith("share") else 1) for r in rows]
        colors = [BLUE if r[2] else GREY for r in rows]
        bars = ax.bar(range(len(rows)), vals, color=colors, width=0.6)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.02, fmt(v), ha="center", va="bottom",
                    color=INK, fontsize=10)
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels([r[0] for r in rows], fontsize=8, color=INK)
        ax.set_ylim(0, max(max(vals), 1e-9) * 1.2)
        ax.set_yticks([])
        ax.set_title(title, color=INK, fontsize=11)
    budget = rec.get("budget_eur", C.DEFAULT_BUDGET) / 1e6
    fig.suptitle(f"{full.get('territoire', '')} – stations Citiz, même budget "
                 f"({_num(budget, 2)} M€ sur {C.HORIZON_YEARS} ans)",
                 x=0.01, ha="left", color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(C.FIG / "slides_strategies.png", facecolor=BG)
    plt.close(fig)


# Rampe froid -> chaud identique à l'application (src/app_data.RAMP) ; 0 option = gris neutre.
RAMP = [(49, 54, 149), (69, 117, 180), (116, 173, 209), (171, 217, 233), (254, 224, 144),
        (253, 174, 97), (244, 109, 67), (215, 48, 39), (165, 0, 38)]
ZERO = (120 / 255, 130 / 255, 150 / 255)


def _cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("froid_chaud", [tuple(c / 255 for c in r) for r in RAMP])


def map_france():
    """Carte métropole : score moyen pondéré par la population sur une grille de 2 km."""
    import pandas as pd
    ca = pd.read_parquet(C.OUT / "cells_access.parquet", columns=["crs_id", "x", "y", "ind", "score"])
    ca = ca[ca.crs_id == 0]
    g = 2000
    ca = ca.assign(gx=(ca.x // g).astype(int), gy=(ca.y // g).astype(int), ws=ca.score * ca.ind,
                   none=(ca.score <= 0) * ca.ind)
    a = ca.groupby(["gx", "gy"], as_index=False)[["ind", "ws", "none"]].sum()
    a["s"] = a.ws / a.ind
    a["zero"] = a.none / a.ind > 0.5           # majorité des habitants sans option
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    z = a[a.zero]
    ax.scatter(z.gx * g, z.gy * g, s=1.3, marker="s", color=ZERO, linewidths=0)
    nz = a[~a.zero].sort_values("s")
    sc = ax.scatter(nz.gx * g, nz.gy * g, c=nz.s, cmap=_cmap(), vmin=0, vmax=100, s=1.3, marker="s",
                    linewidths=0)
    ax.set_aspect("equal")
    ax.axis("off")
    cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("score d'accès 0-100 (froid -> chaud)", color=MUTED)
    cb.outline.set_visible(False)
    ax.set_title("Accès à la mobilité à 5 min de marche (carrés de 2 km ; gris = majorité sans option)",
                 loc="left", color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(C.FIG / "slides_map_france.png", facecolor=BG)
    plt.close(fig)


def territories():
    """Classement national : adhérents potentiels (modèle) et retenus après risque terrain (+ Strasbourg témoin)."""
    import pandas as pd
    t = pd.read_csv(C.OUT / "territories_citiz.csv")
    t = t[t["rank"].notna() | t["reference"]].copy()
    t = t.sort_values("sim_members_adjusted", ascending=True)
    col = {"nouveau territoire": ORANGE, "extension": BLUE}
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(t) + 1.4), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    colors = [GREY if r else col.get(s_, BLUE) for r, s_ in zip(t["reference"], t["statut"])]
    labels = [f"{n}{' (témoin)' if r else ''}" for n, r in zip(t["territoire"], t["reference"])]
    ax.barh(labels, t["sim_members_potential"], color=colors, alpha=0.25, height=0.6)
    bars = ax.barh(labels, t["sim_members_adjusted"], color=colors, height=0.6)
    for b, v, raw, rk in zip(bars, t["sim_members_adjusted"], t["sim_members_potential"], t["risk"]):
        note = f"  (modèle {raw:,.0f} · risque {100 * rk:+.0f} %)" if rk else ""
        ax.text(max(v, raw) * 1.01, b.get_y() + b.get_height() / 2,
                f"{v:,.0f} adhérents{note}".replace(",", " "), va="center", color=INK, fontsize=8)
    ax.set_xlim(0, t["sim_members_potential"].max() * 1.75)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelsize=9, colors=INK)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=ORANGE, label="Citiz absent (nouveau territoire)"),
                       Patch(color=BLUE, label="Citiz présent (extension)"),
                       Patch(color=GREY, label="Strasbourg, territoire témoin"),
                       Patch(color=GREY, alpha=0.25, label="potentiel du modèle avant risque terrain")],
              loc="lower right", frameon=False, fontsize=8)
    ax.set_title(f"Même budget Citiz ({_num(C.CITIZ_BUDGET / 1e6, 2)} M€ / {C.HORIZON_YEARS} ans) : "
                 "adhérents retenus après risque terrain", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(C.FIG / "slides_territories.png", facecolor=BG)
    plt.close(fig)


def map_area(csv, summary, out_name, communes):
    """Territoire : score au carreau 200 m + sites recommandés par type et par financeur."""
    import pandas as pd
    ca = pd.read_parquet(C.OUT / "cells_access.parquet", columns=["lon", "lat", "score", "com"],
                         filters=[("com", "in", list(communes))])
    rec = pd.read_csv(C.OUT / csv)
    # cadrage sur les sites recommandés (+ ~5 km) : l'arrière-pays peu peuplé écraserait la carte
    w, e = rec.lon.min() - 0.06, rec.lon.max() + 0.06
    s_, n = rec.lat.min() - 0.045, rec.lat.max() + 0.045
    ca = ca[ca.lon.between(w, e) & ca.lat.between(s_, n)]
    fig, ax = plt.subplots(figsize=(8, 7.2), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    z = ca[ca.score <= 0]
    ax.scatter(z.lon, z.lat, s=8, marker="s", color=ZERO, linewidths=0, alpha=0.8)
    nz = ca[ca.score > 0]
    ax.scatter(nz.lon, nz.lat, c=nz.score, cmap=_cmap(), vmin=0, vmax=100, s=8, marker="s",
               linewidths=0, alpha=0.8)
    styles = {"citiz": ("o", "#e8743b", "Station Citiz (Citiz)"),
              "bike": ("^", "#1a9e5c", "Station vélo (collectivité)"),
              "bus": ("s", "#5b3fb5", "Arrêt de bus (collectivité)")}
    for k, (m, col, lab) in styles.items():
        r = rec[rec.type == k]
        ax.scatter(r.lon, r.lat, marker=m, s=90, color=col, edgecolors="white", linewidths=1.5,
                   label=f"{lab} : {len(r)}", zorder=3)
    ax.set_aspect(1 / np.cos(np.radians(ca.lat.median())))
    ax.axis("off")
    ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor=GRID, fontsize=9)
    fu = summary.get("funders") or {}
    bc = (fu.get("citiz") or {}).get("budget_eur", C.CITIZ_BUDGET)
    bp = (fu.get("collectivite") or {}).get("budget_eur", C.PUBLIC_BUDGET)
    ax.set_title(f"{summary.get('territoire', '')} : budget Citiz {_num(bc / 1e6, 2)} M€ · "
                 f"collectivité {_num(bp / 1e6, 2)} M€", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(C.FIG / out_name, facecolor=BG)
    plt.close(fig)


def main():
    acc = json.loads((C.OUT / "access_summary.json").read_text())
    rec = json.loads((C.OUT / "recommendations_summary.json").read_text())
    deciles(acc)
    modes(acc)
    ems_f = C.OUT / "recommendations_summary_ems.json"
    # comparaison des stratégies sur le témoin : là où l'offre existe, l'ignorer coûte cher
    strategies(json.loads(ems_f.read_text()) if ems_f.exists() else rec)
    territories()
    map_france()
    from src import territories as T
    top = T.load_summary()["top"]["epci"]
    map_area("recommendations.csv", rec, "slides_map_top.png", T.epci_communes(top))
    if ems_f.exists():
        map_area("recommendations_ems.csv", json.loads(ems_f.read_text()), "slides_map_ems.png", C.EMS_COMMUNES)
    for n in ("slides_deciles", "slides_modes", "slides_strategies", "slides_territories", "slides_map_france",
              "slides_map_top", "slides_map_ems"):
        print("->", C.FIG / f"{n}.png")


if __name__ == "__main__":
    main()
