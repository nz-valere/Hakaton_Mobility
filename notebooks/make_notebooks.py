"""
Régénère les notebooks Fabric (notebooks/*.ipynb) depuis le code de src/ : même code, découpé en cellules.

Chaque notebook « lecture de src/<module>.py » contient : le titre, la docstring du module, la cellule
Fabric (si le notebook l'a déjà, ou pour les notebooks de NEW), la préparation (__file__, sys.argv),
puis « Imports et constantes », une cellule par fonction (titre + premier paragraphe de sa docstring)
et le bloc __main__. Le titre de chaque notebook existant est conservé. Les notebooks sans cellule
« # Préparation » (ex. 08_export_fabric) ne sont pas touchés.

Usage : python notebooks/make_notebooks.py [--check]   (--check : n'écrit rien, code 1 si un notebook est périmé)
"""
import ast
import glob
import json
import re
import sys
from pathlib import Path

NB = Path(__file__).resolve().parent
NL = "\n"
FABRIC_CELL = (
    "# Fabric : à exécuter en premier. En local (hors Fabric), cette cellule ne fait rien.\n"
    "import os\n"
    "import subprocess\n"
    "import sys\n"
    "\n"
    "FABRIC_PROJECT = \"/lakehouse/default/Files/mobiliscore\"  # dossier du projet uploadé dans le Lakehouse\n"
    "if os.path.isdir(\"/lakehouse/default\"):\n"
    "    os.chdir(os.path.join(FABRIC_PROJECT, \"notebooks\"))\n"
    "    subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-q\", \"pyproj\", \"openpyxl\"], check=True)"
)
# notebooks ajoutés après l'import dans Fabric : module, titre, options, texte d'introduction
NEW = {
    "04b_frequency": dict(
        module="frequency.py", title="# Étape 4b – Fréquence des lignes",
        intro="À lancer après `04_accessibility` (lit `outputs/cells_access.parquet`) et avant `06b_recommend`, "
              "qui pondère l'offre de bus, tram et métro par ces fréquences. Les GTFS des réseaux sont téléchargés "
              "par l'étape `frequency` de `01_download`."),
    "05c_collect_gbfs": dict(
        module="collect_gbfs.py", title="# Étape 5c – Collecte de l'usage réel (GBFS Citiz)", argv=["--once"],
        comment="un seul relevé, comme `python -m src.collect_gbfs --once` (notebook à planifier toutes les 5 min)",
        intro="**Un relevé par exécution.** Dans Fabric, planifier ce notebook toutes les 5 minutes "
              "(*Exécuter* → *Planifier*) : chaque exécution ajoute un relevé des 17 réseaux Citiz dans `data/gbfs/` "
              "du Lakehouse, et la collecte ne dépend plus d'un PC allumé. Plus il y a de relevés, plus `05c_usage` "
              "est fiable (le résumé publie le nombre de relevés obtenus). Non testé dans Fabric : vérifier après "
              "quelques exécutions que `data/gbfs/citiz_status_<jour>.csv` grossit."),
    "05c_usage": dict(
        module="usage.py", title="# Étape 5c – Usage réel des stations Citiz",
        intro="À lancer après `05_model` (propension hors pli du modèle Citiz) et une fois des relevés collectés "
              "par `05c_collect_gbfs` (une station n'est retenue qu'avec au moins `C.USAGE_MIN_SNAPSHOTS` relevés, "
              "soit 1 h de collecte)."),
}


def _lines(text):
    ls = text.split(NL)
    return [line + NL for line in ls[:-1]] + ([ls[-1]] if ls[-1] else [])


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(text)}


def _is_fabric(cell):
    return cell["cell_type"] == "code" and "".join(cell["source"]).startswith("# Fabric : à exécuter en premier")


def _is_main_guard(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


def _segments(src_text):
    """Noeuds de premier niveau et leurs lignes [début, fin) ; les commentaires qui précèdent un noeud lui sont rattachés."""
    tree = ast.parse(src_text)
    body, prev_end = tree.body, 0
    if ast.get_docstring(tree) is not None:
        prev_end, body = body[0].end_lineno, body[1:]
    lines = src_text.split(NL)
    out = []
    for node in body:
        a = prev_end
        while a < node.end_lineno and not lines[a].strip():
            a += 1
        out.append((node, a, node.end_lineno))
        prev_end = node.end_lineno
    return tree, lines, out


def _text(lines, a, b):
    seg = lines[a:b]
    while seg and not seg[-1].strip():
        seg = seg[:-1]
    return NL.join(seg)


def build(name, module, title, argv=(), comment=None, intro=None, fabric_cell=None):
    """Texte JSON du notebook `name` pour src/<module>."""
    src_text = (NB.parent / "src" / module).read_text(encoding="utf-8")
    tree, lines, segs = _segments(src_text)
    label = f"src.{Path(module).stem}"
    cells = [md(f"{title}{NL}{NL}Notebook de lecture de `src/{module}` : même code, découpé en cellules. "
                f"Exécuter les cellules dans l'ordre équivaut à `python -m {label}{''.join(' ' + a for a in argv)}`."
                + (f"{NL}{NL}{intro}" if intro else ""))]
    doc = ast.get_docstring(tree)
    if doc:
        cells.append(md(doc))
    if fabric_cell is not None:
        cells.append(fabric_cell)
    argv_txt = "[" + ", ".join(json.dumps(a, ensure_ascii=False) for a in [label, *argv]) + "]"
    cells.append(code(
        f"# Préparation : ce notebook exécute le code de src/{module} tel quel, depuis la racine du projet.{NL}"
        f"import ast{NL}import sys{NL}from pathlib import Path{NL}{NL}"
        f"ROOT = Path.cwd().resolve(){NL}"
        f"if not (ROOT / \"Config.py\").exists():{NL}"
        f"    ROOT = ROOT.parent{NL}"
        f"__file__ = str(ROOT / \"src\" / \"{module}\"){NL}"
        f"__doc__ = ast.get_docstring(ast.parse(Path(__file__).read_text(encoding=\"utf-8\"))){NL}"
        f"sys.argv = {argv_txt}  # {comment or f'options par défaut, comme `python -m {label}`'}"))
    group, first = None, True                      # group : lignes [début, fin) d'instructions hors fonctions
    for node, a, b in segs + [(None, 0, 0)]:
        if node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and not _is_main_guard(node):
            group = (group[0], b) if group else (a, b)
            continue
        if group:
            if first:
                cells.append(md("## Imports et constantes"))
            cells.append(code(_text(lines, *group)))
            group = None
        first = False
        if node is None:
            break
        if _is_main_guard(node):
            cells.append(md(f"## Exécution{NL}{NL}Bloc `__main__` du module, inchangé."))
        else:
            d = ast.get_docstring(node)            # premier paragraphe, lignes mises bout à bout
            cells.append(md(f"### Fonction `{node.name}`"
                            + (NL + NL + " ".join(re.split(r"\n\s*\n", d)[0].split(NL)) if d else "")))
        cells.append(code(_text(lines, a, b)))
    k = 0
    for c in cells:
        if c is fabric_cell:                       # cellule existante gardée telle quelle
            if c.pop("_new", False):
                c["id"] = f"{name}-fabric"
            continue
        c["id"] = f"{name}-{k:03d}"
        k += 1
    nb = {"cells": cells,
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python", "version": "3.9"}},
          "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(nb, indent=1, ensure_ascii=False) + NL


def targets():
    """(nom, paramètres de build) : notebooks existants (titre et cellule Fabric conservés) + NEW."""
    out = {}
    for f in sorted(glob.glob(str(NB / "*.ipynb"))):
        name = Path(f).stem
        cells = json.loads(Path(f).read_text(encoding="utf-8"))["cells"]
        prep = next(("".join(c["source"]) for c in cells if "".join(c["source"]).startswith("# Préparation")), None)
        if prep is None:
            continue                               # notebook écrit à la main (ex. export Fabric)
        fab = next((c for c in cells if _is_fabric(c)), None)
        module = prep.split('ROOT / "src" / "')[1].split('"')[0]
        out[name] = dict(NEW.get(name, {}), module=module, title=cells[0]["source"][0].rstrip(NL), fabric_cell=fab)
    for name, p in NEW.items():
        if name not in out:
            out[name] = dict(p, fabric_cell=None)
    for name, p in out.items():
        if name in NEW and p["fabric_cell"] is None:
            p["fabric_cell"] = dict(code(FABRIC_CELL), _new=True)
    return out


def main():
    check = "--check" in sys.argv
    stale = []
    for name, p in targets().items():
        path = NB / f"{name}.ipynb"
        text = build(name, **p)
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            continue
        stale.append(name)
        if not check:
            path.write_text(text, encoding="utf-8", newline=NL)
        print(f"{'périmé' if check else ('créé' if old is None else 'mis à jour'):10s} notebooks/{name}.ipynb")
    print(f"{len(stale)} notebook(s) {'périmé(s)' if check else 'écrit(s)'}")
    if check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
