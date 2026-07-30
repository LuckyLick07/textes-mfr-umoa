#!/usr/bin/env python3
"""
Validation du pipeline OCR sur un scan synthétique.

On fabrique un PDF image-seule imitant un texte réglementaire de l'AMF-UMOA
(accents, numéros d'articles, montants, énumérations), on y ajoute les défauts
typiques d'une numérisation — inclinaison, bruit, contraste imparfait — puis on
mesure l'écart entre le texte reconnu et la vérité terrain.
"""

import difflib
import subprocess
import sys
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from ocr_pipeline import traiter_document  # noqa: E402

VERITE = """INSTRUCTION N° 65/CREPMF/2021

RELATIVE AU CAPITAL SOCIAL MINIMUM REQUIS ET AUX NORMES PRUDENTIELLES
DES SOCIETES DE GESTION ET D'INTERMEDIATION AGREEES SUR LE MARCHE
FINANCIER REGIONAL DE L'UMOA

Article premier : Objet

La présente Instruction a pour objet de préciser les modalités d'application
des dispositions de l'article 37 du Règlement Général relatif à
l'organisation, au fonctionnement et au contrôle du Marché Financier
Régional de l'UMOA.

Article 2 : Champ d'application

Elle s'applique aux Sociétés de Gestion et d'Intermédiation agréées par
l'Autorité des Marchés Financiers de l'UMOA, ci-après dénommées les SGI.

Article 3 : Capital social minimum

Le capital social minimum des SGI est fixé à un milliard cinq cents millions
(1 500 000 000) de francs CFA, intégralement libéré à la date de l'agrément.

Les fonds propres effectifs ne peuvent à aucun moment devenir inférieurs au
montant du capital social minimum exigé.

Article 4 : Normes prudentielles

Les SGI sont tenues de respecter en permanence les ratios suivants :

- un ratio de couverture des risques au moins égal à 8 % ;
- un ratio de liquidité au moins égal à 60 % ;
- un coefficient de fonds propres et de ressources stables de 50 % au moins.

Article 5 : Entrée en vigueur

La présente Instruction entre en vigueur à compter du 1er janvier 2022 et
abroge toutes dispositions antérieures contraires.

Fait à Abidjan, le 15 décembre 2021"""


def _police(taille: int) -> ImageFont.FreeTypeFont:
    pistes = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ]
    for p in pistes:
        if Path(p).exists():
            return ImageFont.truetype(p, taille)
    raise SystemExit("Aucune police TrueType trouvée")


def fabriquer_scan(dest: Path) -> None:
    """Rend la vérité terrain en image dégradée, puis l'encapsule en PDF."""
    L, H = 2480, 3508          # A4 à 300 dpi
    img = Image.new("L", (L, H), 255)
    d = ImageDraw.Draw(img)
    police = _police(38)

    y = 240
    for ligne in VERITE.split("\n"):
        d.text((230, y), ligne, font=police, fill=25)
        y += 62

    # Défauts de numérisation : inclinaison, bruit de capteur, fond grisé.
    img = img.rotate(-0.8, resample=Image.BICUBIC, fillcolor=255, expand=False)
    a = np.asarray(img, dtype=np.float32)
    rng = np.random.default_rng(7)
    a += rng.normal(0, 9, a.shape)              # bruit gaussien
    a = a * 0.93 + 12                           # contraste réduit, fond gris
    img = Image.fromarray(np.uint8(np.clip(a, 0, 255)))

    tmp = dest.with_suffix(".png")
    img.save(tmp, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(tmp))
    doc.save(dest)
    doc.close()
    tmp.unlink()


def normaliser(t: str) -> str:
    return " ".join(t.split())


def main() -> int:
    dest = Path("/tmp/scan_test.pdf")
    fabriquer_scan(dest)

    # Vérifie que le PDF est bien dépourvu de couche texte.
    doc = fitz.open(dest)
    couche = sum(len(doc[i].get_text().strip()) for i in range(len(doc)))
    doc.close()
    print(f"PDF de test : {dest.stat().st_size // 1024} ko, "
          f"couche texte = {couche} caractères (0 attendu)\n")

    res = traiter_document(dest)
    obtenu = res.detail[0]["texte"]

    a, b = normaliser(VERITE), normaliser(obtenu)
    ratio_car = difflib.SequenceMatcher(None, a, b).ratio()

    ma, mb = a.split(), b.split()
    justes = sum(bloc.size for bloc in
                 difflib.SequenceMatcher(None, ma, mb).get_matching_blocks())
    ratio_mot = justes / len(ma)

    print(f"mode                  : {res.mode}")
    print(f"confiance Tesseract   : {res.confiance_moyenne:.1f} %")
    print(f"exactitude caractères : {ratio_car * 100:.2f} %")
    print(f"exactitude mots       : {ratio_mot * 100:.2f} %")
    print(f"mots attendus / lus   : {len(ma)} / {len(mb)}")

    print("\n--- différences mot à mot ---")
    ecarts = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ma, mb).get_opcodes():
        if tag != "equal":
            ecarts += 1
            if ecarts <= 12:
                print(f"  {tag:9s} attendu={' '.join(ma[i1:i2])!r:42s} "
                      f"lu={' '.join(mb[j1:j2])!r}")
    if ecarts == 0:
        print("  aucune")
    elif ecarts > 12:
        print(f"  ... et {ecarts - 12} autre(s)")

    print("\n--- contrôles ciblés (éléments juridiquement sensibles) ---")
    cibles = ["1 500 000 000", "8 %", "60 %", "50 %", "article 37",
              "1er janvier 2022", "15 décembre 2021", "N° 65/CREPMF/2021"]
    ok = 0
    for c in cibles:
        present = c.lower() in b.lower()
        ok += present
        print(f"  {'OK  ' if present else 'RATE'} {c}")
    print(f"\n  {ok}/{len(cibles)} éléments sensibles correctement restitués")

    return 0 if ratio_car > 0.95 else 1


if __name__ == "__main__":
    sys.exit(main())
