#!/usr/bin/env python3
"""
Analyse de cohérence du corpus : le sens des pages, pas seulement leur texte.

L'OCR restitue des caractères ; ce module vérifie que ce qu'ils composent se
tient. Pour chaque document, il relève :

  - les pages sans contenu exploitable (souvent une page de garde ou un
    feuillet d'en-tête, parfois une page dont la reconnaissance a échoué) ;
  - les trous et les doublons dans la numérotation des articles — un
    « Article 13 » manquant signale presque toujours un intitulé que l'OCR a
    défiguré et que la structuration n'a pas reconnu ;
  - les séquences de TITRES incomplètes, pour la même raison ;
  - les articles sans corps : un intitulé immédiatement suivi du suivant ;
  - le volume de résidus de papier à en-tête écartés par l'épuration.

La sortie est un rapport Markdown trié : les documents les plus atteints
d'abord. Il sert de feuille de route à la relecture — chaque anomalie se
corrige ensuite par `corrections/relecture.json`, jamais à la main dans les
sorties OCR.

Usage :
    coherence.py --texte texte --manifeste manifest.json [--sortie rapport.md]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from corpus import Texte, charger

_ROMAINS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def valeur_romaine(t: str) -> int | None:
    t = t.strip().upper()
    if t == "PREMIER":
        return 1
    if t.isdigit():
        return int(t)
    if not t or any(c not in _ROMAINS for c in t):
        return None
    total = 0
    for i, c in enumerate(t):
        v = _ROMAINS[c]
        total += -v if i + 1 < len(t) and _ROMAINS[t[i + 1]] > v else v
    return total


def numero_article(marque: str) -> int | None:
    m = re.match(r"Article (premier|\d+)", marque)
    if not m:
        return None
    return 1 if m.group(1) == "premier" else int(m.group(1))


def series_articles(nums: list[int]) -> list[list[int]]:
    """Découpe la suite des numéros en séries croissantes.

    Un retour en arrière (…, 21, 1, 2, …) marque le début d'une nouvelle
    série : annexe, formulaire ou texte reproduit à la suite.
    """
    series: list[list[int]] = []
    for n in nums:
        if not series or n < series[-1][-1]:
            series.append([n])
        else:
            series[-1].append(n)
    return series


def analyser(t: Texte) -> dict:
    a = {"pages_vides": [], "articles_manquants": [], "articles_doublons": [],
         "titres_manquants": [], "articles_sans_corps": [],
         "residus": t.residus_retires, "series": 0}

    # Pages dont plus rien ne subsiste après nettoyage et structuration.
    presentes = {b.page for b in t.blocs if b.page}
    a["pages_vides"] = [p for p in range(1, t.pages + 1) if p not in presentes]

    # Numérotation des articles, par séries.
    nums = [n for b in t.blocs if b.genre == "article"
            and (n := numero_article(b.marque)) is not None]
    series = series_articles(nums)
    a["series"] = len(series)
    for s in series:
        vus = set()
        for n in s:
            if n in vus and n not in a["articles_doublons"]:
                a["articles_doublons"].append(n)
            vus.add(n)
        a["articles_manquants"] += [n for n in range(min(s), max(s) + 1)
                                    if n not in vus]

    # Séquence des TITRES. Les valeurs au-delà de 20 sont des lectures
    # aberrantes de l'OCR : elles n'entrent pas dans la séquence attendue.
    titres = [v for b in t.blocs if b.genre == "titre"
              and b.marque.upper().startswith("TITRE")
              and (v := valeur_romaine(b.marque.split(maxsplit=1)[1])) is not None
              and v <= 20]
    if len(titres) >= 2:
        vus_t = set(titres)
        a["titres_manquants"] = [n for n in range(1, max(titres) + 1)
                                 if n not in vus_t]

    # Articles sans corps : l'intitulé existe, le texte ne suit pas.
    for i, b in enumerate(t.blocs):
        if b.genre != "article":
            continue
        suivant = t.blocs[i + 1] if i + 1 < len(t.blocs) else None
        if suivant is None or suivant.genre in ("titre", "section", "article"):
            a["articles_sans_corps"].append(b.marque)

    return a


def gravite(a: dict) -> int:
    return (len(a["articles_manquants"]) * 3
            + len(a["articles_sans_corps"]) * 2
            + len(a["titres_manquants"]) * 2
            + len(a["articles_doublons"])
            + len(a["pages_vides"]))


def lister(valeurs: list, limite: int = 12) -> str:
    # Une numérotation très lacunaire — loi uniforme annexée dont la
    # structuration a largement échoué — se résume au lieu de s'énumérer.
    if valeurs and all(isinstance(v, int) for v in valeurs) and len(valeurs) > 30:
        return f"{len(valeurs)} absents entre {min(valeurs)} et {max(valeurs)}"
    txt = ", ".join(str(v) for v in valeurs[:limite])
    return txt + (f"… (+{len(valeurs) - limite})" if len(valeurs) > limite else "")


def rapport(textes: list[Texte]) -> str:
    lignes = ["# Cohérence du corpus", ""]

    analyses = [(t, analyser(t)) for t in textes]
    atteints = [(t, a) for t, a in analyses if gravite(a) > 0]
    atteints.sort(key=lambda x: -gravite(x[1]))

    total_residus = sum(a["residus"] for _, a in analyses)
    lignes += [
        f"{len(textes)} documents examinés · "
        f"{len(atteints)} présentent au moins une anomalie · "
        f"{total_residus} lignes de gabarit (coordonnées, pagination, rappels "
        f"d'en-tête) écartées à la construction.",
        "",
        "Un article « manquant » n'a le plus souvent pas disparu : son",
        "intitulé a été défiguré par la reconnaissance optique et n'a pas été",
        "reconnu comme tel — le texte est alors fondu dans l'article",
        "précédent. La correction passe par `corrections/relecture.json`,",
        "après contrôle de la page indiquée sur le PDF original.",
        "",
        "| Document | Pages vides | Articles manquants | Doublons | Titres manquants | Sans corps |",
        "|---|---|---|---|---|---|",
    ]
    for t, a in atteints:
        lignes.append(
            f"| {t.slug} | {lister(a['pages_vides'], 6) or '—'} "
            f"| {lister(a['articles_manquants'], 6) or '—'} "
            f"| {lister(a['articles_doublons'], 4) or '—'} "
            f"| {lister(a['titres_manquants'], 4) or '—'} "
            f"| {lister(a['articles_sans_corps'], 3) or '—'} |")

    lignes += ["", "## Détail des documents les plus atteints", ""]
    for t, a in atteints[:20]:
        lignes.append(f"### {t.slug} — {t.titre_court[:70]}")
        lignes.append(f"{t.pages} pages, mode {t.mode}, confiance "
                      f"{t.confiance:.0f} %, {a['residus']} résidus écartés, "
                      f"{a['series']} série(s) d'articles.")
        if a["pages_vides"]:
            lignes.append(f"- Pages sans contenu : {lister(a['pages_vides'])}")
        if a["articles_manquants"]:
            lignes.append(f"- Articles manquants : {lister(a['articles_manquants'])}")
        if a["articles_doublons"]:
            lignes.append(f"- Numéros en double : {lister(a['articles_doublons'])}")
        if a["titres_manquants"]:
            lignes.append(f"- Titres manquants : {lister(a['titres_manquants'])}")
        if a["articles_sans_corps"]:
            lignes.append(f"- Sans corps : {lister(a['articles_sans_corps'])}")
        lignes.append("")

    sains = len(textes) - len(atteints)
    lignes.append(f"Les {sains} autres documents ne présentent aucune "
                  f"anomalie de structure détectable.")
    return "\n".join(lignes) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Cohérence du corpus AMF-UMOA")
    ap.add_argument("--texte", default="texte")
    ap.add_argument("--manifeste", default="manifest.json")
    ap.add_argument("--sortie", default="")
    a = ap.parse_args()

    textes = charger(Path(a.texte), Path(a.manifeste))
    r = rapport(textes)
    if a.sortie:
        Path(a.sortie).write_text(r, encoding="utf-8")
        print(f"Rapport écrit dans {a.sortie}")
    else:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
