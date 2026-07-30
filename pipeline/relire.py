#!/usr/bin/env python3
"""
Outils de relecture du texte reconnu.

La reconnaissance optique produit toujours un résidu d'erreurs. Sur un corpus
juridique, celles qui comptent portent sur les nombres, les dates, les numéros
d'article et les renvois — précisément les éléments qu'une lecture rapide ne
détecte pas.

Ce module sert à deux choses :

  extraire   rend en image les pages à vérifier, afin de comparer visuellement
             le texte reconnu au document d'origine ;

  suspects   signale automatiquement les passages statistiquement douteux
             (nombres mal formés, mots inconnus, ponctuation aberrante) pour
             concentrer la relecture là où elle est utile ;

  appliquer  réinjecte les corrections validées dans les sorties OCR, de façon
             idempotente et traçable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# PyMuPDF et Pillow ne servent qu'au rendu des pages en image. Les importer au
# chargement du module ferait échouer « appliquer » et « suspects » là où ces
# bibliothèques ne sont pas installées — typiquement l'intégration continue, qui
# reconstruit le site sans jamais ouvrir un PDF. L'import est donc différé.


# --------------------------------------------------------------------------
#  Extraction d'images de contrôle
# --------------------------------------------------------------------------

def extraire(pdf: Path, pages: list[int], sortie: Path, dpi: int = 190,
             bandes: int = 1) -> list[Path]:
    """Rend les pages demandées en PNG lisibles.

    `bandes` découpe la page en tranches horizontales : utile pour relire un
    texte dense sans perdre en résolution.
    """
    try:
        import fitz
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Le rendu des pages exige PyMuPDF et Pillow : "
            "pip install pymupdf pillow"
        ) from exc

    sortie.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    produits: list[Path] = []

    for n in pages:
        if not 1 <= n <= len(doc):
            print(f"  page {n} hors limites (document de {len(doc)} pages)")
            continue
        pix = doc[n - 1].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        if bandes <= 1:
            chemin = sortie / f"{pdf.stem}_p{n:03d}.png"
            img.save(chemin, "PNG", optimize=True)
            produits.append(chemin)
        else:
            h = img.height // bandes
            for b in range(bandes):
                haut = b * h
                bas = img.height if b == bandes - 1 else (b + 1) * h
                chemin = sortie / f"{pdf.stem}_p{n:03d}_{b + 1}.png"
                img.crop((0, haut, img.width, bas)).save(chemin, "PNG", optimize=True)
                produits.append(chemin)

    doc.close()
    for p in produits:
        print(f"  {p}  ({p.stat().st_size // 1024} ko)")
    return produits


# --------------------------------------------------------------------------
#  Détection de passages douteux
# --------------------------------------------------------------------------

# Motifs typiques d'erreurs OCR sur des textes réglementaires français.
SUSPECTS = [
    (re.compile(r"\d[a-zA-Z]\d"), "chiffre-lettre-chiffre"),
    (re.compile(r"[a-zA-Z]\d{3,}"), "lettre collée à un nombre"),
    (re.compile(r"\b[Il1]{2,}\b"), "confusion I/l/1"),
    (re.compile(r"\b0[a-zA-Z]|\b[a-zA-Z]0\b"), "confusion O/0"),
    (re.compile(r"\s[,;:]\s"), "ponctuation isolée"),
    (re.compile(r"[«»\"]\s*$", re.M), "guillemet non fermé"),
    (re.compile(r"\b\d{1,3}\s\d{3}\s\d{3}\s\d{3}\b"), "nombre à vérifier"),
    (re.compile(r"[^\s\w.,;:()\[\]«»’'\-–—/%°§\"!?&+=…]"), "caractère inattendu"),
    (re.compile(r"\bartlcle|\barticie|\bartide", re.I), "« article » mal lu"),
    (re.compile(r"\brnillion|\brnontant|\brnarché", re.I), "« rn » pour « m »"),
]

CHIFFRES = re.compile(r"\d[\d\s]{2,}")


def suspects(json_ocr: Path, seuil_conf: float = 82.0) -> None:
    """Affiche les passages à vérifier en priorité dans un document."""
    d = json.loads(json_ocr.read_text(encoding="utf-8"))
    print(f"\n{'=' * 74}\n{json_ocr.stem}   "
          f"{d.get('pages')} pages, mode {d.get('mode')}, "
          f"confiance {d.get('confiance_moyenne')}\n{'=' * 74}")

    total = Counter()
    for page in d.get("detail", []):
        n, texte = page.get("numero"), page.get("texte", "")
        conf = page.get("confiance", 100)
        alertes: list[tuple[str, str]] = []

        for motif, etiquette in SUSPECTS:
            for m in motif.finditer(texte):
                debut = max(0, m.start() - 45)
                extrait = texte[debut:m.end() + 45].replace("\n", " ")
                alertes.append((etiquette, extrait.strip()))
                total[etiquette] += 1

        if conf < seuil_conf:
            print(f"\n-- page {n} : confiance faible ({conf}) — relecture "
                  f"intégrale recommandée")
        if alertes:
            print(f"\n-- page {n} ({conf}) : {len(alertes)} signalement(s)")
            for etiquette, extrait in alertes[:14]:
                print(f"     [{etiquette}] …{extrait}…")
            if len(alertes) > 14:
                print(f"     … et {len(alertes) - 14} autre(s)")

        # Tout montant chiffré mérite une vérification manuelle.
        montants = [m.group(0).strip() for m in CHIFFRES.finditer(texte)
                    if len(m.group(0).strip()) >= 7]
        if montants:
            print(f"     montants à confronter au PDF : "
                  f"{', '.join(sorted(set(montants))[:8])}")

    if total:
        print(f"\nrécapitulatif : "
              + ", ".join(f"{k} × {v}" for k, v in total.most_common()))
    else:
        print("\naucun signalement automatique")


# --------------------------------------------------------------------------
#  Application des corrections
# --------------------------------------------------------------------------

def appliquer(fichier_corrections: Path, dossier_texte: Path) -> None:
    """Réinjecte les corrections validées dans les sorties OCR.

    Format attendu :

      {
        "instruction_1000065": [
          {"page": 2, "avant": "1 600 000 000", "apres": "1 500 000 000"},
          {"page": 3, "remplacer_page": "texte intégral corrigé de la page"}
        ]
      }

    L'opération est idempotente : une correction déjà appliquée est ignorée.
    """
    corrections = json.loads(fichier_corrections.read_text(encoding="utf-8"))
    appliquees = ignorees = manquantes = 0

    for ident, regles in corrections.items():
        # Les clés préfixées d'un souligné portent des commentaires de
        # documentation, pas des règles.
        if ident.startswith("_") or not isinstance(regles, list):
            continue

        cible = dossier_texte / f"{ident}.json"
        if not cible.exists():
            print(f"  document absent : {ident}")
            manquantes += len(regles)
            continue

        d = json.loads(cible.read_text(encoding="utf-8"))
        pages = {p.get("numero"): p for p in d.get("detail", [])}
        modifie = False

        for r in regles:
            if not isinstance(r, dict):
                continue
            page = pages.get(r.get("page"))
            if page is None:
                print(f"  {ident} : page {r.get('page')} introuvable")
                manquantes += 1
                continue

            if "remplacer_page" in r:
                if page["texte"] != r["remplacer_page"]:
                    page["texte"] = r["remplacer_page"]
                    page["caracteres"] = len(page["texte"])
                    page["mode"] = "relu"
                    modifie = True
                    appliquees += 1
                else:
                    ignorees += 1
                continue

            avant, apres = r.get("avant"), r.get("apres")
            if avant is None or apres is None:
                continue
            if avant in page["texte"]:
                page["texte"] = page["texte"].replace(avant, apres)
                page["caracteres"] = len(page["texte"])
                page["mode"] = "relu"
                modifie = True
                appliquees += 1
            elif apres in page["texte"]:
                ignorees += 1          # déjà corrigé
            else:
                print(f"  {ident} p{r['page']} : texte introuvable "
                      f"→ {avant[:60]!r}")
                manquantes += 1

        if modifie:
            d["relu"] = True
            d["caracteres"] = sum(p.get("caracteres", 0) for p in d["detail"])
            cible.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    print(f"\ncorrections appliquées : {appliquees}, "
          f"déjà en place : {ignorees}, non trouvées : {manquantes}")
    if manquantes:
        print("Les corrections non trouvées signalent souvent que le texte OCR a "
              "changé depuis la rédaction de la correction : régénérer puis relire.")


# --------------------------------------------------------------------------
#  CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Relecture du corpus AMF-UMOA")
    sous = ap.add_subparsers(dest="commande", required=True)

    a = sous.add_parser("extraire", help="rendre des pages en image")
    a.add_argument("pdf")
    a.add_argument("--pages", required=True, help="ex. 1,2,5-7")
    a.add_argument("--sortie", default="controle")
    a.add_argument("--dpi", type=int, default=190)
    a.add_argument("--bandes", type=int, default=1)

    b = sous.add_parser("suspects", help="signaler les passages douteux")
    b.add_argument("json", nargs="+")
    b.add_argument("--seuil", type=float, default=82.0)

    c = sous.add_parser("appliquer", help="réinjecter des corrections validées")
    c.add_argument("corrections")
    c.add_argument("--texte", default="texte")

    args = ap.parse_args()

    if args.commande == "extraire":
        pages: list[int] = []
        for morceau in args.pages.split(","):
            morceau = morceau.strip()
            if "-" in morceau:
                d, f = (int(x) for x in morceau.split("-"))
                pages.extend(range(d, f + 1))
            elif morceau:
                pages.append(int(morceau))
        extraire(Path(args.pdf), pages, Path(args.sortie), args.dpi, args.bandes)

    elif args.commande == "suspects":
        for chemin in args.json:
            p = Path(chemin)
            for f in (sorted(p.glob("*.json")) if p.is_dir() else [p]):
                suspects(f, args.seuil)

    else:
        appliquer(Path(args.corrections), Path(args.texte))

    return 0


if __name__ == "__main__":
    sys.exit(main())
