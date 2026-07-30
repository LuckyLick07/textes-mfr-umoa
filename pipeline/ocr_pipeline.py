#!/usr/bin/env python3
"""
Pipeline OCR pour le corpus AMF-UMOA.

Décide page par page entre extraction directe (PDF avec couche texte)
et reconnaissance optique (pages scannées), applique un redressement
géométrique avant OCR et rend un JSON structuré assorti d'un indice de
confiance permettant de cibler la relecture humaine.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageOps

TESSDATA = os.environ.get("TESSDATA_PREFIX", str(Path.home() / "tessdata"))
LANG = "fra"

# Une page dont la couche texte dépasse ce seuil est réputée native.
SEUIL_TEXTE_NATIF = 120
# En dessous de cette confiance moyenne, on retente à plus haute résolution.
SEUIL_RETENTE = 78.0
# Aucun mot n'est jamais écarté : Tesseract attribue une confiance basse aux
# mots portant une apostrophe typographique — « d'application », « l'UMOA » —
# et les filtrer revient à amputer le texte réglementaire sans trace. Seules
# des lignes entièrement décoratives sont supprimées, sous double condition.
SEUIL_LIGNE_BRUIT = 75.0


# --------------------------------------------------------------------------
#  Prétraitement image
# --------------------------------------------------------------------------

def _angle_de_biais(img: Image.Image, amplitude: float = 5.0, pas: float = 0.25) -> float:
    """Estime l'inclinaison par maximisation de la variance du profil de projection.

    Sur un document redressé, les lignes de texte produisent des creux et des
    pics nets dans la somme des pixels par rangée. L'angle qui maximise la
    variance de ce profil est donc celui qui aligne le mieux les lignes.
    """
    petite = img.convert("L")
    petite.thumbnail((800, 800))
    a = np.asarray(petite, dtype=np.float32)
    a = 255.0 - a                      # encre en valeurs hautes
    a[a < 96] = 0.0                    # coupe le fond gris du scan

    meilleur_angle, meilleur_score = 0.0, -1.0
    n = int(amplitude / pas)
    for i in range(-n, n + 1):
        angle = i * pas
        if angle:
            src = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
            pivot = np.asarray(
                src.rotate(angle, resample=Image.BILINEAR, fillcolor=0),
                dtype=np.float32,
            )
        else:
            pivot = a
        profil = pivot.sum(axis=1)
        score = float(np.var(profil))
        if score > meilleur_score:
            meilleur_score, meilleur_angle = score, angle
    return meilleur_angle


def _preparer(img: Image.Image) -> Image.Image:
    """Niveaux de gris, étirement de dynamique et redressement si nécessaire.

    L'étirement se fait sans écrêtage de percentile. Un écrêtage même faible
    — 1 % de chaque extrémité de l'histogramme — efface le texte des pages peu
    encrées : sur une page de titre, l'encre couvre moins de 1 % des pixels et
    se retrouve donc entièrement rejetée du côté clair. Mesuré sur le corpus,
    l'écrêtage n'améliore par ailleurs jamais la reconnaissance.
    """
    img = img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=0)
    angle = _angle_de_biais(img)
    if abs(angle) >= 0.3:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255, expand=True)
    return img


# --------------------------------------------------------------------------
#  OCR
# --------------------------------------------------------------------------

def _bruit_decoratif(mots: list[str]) -> bool:
    """Reconnaît un filet décoratif ou un fragment de logo plutôt qu'une phrase.

    Les séparateurs d'astérisques et les logotypes stylisés se lisent comme une
    accumulation de très courts fragments sans aucun mot substantiel.
    """
    if len(mots) < 4:
        return False
    return not any(len(re.sub(r"[^A-Za-zÀ-ÿ]", "", m)) >= 4 for m in mots)


def _orientation(img: Image.Image) -> int:
    """Détecte la rotation à appliquer pour redresser la page, en degrés.

    Certaines pages du corpus ont été numérisées à l'envers : le texte reconnu
    ressort alors en miroir et parfaitement inutilisable. Le mode d'analyse
    d'orientation de Tesseract identifie ces cas pour quelques dixièmes de
    seconde, bien avant qu'on envisage une reconnaissance complète.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "orient.png"
        petite = img.copy()
        petite.thumbnail((1200, 1200))
        petite.save(src, "PNG")
        try:
            res = subprocess.run(
                ["tesseract", str(src), "-", "--psm", "0",
                 "--tessdata-dir", TESSDATA],
                capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return 0
    if m := re.search(r"Rotate:\s*(\d+)", res.stdout):
        return int(m.group(1)) % 360
    return 0


def _tesseract(img: Image.Image, psm: int = 3) -> tuple[str, float]:
    """Lance Tesseract et reconstruit le texte à partir de la sortie TSV.

    Passer par le TSV plutôt que par la sortie texte apporte deux bénéfices :
    une seule invocation de Tesseract au lieu de deux, et surtout l'accès à la
    confiance de chaque mot, qui permet d'écarter le bruit sans toucher au corps
    du texte.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.png"
        img.save(src, "PNG")
        base = Path(tmp) / "sortie"

        subprocess.run(
            ["tesseract", str(src), str(base),
             "-l", LANG, "--oem", "1", "--psm", str(psm),
             "--tessdata-dir", TESSDATA,
             "-c", "preserve_interword_spaces=1", "tsv"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        brut = base.with_suffix(".tsv").read_text(encoding="utf-8",
                                                  errors="replace")

    # Regroupement des mots par ligne, dans l'ordre de lecture.
    lignes: dict[tuple[int, int, int], list[tuple[float, str]]] = {}
    ordre: list[tuple[int, int, int]] = []
    for enr in brut.splitlines()[1:]:
        ch = enr.split("\t")
        if len(ch) < 12 or ch[0] != "5":
            continue
        mot = ch[11].strip()
        if not mot:
            continue
        try:
            cle = (int(ch[2]), int(ch[3]), int(ch[4]))
            conf = float(ch[10])
        except ValueError:
            continue
        if cle not in lignes:
            lignes[cle] = []
            ordre.append(cle)
        lignes[cle].append((conf, mot))

    sortie: list[str] = []
    confs: list[float] = []
    paragraphe_precedent: tuple[int, int] | None = None

    for cle in ordre:
        mots = lignes[cle]
        moyenne = sum(c for c, _ in mots) / len(mots)

        # Filet d'astérisques, logotype stylisé : uniquement lorsque la ligne
        # n'a aucun mot substantiel ET que Tesseract lui-même doute.
        if moyenne < SEUIL_LIGNE_BRUIT and _bruit_decoratif([m for _, m in mots]):
            continue

        paragraphe = cle[:2]
        if paragraphe_precedent is not None and paragraphe != paragraphe_precedent:
            sortie.append("")
        paragraphe_precedent = paragraphe

        sortie.append(" ".join(m for _, m in mots))
        confs.extend(c for c, _ in mots)

    return "\n".join(sortie), (sum(confs) / len(confs) if confs else 0.0)


# --------------------------------------------------------------------------
#  Nettoyage typographique
# --------------------------------------------------------------------------

# Césure de fin de ligne : un mot coupé se recolle sans tiret, mais un sigle
# composé comme « AMF-UMOA » doit conserver le sien.
_CESURE_MOT = re.compile(r"([a-zà-öø-ÿ])[-­]\n([a-zà-öø-ÿ])")
_CESURE_SIGLE = re.compile(r"([A-ZÀ-Ö0-9])-\n([A-ZÀ-Ö])")
_ESPACES = re.compile(r"[ \t]{2,}")
_LIGNES_VIDES = re.compile(r"\n{3,}")
# Un exposant « er » mal reconnu ressort en guillemet après le chiffre.
_ORDINAL = re.compile(r"\b1\s*[“”″]")
# Le « I » romain en début de titre est souvent lu comme une barre verticale.
_ROMAIN = re.compile(r"^\|(\s*[-–—.)])", re.M)


def nettoyer(texte: str) -> str:
    """Recolle les césures, normalise espaces, apostrophes et artefacts connus."""
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    texte = _CESURE_SIGLE.sub(r"\1-\2", texte)
    texte = _CESURE_MOT.sub(r"\1\2", texte)
    texte = _ORDINAL.sub("1er", texte)
    texte = _ROMAIN.sub(r"I\1", texte)
    texte = _ESPACES.sub(" ", texte)
    texte = _LIGNES_VIDES.sub("\n\n", texte)
    # Guillemets et apostrophes typographiques françaises
    texte = texte.replace("''", '"').replace("``", '"')
    texte = re.sub(r"(?<=\w)'(?=\w)", "’", texte)
    return "\n".join(l.rstrip() for l in texte.split("\n")).strip()


# --------------------------------------------------------------------------
#  Traitement d'un document
# --------------------------------------------------------------------------

@dataclass
class Page:
    numero: int
    mode: str          # "natif" ou "ocr"
    confiance: float
    caracteres: int
    texte: str


@dataclass
class Document:
    fichier: str
    pages: int
    mode: str
    confiance_moyenne: float
    caracteres: int
    pages_faibles: list[int] = field(default_factory=list)
    detail: list[dict] = field(default_factory=list)


def traiter_page(doc: fitz.Document, index: int, dpi: int) -> Page:
    page = doc[index]

    natif = page.get_text().strip()
    if len(natif) >= SEUIL_TEXTE_NATIF:
        propre = nettoyer(natif)
        return Page(index + 1, "natif", 100.0, len(propre), propre)

    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = _preparer(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    texte, conf = _tesseract(img)

    # Page numérisée de travers ou à l'envers : on redresse et on recommence.
    if conf < SEUIL_RETENTE:
        candidats = []
        rot = _orientation(img)
        if rot:
            candidats.append(rot)
        if 180 not in candidats:
            candidats.append(180)      # l'erreur de numérisation la plus courante
        for angle in candidats:
            pivote = img.rotate(-angle, expand=True, fillcolor=255)
            t_alt, c_alt = _tesseract(pivote)
            if c_alt > conf + 3:       # marge pour éviter les faux positifs
                texte, conf, img = t_alt, c_alt, pivote
                break

    # Seconde tentative à plus haute résolution si le résultat reste douteux.
    if conf < SEUIL_RETENTE and dpi < 400:
        pix2 = page.get_pixmap(dpi=400, colorspace=fitz.csGRAY)
        img2 = _preparer(Image.frombytes("L", (pix2.width, pix2.height), pix2.samples))
        if (rot2 := _orientation(img2)):
            img2 = img2.rotate(-rot2, expand=True, fillcolor=255)
        texte2, conf2 = _tesseract(img2)
        if conf2 > conf:
            texte, conf = texte2, conf2

    propre = nettoyer(texte)
    return Page(index + 1, "ocr", round(conf, 2), len(propre), propre)


def traiter_document(chemin: Path, dpi: int = 300) -> Document:
    doc = fitz.open(chemin)
    pages = [traiter_page(doc, i, dpi) for i in range(len(doc))]
    doc.close()

    ocr = [p for p in pages if p.mode == "ocr"]
    conf = sum(p.confiance for p in ocr) / len(ocr) if ocr else 100.0
    mode = "natif" if not ocr else ("ocr" if len(ocr) == len(pages) else "mixte")

    return Document(
        fichier=chemin.name,
        pages=len(pages),
        mode=mode,
        confiance_moyenne=round(conf, 2),
        caracteres=sum(p.caracteres for p in pages),
        pages_faibles=[p.numero for p in ocr if p.confiance < SEUIL_RETENTE],
        detail=[asdict(p) for p in pages],
    )


# --------------------------------------------------------------------------
#  CLI
# --------------------------------------------------------------------------

def _tache(args):
    chemin, dpi, sortie = args
    try:
        res = traiter_document(Path(chemin), dpi)
    except Exception as exc:  # noqa: BLE001
        return chemin, None, f"{type(exc).__name__}: {exc}"
    Path(sortie).write_text(
        json.dumps(asdict(res), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return chemin, res, None


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR du corpus AMF-UMOA")
    ap.add_argument("entrees", nargs="+", help="fichiers PDF ou dossiers")
    ap.add_argument("-o", "--sortie", default="texte", help="dossier de sortie JSON")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    pdfs: list[Path] = []
    for e in args.entrees:
        p = Path(e)
        pdfs.extend(sorted(p.glob("*.pdf")) if p.is_dir() else [p])

    dest = Path(args.sortie)
    dest.mkdir(parents=True, exist_ok=True)

    taches = [
        (str(p), args.dpi, str(dest / (p.stem + ".json")))
        for p in pdfs
        if not (dest / (p.stem + ".json")).exists()
    ]
    print(f"{len(pdfs)} PDF, {len(taches)} à traiter, {args.jobs} processus\n", flush=True)

    faits = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futurs = {ex.submit(_tache, t): t[0] for t in taches}
        for f in as_completed(futurs):
            chemin, res, err = f.result()
            faits += 1
            nom = Path(chemin).name
            if err:
                print(f"  [{faits}/{len(taches)}] ECHEC {nom} : {err}", flush=True)
            else:
                alerte = f"  <- {len(res.pages_faibles)} page(s) à relire" if res.pages_faibles else ""
                print(
                    f"  [{faits}/{len(taches)}] {nom:38s} {res.pages:3d}p "
                    f"{res.mode:6s} conf={res.confiance_moyenne:5.1f} "
                    f"{res.caracteres:7d} car.{alerte}",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
