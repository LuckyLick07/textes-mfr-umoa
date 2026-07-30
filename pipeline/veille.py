#!/usr/bin/env python3
"""
Veille automatique sur le corpus réglementaire.

Deux sources alimentent le recueil.

La première est le site officiel de l'AMF-UMOA, dont l'API est interrogée pour
repérer les textes publiés depuis la dernière construction. La seconde est le
dossier `apports/`, où sont déposés les actes que l'Autorité mentionne sans les
publier — notamment ceux du Conseil des Ministres de l'UEMOA, dont la rubrique
« Autres actes » du site officiel est vide.

Ce module ne fait ni reconnaissance optique ni génération : il prépare le
travail, en déposant dans un dossier les seuls PDF nouveaux et en consignant ce
qu'il a trouvé. Il n'utilise que la bibliothèque standard, afin de tourner sans
installation préalable.

Usage :
    veille.py detecter  --texte texte --sortie nouveaux --journal journal
    veille.py finaliser --texte texte --journal journal
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timezone, datetime
from pathlib import Path

AMF = "https://www.amf-umoa.org"
API_LISTE = AMF + "/service/api/elastic/actualite?size=3000&page=0&langue=fr"
API_DOC = AMF + "/service/api/elastic/download/actualite/{id}/doc"

CATEGORIES = ("Instruction", "Circulaire", "Decision", "Rapport")
NAVIGATEUR = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Le premier mot du nom de fichier déposé indique le type de l'acte.
TYPES_DEPUIS_NOM = {
    "reglement": "autre", "règlement": "autre", "decision": "decision",
    "décision": "decision", "instruction": "instruction",
    "circulaire": "circulaire", "loi": "autre", "directive": "autre",
    "avis": "autre", "convention": "autre", "annexe": "autre",
    "traite": "autre", "traité": "autre",
}


def slugifier(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.replace("’", "'"))
                if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.replace("°", "")).lower()
    return re.sub(r"-{2,}", "-", t).strip("-")[:80]


def telecharger(url: str, destination: Path, delai: int = 180) -> tuple[bool, str]:
    """Récupère une adresse vers un fichier. Renvoie (succès, explication)."""
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            contenu = reponse.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if not contenu:
        return False, "réponse vide"
    if not contenu[:4] == b"%PDF" and destination.suffix.lower() == ".pdf":
        return False, f"ce n'est pas un PDF (débute par {contenu[:8]!r})"

    destination.write_bytes(contenu)
    return True, f"{len(contenu) // 1024} ko"


# --------------------------------------------------------------------------
#  Détection
# --------------------------------------------------------------------------

def lire_api() -> list[dict]:
    requete = urllib.request.Request(API_LISTE, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=120) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def detecter(dossier_texte: Path, sortie: Path, journal: Path,
             dossier_apports: Path) -> int:
    sortie.mkdir(parents=True, exist_ok=True)
    journal.mkdir(parents=True, exist_ok=True)
    deja = {f.stem for f in dossier_texte.glob("*.json")}

    lignes: list[str] = []
    nouveaux = echecs = 0

    # ---- Source officielle ------------------------------------------------
    try:
        items = lire_api()
        candidats = [it for it in items
                     if it.get("categorie") in CATEGORIES and it.get("documentUrl")]
        lignes.append(f"L'API de l'AMF-UMOA répond et annonce {len(items)} entrées, "
                      f"dont {len(candidats)} documents des catégories suivies.")

        manquants = [it for it in candidats
                     if f"{it['categorie'].lower()}_{it['id']}" not in deja]
        if not manquants:
            lignes.append("Aucun texte nouveau : le recueil est à jour.")
        else:
            lignes.append(f"{len(manquants)} texte(s) absent(s) du recueil :")
            for it in manquants:
                nom = f"{it['categorie'].lower()}_{it['id']}.pdf"
                ok, detail = telecharger(API_DOC.format(id=it["id"]), sortie / nom)
                if ok:
                    nouveaux += 1
                    lignes.append(f"- **{it.get('titre', '?')}** "
                                  f"({it.get('date', '?')}) — récupéré, {detail}")
                else:
                    echecs += 1
                    lignes.append(f"- {it.get('titre', '?')} — échec du "
                                  f"téléchargement ({detail})")

        # Le manifeste est réenregistré : il porte les intitulés et les résumés.
        Path("manifest.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        lignes.append(f"**L'API de l'AMF-UMOA est injoignable** "
                      f"({type(exc).__name__}: {exc}). La veille sur la source "
                      f"officielle est reportée ; les apports sont traités.")
        echecs += 1

    # ---- Apports déposés à la main ---------------------------------------
    fichier_meta = dossier_apports / "metadonnees.json"
    meta = json.loads(fichier_meta.read_text(encoding="utf-8")) \
        if fichier_meta.exists() else {}

    apportes = 0
    if dossier_apports.is_dir():
        for pdf in sorted(dossier_apports.glob("*.pdf")):
            titre = re.sub(r"\s+", " ", pdf.stem.replace("_", " ")).strip()
            ident = "apport_" + slugifier(titre)
            if ident in deja:
                continue
            premier = slugifier(titre.split()[0]) if titre.split() else ""
            meta.setdefault(ident, {
                "titre": titre,
                "type": TYPES_DEPUIS_NOM.get(premier, "autre"),
                "date": "",
                "resume": "",
                "source": "",
                "fichier_origine": pdf.name,
            })
            (sortie / f"{ident}.pdf").write_bytes(pdf.read_bytes())
            apportes += 1
            lignes.append(f"- **{titre}** — apport personnel, pris en compte")

    if apportes:
        fichier_meta.parent.mkdir(parents=True, exist_ok=True)
        fichier_meta.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        lignes.insert(0, f"{apportes} document(s) déposé(s) dans « apports » "
                         f"rejoignent le recueil.")
    elif dossier_apports.is_dir():
        lignes.append("Aucun nouveau document dans le dossier « apports ».")

    # ---- Compte rendu -----------------------------------------------------
    total = nouveaux + apportes
    entete = (f"# Veille du {date.today().isoformat()}\n\n"
              f"**{total} document(s) ajouté(s)**"
              + (f", {echecs} anomalie(s)." if echecs else ".") + "\n\n")
    rapport = entete + "\n".join(lignes) + "\n"
    (journal / "derniere-veille.md").write_text(rapport, encoding="utf-8")
    (journal / f"veille-{date.today().isoformat()}.md").write_text(
        rapport, encoding="utf-8")

    print(rapport)
    print(f"::notice::{total} document(s) à traiter, {echecs} anomalie(s)")
    # Un code de sortie 0 même sans nouveauté : l'absence de texte nouveau est
    # un résultat normal, pas une erreur.
    return 0


# --------------------------------------------------------------------------
#  Finalisation : compte rendu de qualité après reconnaissance
# --------------------------------------------------------------------------

def finaliser(dossier_texte: Path, journal: Path, sortie: Path) -> int:
    """Complète le compte rendu avec la qualité obtenue sur les nouveaux textes."""
    recents = sorted(sortie.glob("*.pdf"))
    if not recents:
        return 0

    lignes = ["", "## Qualité de la reconnaissance", ""]
    a_relire: list[str] = []
    for pdf in recents:
        f = dossier_texte / f"{pdf.stem}.json"
        if not f.exists():
            lignes.append(f"- {pdf.stem} — **aucune sortie produite**")
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        mode = {"natif": "texte natif", "ocr": "reconnaissance optique",
                "mixte": "mixte", "relu": "relu"}.get(d.get("mode"), d.get("mode"))
        conf = d.get("confiance_moyenne", 0)
        note = f"- {pdf.stem} — {d.get('pages')} pages, {mode}"
        if d.get("mode") != "natif":
            note += f", confiance {conf:.1f} %"
        if d.get("pages_faibles"):
            note += (f" — pages à relire : "
                     f"{', '.join(str(p) for p in d['pages_faibles'])}")
            a_relire.append(pdf.stem)
        lignes.append(note)

    if a_relire:
        lignes += ["", "Les documents ci-dessus comportent des pages dont la "
                   "reconnaissance est incertaine. Ils sont publiés — chaque page "
                   "du site signale son indice de confiance et renvoie au PDF "
                   "officiel — mais une relecture leur ferait gagner en fiabilité."]

    for nom in ("derniere-veille.md", f"veille-{date.today().isoformat()}.md"):
        chemin = journal / nom
        if chemin.exists():
            chemin.write_text(chemin.read_text(encoding="utf-8")
                              + "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Veille sur le corpus AMF-UMOA")
    sous = ap.add_subparsers(dest="commande", required=True)
    for nom in ("detecter", "finaliser"):
        p = sous.add_parser(nom)
        p.add_argument("--texte", default="texte")
        p.add_argument("--sortie", default="nouveaux")
        p.add_argument("--journal", default="journal")
        p.add_argument("--apports", default="apports")
    a = ap.parse_args()

    if a.commande == "detecter":
        return detecter(Path(a.texte), Path(a.sortie), Path(a.journal),
                        Path(a.apports))
    return finaliser(Path(a.texte), Path(a.journal), Path(a.sortie))


if __name__ == "__main__":
    sys.exit(main())
