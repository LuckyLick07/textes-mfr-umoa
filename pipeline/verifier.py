#!/usr/bin/env python3
"""
Contrôles automatiques sur le site généré.

Vérifie ce qui casse silencieusement un site statique : liens internes morts,
balisage structuré invalide, pages sans contenu, entrées de sitemap sans cible,
index de recherche incohérent. Le script sort en code 1 dès qu'une anomalie
bloquante est détectée, ce qui permet de l'utiliser en intégration continue.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse

LIENS = re.compile(r'(?:href|src)="([^"]+)"')
JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
TITRE = re.compile(r"<title>(.*?)</title>", re.S)
DESC = re.compile(r'<meta name="description" content="([^"]*)"')
CANON = re.compile(r'<link rel="canonical" href="([^"]+)"')
H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
BALISES = re.compile(r"<[^>]+>")


class Rapport:
    def __init__(self) -> None:
        self.erreurs: list[str] = []
        self.avertissements: list[str] = []
        self.stats: Counter = Counter()

    def erreur(self, m: str) -> None:
        self.erreurs.append(m)

    def alerte(self, m: str) -> None:
        self.avertissements.append(m)


def verifier(racine: Path) -> Rapport:
    r = Rapport()
    if not racine.is_dir():
        r.erreur(f"dossier introuvable : {racine}")
        return r

    pages = sorted(racine.rglob("*.html"))
    r.stats["pages"] = len(pages)
    if not pages:
        r.erreur("aucune page HTML générée")
        return r

    # ---- Pages : métadonnées, contenu, balisage structuré ----------------
    canoniques: Counter = Counter()

    for page in pages:
        rel = page.relative_to(racine)
        html = page.read_text(encoding="utf-8", errors="replace")

        if m := TITRE.search(html):
            titre = BALISES.sub("", m.group(1)).strip()
            if not titre:
                r.erreur(f"{rel} : balise title vide")
            elif len(titre) > 130:
                r.alerte(f"{rel} : title de {len(titre)} caractères "
                         f"(risque de troncature dans les résultats)")
        else:
            r.erreur(f"{rel} : title absent")

        if m := DESC.search(html):
            if not m.group(1).strip():
                r.erreur(f"{rel} : meta description vide")
        else:
            r.erreur(f"{rel} : meta description absente")

        if m := CANON.search(html):
            canoniques[m.group(1)] += 1
        else:
            r.erreur(f"{rel} : URL canonique absente")

        h1 = H1.findall(html)
        if len(h1) == 0:
            r.erreur(f"{rel} : aucun h1")
        elif len(h1) > 1:
            r.alerte(f"{rel} : {len(h1)} balises h1")

        for bloc in JSONLD.findall(html):
            r.stats["jsonld"] += 1
            try:
                obj = json.loads(bloc)
            except json.JSONDecodeError as exc:
                r.erreur(f"{rel} : JSON-LD invalide ({exc})")
                continue
            if "@context" not in obj or "@type" not in obj:
                r.erreur(f"{rel} : JSON-LD sans @context ou @type")

        # Une page de texte doit contenir du texte : c'est tout l'objet du site.
        if rel.as_posix().startswith("textes/"):
            # Le corps contient des div imbriqués (repères de page) : on borne
            # sur la fermeture indentée du gabarit, non sur le premier </div>.
            corps = re.search(
                r'<div class="corps-texte"[^>]*>(.*?)\n  </div>', html, re.S)
            longueur = len(BALISES.sub(" ", corps.group(1)).strip()) if corps else 0
            if corps is None:
                r.erreur(f"{rel} : bloc corps-texte introuvable")
            r.stats["caracteres_texte"] += longueur
            if longueur < 200:
                r.erreur(f"{rel} : corps de texte quasi vide ({longueur} car.)")

    for url, n in canoniques.items():
        if n > 1:
            r.erreur(f"URL canonique dupliquée ({n} pages) : {url}")

    # ---- Liens internes --------------------------------------------------
    externes = casses = 0
    for page in pages:
        rel = page.relative_to(racine)
        html = page.read_text(encoding="utf-8", errors="replace")
        for lien in LIENS.findall(html):
            if lien.startswith(("http://", "https://", "mailto:", "#", "data:")):
                externes += 1
                continue
            chemin = unquote(urlparse(lien).path)
            if not chemin:
                continue
            cible = (page.parent / chemin).resolve()
            if cible.is_dir():
                cible = cible / "index.html"
            if not cible.exists():
                # Les PDF peuvent être délibérément non embarqués.
                if chemin.endswith(".pdf"):
                    r.alerte(f"{rel} : PDF local absent → {lien}")
                else:
                    r.erreur(f"{rel} : lien interne mort → {lien}")
                    casses += 1
            else:
                r.stats["liens_internes"] += 1
    r.stats["liens_externes"] = externes

    # ---- Sitemap ---------------------------------------------------------
    sitemap = racine / "sitemap.xml"
    if not sitemap.exists():
        r.erreur("sitemap.xml absent")
    else:
        locs = re.findall(r"<loc>(.*?)</loc>", sitemap.read_text(encoding="utf-8"))
        r.stats["sitemap"] = len(locs)
        if not locs:
            r.erreur("sitemap.xml sans aucune URL")
        base = None
        for loc in locs:
            p = urlparse(loc)
            if base is None:
                base = f"{p.scheme}://{p.netloc}"
            elif f"{p.scheme}://{p.netloc}" != base:
                r.erreur(f"sitemap : domaine incohérent → {loc}")
            chemin = unquote(p.path).strip("/")
            # Sur une page de projet GitHub, le premier segment de l'URL est le
            # nom du dépôt et n'existe pas dans l'arborescence produite.
            variantes = [chemin]
            if "/" in chemin:
                variantes.append(chemin.split("/", 1)[1])
            elif chemin:
                variantes.append("")
            if not any((racine / v / "index.html").exists() or
                       (v and (racine / v).is_file())
                       for v in variantes):
                r.erreur(f"sitemap : URL sans page correspondante → {loc}")
        if len(set(locs)) != len(locs):
            r.erreur("sitemap : URLs dupliquées")

    if not (racine / "robots.txt").exists():
        r.alerte("robots.txt absent")

    # ---- Index de recherche ---------------------------------------------
    idx = racine / "data" / "index-recherche.json"
    if not idx.exists():
        r.erreur("index de recherche absent")
    else:
        data = json.loads(idx.read_text(encoding="utf-8"))
        docs, termes = data.get("docs", []), data.get("termes", {})
        r.stats["index_docs"] = len(docs)
        r.stats["index_termes"] = len(termes)
        r.stats["index_ko"] = idx.stat().st_size // 1024

        pages_texte = [p for p in pages
                       if p.relative_to(racine).as_posix().startswith("textes/")]
        if len(docs) != len(pages_texte):
            r.alerte(f"index : {len(docs)} documents indexés pour "
                     f"{len(pages_texte)} pages de texte")

        for i, d in enumerate(docs):
            if len(d) < 7:
                r.erreur(f"index : entrée {i} incomplète")
                break
            if not (racine / "textes" / d[0] / "index.html").exists():
                r.erreur(f"index : slug sans page → {d[0]}")
            if not (racine / "data" / f"{d[0]}.txt").exists():
                r.erreur(f"index : texte brut absent → {d[0]}.txt")

        hors = [t for t, p in list(termes.items())[:5000]
                for d, _ in p if d >= len(docs)]
        if hors:
            r.erreur(f"index : {len(hors)} renvoi(s) vers un document inexistant")

        if "idf" in data and set(data["idf"]) != set(termes):
            r.alerte("index : table idf désynchronisée des postings")

        for essai in ("agrement", "capital", "sgi", "article"):
            if essai in termes:
                r.stats["termes_temoins"] += 1

    return r


def main() -> int:
    racine = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    r = verifier(racine)

    print(f"\nContrôle de {racine}")
    print("-" * 66)
    for cle, val in sorted(r.stats.items()):
        print(f"  {cle:22s} {val}")

    if r.avertissements:
        print(f"\n{len(r.avertissements)} avertissement(s) :")
        for a in r.avertissements[:25]:
            print(f"  · {a}")
        if len(r.avertissements) > 25:
            print(f"  · … et {len(r.avertissements) - 25} autre(s)")

    if r.erreurs:
        print(f"\n{len(r.erreurs)} ERREUR(S) :")
        for x in r.erreurs[:40]:
            print(f"  × {x}")
        if len(r.erreurs) > 40:
            print(f"  × … et {len(r.erreurs) - 40} autre(s)")
        print("\nRésultat : ÉCHEC")
        return 1

    print("\nRésultat : tous les contrôles passent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
