#!/usr/bin/env python3
"""
Générateur du site statique du corpus réglementaire AMF-UMOA.

Produit un site entièrement statique où le texte intégral de chaque document
figure dans le HTML — condition nécessaire pour que les moteurs de recherche
indexent des contenus aujourd'hui enfermés dans des images scannées.

Sortie : arborescence prête à publier (GitHub Pages), avec URLs propres,
balisage schema.org Legislation, sitemap et recherche plein texte côté client.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from acteurs import CATEGORIES, ORDRE as ORDRE_CATEGORIES, TEXTES_COMMUNS
from produits import FAMILLES, ORDRE as ORDRE_FAMILLES
from produits import TEXTES_COMMUNS as OPC_TEXTES_COMMUNS
from produits import charger as charger_opc
from produits import par_famille as opc_par_famille
from produits import par_societe as produits_par_societe
from personnes import FAMILLES_FONCTION
from personnes import charger as charger_personnes
from personnes import par_societe as personnes_par_societe
from acteurs import charger as charger_acteurs
from acteurs import homologues as acteurs_homologues
from acteurs import par_categorie as acteurs_par_categorie
from corpus import (TYPES, Texte, charger, date_francaise, sans_accent,
                    titre_propre)
from illustrations import (EMBLEME, bande_guillochee, icone, illustration_heros,
                           sceau_rosette)

SITE_NOM = "Textes du Marché Financier Régional de l’UMOA"
SITE_COURT = "Textes MFR-UMOA"
SITE_DESC = ("Recueil consultable et indexable des textes réglementaires du Marché "
             "Financier Régional de l’UMOA : Convention, Règlement Général, "
             "instructions, circulaires et décisions de l'AMF-UMOA.")
AUTORITE = "Autorité des Marchés Financiers de l'Union Monétaire Ouest Africaine"

# Rubriques effectivement produites lors de la construction en cours. La
# navigation ne pointe que vers celles-ci, pour qu'un corpus partiel ne génère
# jamais de lien mort.
SECTIONS_PRESENTES: set[str] = set()

# Vrai lorsque l'annuaire des acteurs a pu être chargé : la navigation ne
# propose la rubrique que si elle est effectivement produite.
ACTEURS_PRESENTS = False
OPC_PRESENTS = False
PERSONNES_PRESENTES = False

MOTS_VIDES = set("""
au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma
mais me meme mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se
ses son sur ta te tes toi ton tu un une vos votre vous c d j l a m n s t y ete
etee etees etes etant suis es est sommes etes sont serai seras sera serons serez
seront serais serait serions seriez seraient etais etait etions etiez etaient
fus fut fumes futes furent sois soit soyons soyez soient fusse fusses fut ai as
avons avez ont aurai auras aura aurons aurez auront aurais aurait aurions auriez
auraient avais avait avions aviez avaient eus eut eumes eutes eurent aie aies
ait ayons ayez aient eusse eusses eut eussions eussiez eussent ayant eu eue eues
plus tres etre avoir cette cet celui celle ceux dont donc alors ainsi comme
lorsque apres avant entre sous vers chez sans selon dit dite dits dites
""".split())


# --------------------------------------------------------------------------
#  Outils
# --------------------------------------------------------------------------

def e(t: str) -> str:
    return html.escape(t or "", quote=True)


def jetons(t: str) -> list[str]:
    t = sans_accent(t.replace("’", "'")).lower()
    return [j for j in re.split(r"[^a-z0-9]+", t) if len(j) >= 2]


def statut(t: Texte) -> tuple[str, str]:
    """Reprend la qualification de la source, sans l'interpréter.

    Le site officiel renseigne une colonne « État » qui indique « non abrogé » ;
    il n'affirme pas la force juridique du texte. Écrire « en vigueur » serait
    une conclusion juridique que ce recueil n'a pas à tirer — d'autant que la
    présentation du cadre légal mentionne des instructions abrogées sans que la
    source précise lesquelles.
    """
    return ("Abrogé", "abroge") if t.abroge else ("Non abrogé", "vigueur")


# --------------------------------------------------------------------------
#  Gabarit commun
# --------------------------------------------------------------------------

def page_html(*, titre: str, description: str, corps: str, chemin: str,
              base_url: str, jsonld: str = "", classe: str = "",
              script_annuaire: bool = False, indexable: bool = True) -> str:
    """Enveloppe HTML commune. `chemin` est la profondeur relative vers la racine."""
    canonique = base_url.rstrip("/") + "/" + chemin.lstrip("/")
    racine = "../" * (chemin.strip("/").count("/") + 1) if chemin.strip("/") else ""
    an = date.today().year

    presentes = SECTIONS_PRESENTES or set(TYPES)
    liens_nav = "\n      ".join(
        f'<a href="{racine}{TYPES[c][1]}/">{e(TYPES[c][2])}</a>'
        for c in TYPES
        if c != "rapport" and c in presentes
    )
    if ACTEURS_PRESENTS:
        liens_nav += f'\n      <span class="nav-sep" aria-hidden="true"></span>'
        liens_nav += f'\n      <a href="{racine}acteurs/">Acteurs</a>'
    if OPC_PRESENTS:
        liens_nav += f'\n      <a href="{racine}opc/">OPC</a>'
    if PERSONNES_PRESENTES:
        liens_nav += f'\n      <a href="{racine}personnes/">Personnes</a>'
    lien_rapports = (f' ·\n      <a href="{racine}rapports/">Rapports</a>'
                     if "rapport" in presentes else "")
    script_sup = (f'\n<script src="{racine}assets/annuaire.js" defer></script>'
                  if script_annuaire else "")

    # Les fiches de personnes physiques sont consultables mais tenues hors des
    # moteurs : le registre de l'Autorité lui-même n'est pas indexable, et un
    # annuaire nominatif trouvable par une recherche sur un nom propre n'a pas
    # la même portée qu'une page de société.
    directive_robots = (
        '<meta name="robots" content="index, follow, max-snippet:-1, '
        'max-image-preview:large">' if indexable else
        '<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">\n'
        '<meta name="googlebot" content="noindex, nofollow">')

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titre)}</title>
<meta name="description" content="{e(description[:300])}">
<link rel="canonical" href="{e(canonique)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(titre)}">
<meta property="og:description" content="{e(description[:300])}">
<meta property="og:url" content="{e(canonique)}">
<meta property="og:site_name" content="{e(SITE_NOM)}">
<meta property="og:locale" content="fr_FR">
<meta name="twitter:card" content="summary">
{directive_robots}
<link rel="icon" href="{racine}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{racine}assets/style.css">
{jsonld}
</head>
<body class="{classe}">
<a class="saut" href="#contenu">Aller au contenu</a>
<header class="entete">
  <div class="conteneur entete-corps">
    <a class="marque" href="{racine or './'}">
      {EMBLEME}
      <span class="marque-texte">
        <span class="marque-titre">{e(SITE_COURT)}</span>
        <span class="marque-sous">Corpus réglementaire consultable</span>
      </span>
    </a>
    <nav class="nav" aria-label="Navigation principale">
      {liens_nav}
      <a href="{racine}recherche/" class="nav-recherche">Rechercher</a>
    </nav>
  </div>
</header>
<main id="contenu">
{corps}
</main>
<script src="{racine}assets/assistant.js" defer></script>{script_sup}
<footer class="pied">
  {bande_guillochee("guilloche-pied")}
  <div class="conteneur pied-corps">
    <div class="pied-textes">
      <p class="pied-avis"><strong>Site non officiel.</strong> Ce recueil est une
      initiative indépendante destinée à rendre consultables et indexables des
      textes publics aujourd'hui diffusés sous forme d'images scannées.
      Il n'émane pas de l'AMF-UMOA et n'a aucune valeur juridique&nbsp;: seuls les
      documents originaux publiés par l'Autorité font foi.</p>
      <p class="pied-liens">
        <a href="{racine}a-propos/">À propos et méthode</a> ·
        <a href="{racine}chronologie/">Chronologie</a>{lien_rapports} ·
        <a href="https://www.amf-umoa.org/" rel="noopener external">Site officiel de l'AMF-UMOA</a>
      </p>
      <p class="pied-mention">Source des documents&nbsp;: {e(AUTORITE)} · Recueil mis à jour en {an}</p>
    </div>
    {sceau_rosette(88)}
  </div>
</footer>
</body>
</html>
"""


# --------------------------------------------------------------------------
#  Rendu du texte structuré
# --------------------------------------------------------------------------

def rendre_blocs(t: Texte) -> tuple[str, list[tuple[str, str]]]:
    """Rend les blocs en HTML sémantique et renvoie le sommaire."""
    morceaux: list[str] = []
    sommaire: list[tuple[str, str]] = []
    en_liste = False
    page_vue = 0
    compteur: dict[str, int] = defaultdict(int)

    def fermer_liste():
        nonlocal en_liste
        if en_liste:
            morceaux.append("</ul>")
            en_liste = False

    for b in t.blocs:
        if b.page and b.page != page_vue:
            fermer_liste()
            page_vue = b.page
            morceaux.append(
                f'<div class="repere-page" id="page-{b.page}" '
                f'aria-hidden="true"><span>page {b.page}</span></div>'
            )

        if b.genre in ("titre", "section", "article"):
            fermer_liste()
            base = re.sub(r"-{2,}", "-",
                          re.sub(r"[^a-z0-9]+", "-",
                                 sans_accent(b.marque).lower())).strip("-")
            base = base or "section"
            compteur[base] += 1
            ancre = base if compteur[base] == 1 else f"{base}-{compteur[base]}"
            niveau = {"titre": "h2", "section": "h3", "article": "h3"}[b.genre]
            classe = f"bloc-{b.genre}"
            intitule = f" — {e(b.texte)}" if b.texte else ""
            morceaux.append(
                f'<{niveau} class="{classe}" id="{e(ancre)}">'
                f'<a class="ancre" href="#{e(ancre)}" aria-label="Lien vers {e(b.marque)}">#</a>'
                f'<span class="marque">{e(b.marque)}</span>{intitule}</{niveau}>'
            )
            if b.genre in ("titre", "article"):
                sommaire.append((ancre, b.marque + (f" — {b.texte}" if b.texte else "")))

        elif b.genre in ("puce", "numerote"):
            if not en_liste:
                morceaux.append('<ul class="bloc-liste">')
                en_liste = True
            prefixe = (f'<span class="puce-num">{e(b.marque)}</span> '
                       if b.genre == "numerote" and b.marque else "")
            morceaux.append(f"<li>{prefixe}{e(b.texte)}</li>")

        else:
            fermer_liste()
            morceaux.append(f"<p>{e(b.texte)}</p>")

    fermer_liste()
    return "\n".join(morceaux), sommaire


# --------------------------------------------------------------------------
#  Page d'un texte
# --------------------------------------------------------------------------

def page_texte(t: Texte, base_url: str, voisins: dict,
               pdf_local: bool = False) -> str:
    lib_statut, cls_statut = statut(t)
    contenu, sommaire = rendre_blocs(t)

    # Par défaut le recueil renvoie vers le PDF officiel : c'est la référence
    # qui fait foi, et cela évite d'héberger des centaines de Mo de scans.
    lien_pdf = f"../../pdf/{e(t.pdf)}" if pdf_local else e(t.pdf_url)
    ext_pdf = "" if pdf_local else ' rel="noopener external"'

    # Les textes de base n'ont pas de numéro : leur nom court les identifie
    # mieux que la mention générique du type.
    identifiant = (t.titre_court if t.type_cle == "base"
                   else (f"{t.libelle_type} {t.numero}".strip() or t.titre_court))
    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "name": t.titre,
        "legislationIdentifier": identifiant,
        "legislationType": t.libelle_type,
        "legislationJurisdiction": "Union Monétaire Ouest Africaine (UMOA)",
        "legislationLegalForce": "NotInForce" if t.abroge else "InForce",
        "inLanguage": "fr",
        "url": f"{base_url.rstrip('/')}/textes/{t.slug}/",
        "publisher": {
            "@type": "GovernmentOrganization",
            "name": AUTORITE,
            "alternateName": "AMF-UMOA",
            "url": "https://www.amf-umoa.org/",
        },
        "isBasedOn": {
            "@type": "DigitalDocument",
            "name": f"{t.titre} (PDF original publié par l'AMF-UMOA)",
            "url": t.pdf_url,
            "encodingFormat": "application/pdf",
        },
    }
    # La date de l'API est celle de la mise en ligne. On ne la déclare comme
    # date de l'acte que lorsque l'année concorde avec celle de la référence ;
    # sinon on se contente de la date de publication en ligne, seule certaine.
    if t.date_iso:
        jsonld_obj["datePublished"] = t.date_iso
        if t.annee_texte and t.date_iso[:4] == t.annee_texte:
            jsonld_obj["legislationDate"] = t.date_iso
    if t.resume:
        jsonld_obj["abstract"] = t.resume

    fil = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Accueil",
             "item": base_url.rstrip("/") + "/"},
            {"@type": "ListItem", "position": 2, "name": t.libelle_pluriel,
             "item": f"{base_url.rstrip('/')}/{t.dossier_type}/"},
            {"@type": "ListItem", "position": 3, "name": identifiant},
        ],
    }
    jsonld = (
        '<script type="application/ld+json">'
        + json.dumps(jsonld_obj, ensure_ascii=False) + "</script>\n"
        '<script type="application/ld+json">'
        + json.dumps(fil, ensure_ascii=False) + "</script>"
    )

    som_html = ""
    if len(sommaire) >= 3:
        items = "\n".join(
            f'<li><a href="#{e(a)}">{e(txt[:110])}</a></li>' for a, txt in sommaire
        )
        som_html = f"""
<nav class="sommaire" aria-labelledby="som-titre">
  <h2 id="som-titre">Sommaire</h2>
  <ol>{items}</ol>
</nav>"""

    tags_html = ""
    if t.tags:
        puces = " ".join(f'<span class="etiquette">{e(x)}</span>' for x in t.tags)
        tags_html = f'<div class="etiquettes">{puces}</div>'

    fiabilite = (
        f'<p class="ocr-detail">Reconnaissance optique du texte, indice de '
        f'confiance moyen&nbsp;: <strong>{t.confiance:.1f}&nbsp;%</strong>.'
        + (f" Pages à relire en priorité&nbsp;: "
           f"{', '.join(str(p) for p in t.pages_faibles)}."
           if t.pages_faibles else "")
        + "</p>"
    ) if t.mode != "natif" else (
        '<p class="ocr-detail">Texte extrait directement de la couche '
        'textuelle du PDF d\'origine.</p>'
    )

    # Abrogation attestée : la fiche cite le texte qui la prononce.
    abroge_par_html = ""
    if t.abroge_par:
        cible = (f'<a href="../{e(t.abroge_par_slug)}/">{e(t.abroge_par)}</a>'
                 if t.abroge_par_slug else e(t.abroge_par))
        abroge_par_html = f'<div><dt>Abrogé par</dt><dd>{cible}</dd></div>'

    # La note de statut distingue les deux origines possibles : la colonne
    # « État » de la source, ou une clause expresse d'un texte publié.
    if t.abroge_par:
        note_statut = (
            '<p class="ocr-detail">Le statut «&nbsp;Abrogé&nbsp;» est rapporté '
            'ici parce qu\'un texte publié du recueil le prononce expressément '
            '— voir la référence dans la fiche ci-dessus — et non d\'après la '
            'colonne «&nbsp;État&nbsp;» de la source officielle, qui ne le '
            'mentionne pas. Vérifiez l\'état exact du texte auprès de '
            'l\'Autorité avant tout usage.</p>')
    else:
        note_statut = (
            '<p class="ocr-detail">Le statut affiché reprend la seule '
            'indication de la source officielle et ne constitue pas une '
            'appréciation de la force juridique du texte&nbsp;: vérifiez '
            'qu\'il n\'a pas été modifié ou abrogé depuis.</p>')

    refs_html = ""
    liens_refs = []
    for num in t.references.get("articles_rg", [])[:12]:
        liens_refs.append(
            f'<a href="../reglement-general/#article-{num}">Article {num} '
            f'du Règlement Général</a>')
    if liens_refs:
        refs_html = (
            '<section class="textes-lies"><h2>Renvois détectés dans le texte</h2><p>'
            + " · ".join(liens_refs) + "</p></section>"
        )

    prec, suiv = voisins.get("prec"), voisins.get("suiv")
    nav_html = '<nav class="nav-voisins" aria-label="Documents voisins">'
    nav_html += (f'<a class="voisin prec" href="../{prec.slug}/"><span>Précédent</span>'
                 f'{e(prec.titre_court[:80])}</a>' if prec else "<span></span>")
    nav_html += (f'<a class="voisin suiv" href="../{suiv.slug}/"><span>Suivant</span>'
                 f'{e(suiv.titre_court[:80])}</a>' if suiv else "<span></span>")
    nav_html += "</nav>"

    corps = f"""
<article class="texte" itemscope itemtype="https://schema.org/Legislation">
<div class="conteneur">

  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../../">Accueil</a> <span>›</span>
    <a href="../../{t.dossier_type}/">{e(t.libelle_pluriel)}</a> <span>›</span>
    <span aria-current="page">{e(identifiant)}</span>
  </nav>

  <header class="texte-entete">
    <p class="surtitre">{icone(t.type_cle, 15)}{e(t.libelle_type)}{(' · ' + e(t.numero)) if t.numero else ''}</p>
    <h1 itemprop="name">{e(t.titre)}</h1>
    <dl class="fiche">
      <div><dt>Statut</dt><dd><span class="badge {cls_statut}">{lib_statut}</span></dd></div>
      {abroge_par_html}
      {f'<div><dt>Référence</dt><dd>{e(t.numero)}</dd></div>' if t.numero else ''}
      {f'<div><dt>Année du texte</dt><dd>{e(t.annee)}</dd></div>' if t.annee else ''}
      {f'<div><dt>Mise en ligne</dt><dd><time datetime="{e(t.date_iso)}">{e(t.date_texte)}</time></dd></div>' if t.date_iso else ''}
      <div><dt>Pages</dt><dd>{t.pages}</dd></div>
      <div><dt>Source</dt><dd><a href="{e(t.source_url)}" rel="noopener external">AMF-UMOA</a></dd></div>
    </dl>
    {tags_html}
    {f'<p class="chapeau" itemprop="abstract">{e(t.resume)}</p>' if t.resume else ''}
    <div class="actions">
      <a class="bouton" href="{lien_pdf}"{ext_pdf}{'' if pdf_local else ' data-pdf-distant'}>Consulter le PDF original</a>
      <a class="bouton secondaire" href="../../data/{e(t.slug)}.txt">Texte brut</a>
    </div>
  </header>

  <aside class="avis" role="note">
    <p><strong>Avertissement.</strong> Le texte ci-dessous a été obtenu par
    reconnaissance optique de caractères à partir du document scanné publié par
    l'AMF-UMOA. Des erreurs de lecture résiduelles sont possibles.
    <strong>Seul le PDF original fait foi.</strong> Vérifiez
    systématiquement toute citation sur le document source avant tout usage
    professionnel.</p>
    {note_statut}
    {fiabilite}
  </aside>
{som_html}

  <div class="corps-texte" itemprop="text">
{contenu}
  </div>

{refs_html}

  <section class="citer">
    <h2>Citer ce document</h2>
    <p class="citation">{e(identifiant)}, {e(t.titre)}{(' (' + e(t.annee) + ')') if t.annee else ''}.
    {e(AUTORITE)}. Document original&nbsp;:
    <a href="{e(t.source_url)}" rel="noopener external">amf-umoa.org</a>.</p>
  </section>

{nav_html}
</div>
</article>
<script src="../../assets/pdf.js" defer></script>
"""
    desc = t.resume or f"{identifiant} — {t.titre}"
    # Éviter « Règlement Général — Règlement Général » : sur les textes de base,
    # la référence et le nom court sont un seul et même libellé.
    titre_onglet = (identifiant if identifiant == t.titre_court
                    else f"{identifiant} — {t.titre_court[:80]}")
    return page_html(titre=titre_onglet,
                     description=desc, corps=corps,
                     chemin=f"textes/{t.slug}/", base_url=base_url,
                     jsonld=jsonld, classe="page-texte")


# --------------------------------------------------------------------------
#  Listes
# --------------------------------------------------------------------------

def carte(t: Texte, prefixe: str = "../textes/") -> str:
    lib, cls = statut(t)
    meta = " · ".join(x for x in [t.numero, t.annee, f"{t.pages} p."] if x)
    return f"""
<li class="carte">
  <a class="carte-lien" href="{prefixe}{t.slug}/">
    <span class="carte-type">{icone(t.type_cle, 14)}{e(t.libelle_type)}</span>
    <span class="badge {cls} petit">{lib}</span>
    <h3>{e(t.titre_court)}</h3>
    <p class="carte-meta">{e(meta)}</p>
    {f'<p class="carte-resume">{e(t.resume[:230])}{"…" if len(t.resume) > 230 else ""}</p>' if t.resume else ''}
  </a>
</li>"""


def page_liste(type_cle: str, textes: list[Texte], base_url: str,
               intro: str) -> str:
    lib, dossier, pluriel = TYPES[type_cle]
    non_abroges = [t for t in textes if not t.abroge]
    items = "\n".join(carte(t) for t in textes)

    liste_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{pluriel} de l'AMF-UMOA",
        "description": intro[:300],
        "url": f"{base_url.rstrip('/')}/{dossier}/",
        "isPartOf": {"@type": "WebSite", "name": SITE_NOM,
                     "url": base_url.rstrip("/") + "/"},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(textes),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": t.titre,
                 "url": f"{base_url.rstrip('/')}/textes/{t.slug}/"}
                for i, t in enumerate(textes)
            ],
        },
    }

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">{e(pluriel)}</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone(type_cle)}</span>
    <h1>{e(pluriel)}</h1>
    <p class="chapeau">{intro}</p>
    <p class="compte"><strong>{len(textes)}</strong> document{'s' if len(textes) > 1 else ''}
    dans le recueil, dont <strong>{len(non_abroges)}</strong> non
    abrogé{'s' if len(non_abroges) > 1 else ''}.</p>
  </header>
  <ul class="cartes">
{items}
  </ul>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(liste_ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{pluriel} de l'AMF-UMOA — {SITE_COURT}",
                     description=intro, corps=corps, chemin=f"{dossier}/",
                     base_url=base_url, jsonld=jsonld, classe="page-liste")


# --------------------------------------------------------------------------
#  Accueil, chronologie, recherche, à propos
# --------------------------------------------------------------------------

def page_accueil(textes: list[Texte], acteurs: list, base_url: str) -> str:
    par_type = defaultdict(list)
    for t in textes:
        par_type[t.type_cle].append(t)

    base = sorted(par_type.get("base", []), key=lambda x: x.rang)
    base_html = "\n".join(f"""
    <li><a href="textes/{t.slug}/">
      <strong>{e(t.titre_court)}</strong>
      <span>{e(t.date_texte)}</span>
    </a></li>""" for t in base)

    recents = sorted([t for t in textes if t.type_cle in ("instruction", "circulaire",
                                                          "decision")],
                     key=lambda x: x.date_iso or "", reverse=True)[:8]
    recents_html = "\n".join(carte(t, "textes/") for t in recents)

    vignettes = "\n".join(f"""
    <a class="vignette" href="{TYPES[k][1]}/">
      <span class="vignette-icone">{icone(k)}</span>
      <span class="vignette-nombre">{len(par_type.get(k, []))}</span>
      <span class="vignette-nom">{e(TYPES[k][2])}</span>
    </a>""" for k in TYPES if par_type.get(k))

    total_pages = sum(t.pages for t in textes)
    total_car = sum(len(t.texte_brut) for t in textes)
    # Espace fine insécable comme séparateur de milliers, usage français.
    pages_fr = f"{total_pages:,}".replace(",", "\u202f")
    car_fr = f"{total_car:,}".replace(",", "\u202f")

    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NOM,
        "alternateName": SITE_COURT,
        "description": SITE_DESC,
        "url": base_url.rstrip("/") + "/",
        "inLanguage": "fr",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint",
                       "urlTemplate": base_url.rstrip("/") + "/recherche/?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    }

    bloc_acteurs = ""
    if acteurs:
        groupes = acteurs_par_categorie(acteurs)
        colonnes = "\n".join(f"""
    <li><a href="acteurs/{cle}/">
      <strong>{e(CATEGORIES[cle].pluriel)}</strong>
      <span>{len(g)} agréé{'s' if len(g) > 1 else ''}</span>
    </a></li>""" for cle, g in groupes.items())
        bloc_acteurs = f"""
  <section class="bloc-accueil">
    <h2>Qui est qui sur le marché</h2>
    <p class="chapeau">Les {len(acteurs)} acteurs agréés par l'AMF-UMOA, classés
    par métier, avec pour chacun sa fiche et les textes qui le régissent.</p>
    <ul class="liste-base liste-acteurs">
{colonnes}
    </ul>
    <p class="voir-plus"><a href="acteurs/">Annuaire complet et notices par
    catégorie</a></p>
  </section>"""

    corps = f"""
<section class="heros">
  <div class="conteneur">
    <div class="heros-col">
      <h1>{e(SITE_NOM)}</h1>
      <p class="heros-texte">Les textes qui régissent le marché financier régional
      de l'UMOA sont publics, mais diffusés sous forme de documents scannés non
      indexés&nbsp;: introuvables par les moteurs de recherche, impossibles à
      parcourir autrement qu'en ouvrant les fichiers un par un. Ce recueil les
      rend lisibles, cherchables et citables.</p>
      <form class="heros-recherche" action="recherche/" method="get" role="search">
        <label for="q-accueil" class="visuellement-masque">Rechercher dans les textes</label>
        <input type="search" id="q-accueil" name="q" placeholder="Rechercher : agrément SGI, capital minimum, article 37…" autocomplete="off">
        <button type="submit">Rechercher</button>
      </form>
      <p class="heros-chiffres">{len(textes)} documents · {pages_fr} pages ·
      {car_fr} caractères de texte recherchable</p>
    </div>
    <div class="heros-visuel">
{illustration_heros()}
    </div>
  </div>
  {bande_guillochee("guilloche-heros")}
</section>

<div class="conteneur">
  <nav class="vignettes" aria-label="Parcourir par type">
{vignettes}
  </nav>

  <section class="bloc-accueil">
    <h2>Textes de base</h2>
    <p class="chapeau">Le socle du marché financier régional, dans l'ordre de la
    hiérarchie des normes.</p>
    <ul class="liste-base">
{base_html}
    </ul>
  </section>

  <section class="bloc-accueil">
    <h2>Textes d'application les plus récents</h2>
    <ul class="cartes">
{recents_html}
    </ul>
    <p class="voir-plus"><a href="instructions/">Toutes les instructions</a> ·
    <a href="circulaires/">toutes les circulaires</a> ·
    <a href="chronologie/">chronologie complète</a></p>
  </section>

{bloc_acteurs}

  <section class="bloc-accueil encadre">
    <h2>Comment ce recueil est constitué</h2>
    <p>Chaque document provient du site officiel de l'AMF-UMOA. Les fichiers
    scannés ont été soumis à une reconnaissance optique de caractères en
    français, puis restructurés en articles et alinéas afin que le texte figure
    intégralement dans la page — et devienne donc accessible aux moteurs de
    recherche. Le PDF original reste accessible en un clic depuis chaque
    document, et demeure la seule référence faisant foi.</p>
    <p><a href="a-propos/">Méthode détaillée, limites et signalement d'erreurs</a></p>
  </section>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{SITE_NOM}", description=SITE_DESC, corps=corps,
                     chemin="", base_url=base_url, jsonld=jsonld,
                     classe="page-accueil")


def page_chronologie(textes: list[Texte], base_url: str) -> str:
    par_annee = defaultdict(list)
    for t in textes:
        par_annee[t.annee or "Sans date"].append(t)

    sections = []
    for annee in sorted(par_annee, reverse=True):
        lignes = "\n".join(f"""
      <li>
        <a href="../textes/{t.slug}/">
          <span class="chrono-type">{e(t.libelle_type)}</span>
          <span class="chrono-titre">{e(t.titre_court)}</span>
          <span class="chrono-date">{t.pages} p.</span>
        </a>
      </li>""" for t in sorted(par_annee[annee],
                               key=lambda x: x.numero.zfill(8), reverse=True))
        sections.append(f"""
    <section class="chrono-annee">
      <h2 id="a{e(annee)}">{e(annee)} <span class="chrono-compte">{len(par_annee[annee])}</span></h2>
      <ul class="chrono-liste">{lignes}</ul>
    </section>""")

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">Chronologie</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone("chronologie")}</span>
    <h1>Chronologie du corpus</h1>
    <p class="chapeau">L'ensemble des textes du recueil classés par année
    d'adoption ou de publication, du plus récent au plus ancien.</p>
  </header>
{''.join(sections)}
</div>
"""
    return page_html(titre=f"Chronologie des textes — {SITE_COURT}",
                     description="Chronologie complète des textes réglementaires "
                                 "du Marché Financier Régional de l'UMOA.",
                     corps=corps, chemin="chronologie/", base_url=base_url,
                     classe="page-chrono")


def page_recherche(base_url: str) -> str:
    corps = """
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">Recherche</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">__ICONE_RECHERCHE__</span>
    <h1>Rechercher dans le corpus</h1>
    <p class="chapeau">La recherche porte sur le texte intégral de tous les
    documents du recueil, y compris le contenu des pages scannées, ainsi que
    sur l'annuaire des acteurs agréés — dénomination, sigle et numéro
    d'agrément.</p>
  </header>

  <form class="recherche-form" role="search" onsubmit="return false">
    <label for="q" class="visuellement-masque">Termes recherchés</label>
    <input type="search" id="q" name="q" autocomplete="off" autofocus
           placeholder="agrément SGI, capital minimum, blanchiment, article 37…">
    <button type="button" id="vider" aria-label="Effacer">×</button>
  </form>

  <div class="recherche-filtres" id="filtres" hidden>
    <span>Filtrer :</span>
    <button type="button" data-type="" class="actif">Tous</button>
    <button type="button" data-type="base">Textes de base</button>
    <button type="button" data-type="instruction">Instructions</button>
    <button type="button" data-type="circulaire">Circulaires</button>
    <button type="button" data-type="decision">Décisions</button>
    <button type="button" data-type="rapport">Rapports</button>
    <button type="button" data-type="acteur">Acteurs agréés</button>
  </div>

  <p id="etat" class="recherche-etat">Chargement de l'index…</p>
  <ol id="resultats" class="resultats"></ol>
</div>
<script src="../assets/recherche.js" defer></script>
"""
    corps = corps.replace("__ICONE_RECHERCHE__", icone("recherche"))
    return page_html(titre=f"Recherche plein texte — {SITE_COURT}",
                     description="Recherche plein texte dans les instructions, "
                                 "circulaires, décisions et textes de base de "
                                 "l'AMF-UMOA.",
                     corps=corps, chemin="recherche/", base_url=base_url,
                     classe="page-recherche")


def page_apropos(textes: list[Texte], base_url: str) -> str:
    ocr = [t for t in textes if t.mode != "natif"]
    conf = sum(t.confiance for t in ocr) / len(ocr) if ocr else 0
    a_relire = sum(len(t.pages_faibles) for t in textes)

    corps = f"""
<div class="conteneur etroit">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">À propos</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone("apropos")}</span>
    <h1>À propos de ce recueil</h1>
  </header>

  <div class="prose">
    <h2>Pourquoi ce site existe</h2>
    <p>Les textes qui organisent le marché financier régional de l'UMOA sont des
    documents publics. Ils sont mis en ligne par l'AMF-UMOA, mais sous forme
    d'images scannées dépourvues de couche textuelle. Concrètement, cela signifie
    qu'aucun moteur de recherche ne peut en indexer le contenu, qu'on ne peut pas
    y faire une recherche par mot-clé, ni en copier une disposition pour la citer.
    Un praticien qui cherche la règle applicable à une situation donnée doit
    ouvrir les fichiers un par un.</p>
    <p>Ce recueil applique une reconnaissance optique de caractères à ces
    documents et republie le texte obtenu en HTML, où il devient lisible,
    cherchable, citable et indexable. L'objectif est l'accès à la norme, rien de
    plus.</p>

    <h2>Comment il est fabriqué</h2>
    <p>Les documents sont récupérés depuis le site officiel de l'AMF-UMOA. Pour
    chaque page, le pipeline détermine si une couche textuelle exploitable
    existe&nbsp;: dans ce cas le texte est extrait directement. Sinon la page est
    rendue en niveaux de gris à haute résolution, redressée géométriquement, puis
    soumise au moteur Tesseract avec le modèle de langue française le plus précis
    disponible. Les pages dont l'indice de confiance reste faible sont signalées
    et font l'objet d'une relecture manuelle contre l'image d'origine.</p>
    <p>Le texte reconnu est ensuite restructuré&nbsp;: titres, sections, articles,
    alinéas et énumérations sont identifiés afin de produire un balisage
    sémantique. Chaque article reçoit une ancre stable, ce qui permet de pointer
    directement une disposition précise.</p>

    <h2>L'annuaire des acteurs agréés</h2>
    <p>La rubrique «&nbsp;Acteurs&nbsp;» reprend le registre des intervenants
    agréés publié par l'AMF-UMOA, relevé automatiquement chaque mois. Les
    données d'identification — dénomination, catégorie d'agrément, numéro et
    date d'agrément, siège, coordonnées — proviennent intégralement de ce
    registre&nbsp;; le recueil n'y ajoute rien. Ce qu'il apporte est le
    rattachement de chaque catégorie aux textes qui la régissent, et une notice
    expliquant le métier.</p>
    <p>Une réserve. La mention d'activité reprise du registre n'est pas une
    attestation&nbsp;: un agrément peut avoir été retiré, suspendu ou renouvelé
    sans que le relevé le reflète encore, et seul le registre officiel fait foi.
    Les coordonnées, en revanche, sont reprises intégralement — toutes les
    adresses électroniques, tous les numéros —, telles que l'Autorité les
    publie. Une société qui souhaite voir corriger sa fiche peut le signaler,
    mais la correction doit d'abord être faite au registre, qui reste la
    source.</p>

    <h2>Fiabilité et limites</h2>
    <p>La reconnaissance optique n'est jamais parfaite. Sur ce corpus, l'indice de
    confiance moyen s'établit à <strong>{conf:.1f}&nbsp;%</strong> sur les
    {len(ocr)} documents scannés, et {a_relire} page{'s' if a_relire != 1 else ''}
    {'sont' if a_relire != 1 else 'est'} signalée{'s' if a_relire != 1 else ''}
    comme nécessitant une vérification. Les erreurs résiduelles portent
    typiquement sur des caractères isolés, la ponctuation ou la mise en colonnes
    des tableaux.</p>
    <p><strong>Ce site n'a aucune valeur juridique.</strong> Il ne remplace pas
    les documents officiels et n'engage ni l'AMF-UMOA ni aucune autre autorité.
    Avant tout usage professionnel ou contentieux, la disposition citée doit être
    vérifiée sur le PDF original, accessible depuis chaque page du recueil.</p>

    <h2>Sur le statut des textes</h2>
    <p>Le site officiel renseigne pour chaque texte une colonne «&nbsp;État&nbsp;»
    portant la mention «&nbsp;non abrogé&nbsp;». Ce recueil se contente de la
    reprendre, sans la transformer en affirmation de force juridique. La nuance
    n'est pas rhétorique&nbsp;: la présentation du cadre légal par l'Autorité
    indique que sept des soixante-dix instructions adoptées ont été abrogées,
    sans que les données publiées permettent d'identifier lesquelles. Un texte
    affiché comme non abrogé ici peut donc avoir été modifié ou remplacé depuis.
    Vérifiez toujours l'état d'un texte auprès de l'Autorité avant de vous en
    prévaloir.</p>
    <p>Une exception, bornée&nbsp;: lorsqu'un texte publié du recueil prononce
    lui-même, expressément, l'abrogation d'un autre — «&nbsp;la présente
    Instruction abroge l'Instruction 04/97…&nbsp;» —, cette information est
    reportée sur la fiche du texte abrogé, avec la référence de la disposition
    qui la fonde. Le recueil ne déclare ainsi jamais une abrogation de son
    propre chef&nbsp;: il ne fait que rapprocher deux textes publiés, et la
    clause citée reste vérifiable en un clic.</p>

    <h2>Ce qui manque</h2>
    <p>La rubrique «&nbsp;Autres actes&nbsp;» du site officiel est actuellement
    vide. Plusieurs textes cités dans la présentation du cadre légal n'y figurent
    donc pas&nbsp;: le règlement relatif aux obligations sécurisées, celui portant
    sur les fonds communs de titrisation, celui relatif aux titres islamiques et
    aux SUKUK, ainsi que la décision portant adoption de la loi uniforme relative
    aux infractions boursières. Ces textes émanent du Conseil des Ministres de
    l'UEMOA et devront être recherchés auprès des sources de l'Union.</p>

    <h2>Signaler une erreur</h2>
    <p>Toute erreur de transcription constatée peut être signalée. Le corpus est
    régénérable intégralement à partir des sources officielles, et les
    corrections sont réappliquées à chaque reconstruction.</p>

    <h2>Sources</h2>
    <p>L'intégralité des documents provient du site de l'{e(AUTORITE)}
    (<a href="https://www.amf-umoa.org/" rel="noopener external">amf-umoa.org</a>).
    Les textes de loi et actes réglementaires sont des documents publics. Ce
    recueil en facilite l'accès sans en modifier la substance.</p>
  </div>
</div>
"""
    return page_html(titre=f"À propos et méthode — {SITE_COURT}",
                     description="Méthode de constitution du recueil, fiabilité "
                                 "de la reconnaissance optique, limites et "
                                 "avertissement juridique.",
                     corps=corps, chemin="a-propos/", base_url=base_url,
                     classe="page-apropos")


# --------------------------------------------------------------------------
#  Acteurs agréés
# --------------------------------------------------------------------------

ACTEURS_INTRO = (
    "Nul ne peut exercer sur le Marché Financier Régional sans un agrément ou "
    "une habilitation de l'AMF-UMOA. Cette rubrique reprend le registre des "
    "acteurs agréés tenu par l'Autorité et le met en regard des textes qui "
    "régissent chaque métier : qui négocie les titres, qui les conserve, qui "
    "gère les fonds, qui accompagne les émetteurs, qui garantit et qui note."
)


# Les résumés du corpus reprennent l'intitulé officiel, saisi en capitales et
# précédé de la référence de l'acte. Sur une liste de renvois, seule importe la
# matière : on retire donc la référence et la formule d'attaque.
_ATTAQUE = re.compile(
    r"^\s*(?:(?:instruction|circulaire|d[ée]cision|r[èe]glement)[^,;]{0,60}?"
    r"(?:n[°o]\s*[\w/.-]+)?\s*)?"
    r"(?:est\s+)?(?:relative?\s+(?:aux?|[àa]|au)|portant|applicable\s+aux?)\s+",
    re.I)


def objet_court(resume: str, limite: int = 115) -> str:
    """Matière d'un texte, sans sa référence ni sa formule d'attaque."""
    t = titre_propre(" ".join((resume or "").split()))
    t = _ATTAQUE.sub("", t).strip(" .,;:")
    t = re.sub(r"^(?:l'|la |le |les |des |du |de la |de |aux |au |a )", "", t,
               flags=re.I)
    if len(t) > limite:
        t = t[:limite].rsplit(" ", 1)[0].rstrip(" .,;:") + "…"
    # Les résumés du corpus sont eux-mêmes tronqués et se terminent parfois sur
    # un mot amputé (« en dehors de l'etat de leur s ») : on le retire.
    mots = t.split(" ")
    if len(mots) > 3 and 0 < len(mots[-1]) <= 2 and mots[-1].isalpha():
        t = " ".join(mots[:-1]) + "…"
    return (t[:1].upper() + t[1:]) if t else ""


def _renvois_textes(slugs, textes_par_slug, prefixe: str,
                    legendes: dict[str, str] | None = None) -> str:
    """Liste de renvois vers les textes du recueil, ignorant les absents."""
    lignes = []
    for s in slugs:
        t = textes_par_slug.get(s)
        if not t:
            continue
        legende = (legendes or {}).get(s) or objet_court(t.resume)
        lignes.append(
            f'<li><a href="{prefixe}{t.slug}/">{e(t.titre_court)}</a>'
            + (f'<span class="renvoi-objet">{e(legende[:160])}</span>'
               if legende else "")
            + "</li>")
    return "\n".join(lignes)


def _ligne_annuaire(a, dans_categorie: bool = False) -> str:
    """Une ligne d'annuaire. Depuis une page de catégorie, le lien est relatif
    au dossier de la catégorie ; depuis la page d'ensemble, il le préfixe."""
    cible = f"{a.slug}/" if dans_categorie else f"{a.chemin}/"
    _, cls = a.statut
    lib = "Actif" if a.actif else "Non actif"
    pays = e(a.pays)
    return (
        f'<tr data-cat="{a.categorie}" data-pays="{e(a.pays_code)}" '
        f'data-actif="{"1" if a.actif else "0"}" '
        # Le champ de recherche compare en capitales sans accent : l'attribut
        # doit l'être aussi, sans quoi « sénégal » ne trouve rien.
        f'data-nom="{e(sans_accent(a.nom + " " + a.cat.sigle + " " + a.pays + " " + a.agrement).upper())}">'
        f'<td class="an-nom"><a href="{cible}">{e(a.nom)}</a></td>'
        f'<td class="an-cat"><span class="sigle" title="{e(a.cat.singulier)}">'
        f'{e(a.cat.sigle)}</span></td>'
        f'<td class="an-pays">{pays}</td>'
        f'<td class="an-agr">{e(a.agrement) or "—"}</td>'
        f'<td class="an-date">{e(a.date_agrement[:4]) or "—"}</td>'
        f'<td class="an-etat"><span class="badge {cls} petit">{lib}</span></td>'
        "</tr>")


def page_acteurs(acteurs: list, releve: str, textes: list[Texte],
                 base_url: str) -> str:
    groupes = acteurs_par_categorie(acteurs)
    par_slug = {t.slug: t for t in textes}
    actifs = [a for a in acteurs if a.actif]
    pays = sorted({(a.pays_code, a.pays) for a in acteurs}, key=lambda x: x[1])

    vignettes = "\n".join(f"""
    <a class="vignette" href="{cle}/">
      <span class="vignette-icone">{icone(CATEGORIES[cle].icone, 26)}</span>
      <span class="vignette-nombre">{len(g)}</span>
      <span class="vignette-nom">{e(CATEGORIES[cle].court)}</span>
    </a>""" for cle, g in groupes.items())

    sections = "\n".join(f"""
  <section class="cat-bloc" id="{cle}">
    <h2><a href="{cle}/">{e(CATEGORIES[cle].pluriel)}</a>
      <span class="cat-sigle">{e(CATEGORIES[cle].sigle)}</span></h2>
    <p class="cat-role">{e(CATEGORIES[cle].role)}</p>
    <p class="cat-compte">{len(g)} inscrit{'s' if len(g) > 1 else ''} au registre,
      dont {sum(1 for a in g if a.actif)} en activité ·
      <a href="{cle}/">Voir la notice et la liste</a></p>
  </section>""" for cle, g in groupes.items())

    filtres_cat = "\n".join(
        f'<option value="{cle}">{e(CATEGORIES[cle].pluriel)}</option>'
        for cle in groupes)
    filtres_pays = "\n".join(f'<option value="{e(c)}">{e(n)}</option>'
                             for c, n in pays)
    lignes = "\n".join(_ligne_annuaire(a) for a in acteurs)

    communs = _renvois_textes([s for s, _ in TEXTES_COMMUNS], par_slug,
                              "../textes/", dict(TEXTES_COMMUNS))

    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Acteurs agréés du Marché Financier Régional de l'UMOA",
        "description": ACTEURS_INTRO[:300],
        "url": f"{base_url.rstrip('/')}/acteurs/",
        "isPartOf": {"@type": "WebSite", "name": SITE_NOM,
                     "url": base_url.rstrip("/") + "/"},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(acteurs)},
    }

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">Acteurs agréés</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone("acteurs")}</span>
    <h1>Acteurs agréés du marché</h1>
    <p class="chapeau">{ACTEURS_INTRO}</p>
    <p class="compte"><strong>{len(acteurs)}</strong> inscriptions au registre,
    dont <strong>{len(actifs)}</strong> en activité, réparties en
    <strong>{len(groupes)}</strong> catégories d'agrément.
    Relevé du {date_francaise(releve)}.</p>
  </header>

  <nav class="vignettes" aria-label="Catégories d'acteurs">
{vignettes}
  </nav>

  <section class="annuaire" id="annuaire">
    <h2>Annuaire</h2>
    <form class="an-filtres" role="search" onsubmit="return false">
      <p class="an-champ">
        <label for="an-q">Chercher un acteur</label>
        <input type="search" id="an-q" placeholder="Nom, sigle, numéro d'agrément…"
               autocomplete="off" spellcheck="false">
      </p>
      <p class="an-champ">
        <label for="an-cat">Catégorie</label>
        <select id="an-cat"><option value="">Toutes</option>
{filtres_cat}
        </select>
      </p>
      <p class="an-champ">
        <label for="an-pays">Pays du siège</label>
        <select id="an-pays"><option value="">Tous</option>
{filtres_pays}
        </select>
      </p>
      <p class="an-champ an-bascule">
        <label for="an-actifs">
          <input type="checkbox" id="an-actifs" checked>
          Masquer les inscriptions non actives
        </label>
      </p>
    </form>
    <p class="an-etat" id="an-etat" role="status" aria-live="polite"></p>
    <div class="an-cadre">
      <table class="an-table" id="an-table" data-objet="acteur">
        <thead>
          <tr><th scope="col">Dénomination</th><th scope="col">Catégorie</th>
          <th scope="col">Pays</th><th scope="col">Agrément</th>
          <th scope="col">Depuis</th><th scope="col">État</th></tr>
        </thead>
        <tbody>
{lignes}
        </tbody>
      </table>
    </div>
    <p class="an-note">L'état indiqué reprend celui du registre de l'Autorité au
    jour du relevé. Il ne vaut pas attestation&nbsp;: seul le registre officiel
    fait foi.</p>
  </section>

  <section class="cat-blocs">
    <h2 class="titre-rang">Les métiers du marché</h2>
{sections}
  </section>

  <section class="textes-lies" id="textes-communs">
    <h2>Textes communs à tous les acteurs agréés</h2>
    <p class="renvoi-avis">Quelle que soit la catégorie, ces textes s'appliquent
    à l'ensemble des intervenants agréés.</p>
    <ul class="textes-lies-liste">
{communs}
    </ul>
  </section>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"Acteurs agréés du marché financier régional — {SITE_COURT}",
                     description=ACTEURS_INTRO, corps=corps, chemin="acteurs/",
                     base_url=base_url, jsonld=jsonld, classe="page-acteurs",
                     script_annuaire=True)


def page_categorie_acteurs(cle: str, groupe: list, tous: list,
                           textes: list[Texte], releve: str,
                           base_url: str) -> str:
    cat = CATEGORIES[cle]
    par_slug = {t.slug: t for t in textes}
    actifs = [a for a in groupe if a.actif]
    notice = "\n".join(f"<p>{e(p)}</p>" for p in cat.notice)
    lignes = "\n".join(_ligne_annuaire(a, dans_categorie=True) for a in groupe)
    renvois = _renvois_textes(cat.textes, par_slug, "../../textes/")

    autres = "\n".join(
        f'<a href="../{c}/">{e(CATEGORIES[c].pluriel)}</a>'
        for c in ORDRE_CATEGORIES if c != cle and any(x.categorie == c for x in tous))

    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{cat.pluriel} agréées sur le marché financier régional de l'UMOA",
        "description": cat.role,
        "url": f"{base_url.rstrip('/')}/acteurs/{cle}/",
        "mainEntity": {
            "@type": "ItemList", "numberOfItems": len(groupe),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": a.nom,
                 "url": f"{base_url.rstrip('/')}/acteurs/{a.chemin}/"}
                for i, a in enumerate(groupe)],
        },
    }

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../../">Accueil</a> <span>›</span>
    <a href="../">Acteurs agréés</a> <span>›</span>
    <span aria-current="page">{e(cat.pluriel)}</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone(cat.icone)}</span>
    <p class="surtitre">{e(cat.sigle)}</p>
    <h1>{e(cat.pluriel)}</h1>
    <p class="chapeau">{e(cat.role)}</p>
    <p class="compte"><strong>{len(groupe)}</strong> inscription{'s' if len(groupe) > 1 else ''}
    au registre, dont <strong>{len(actifs)}</strong> en activité.
    Relevé du {date_francaise(releve)}.</p>
  </header>

  <section class="cat-notice prose">
    <h2>Ce que recouvre le métier</h2>
{notice}
  </section>

  <section class="textes-lies">
    <h2>Textes applicables</h2>
    <ul class="textes-lies-liste">
{renvois}
    </ul>
    <p class="renvoi-plus"><a href="../#textes-communs">Textes communs à tous
    les acteurs agréés</a></p>
  </section>

  <section class="annuaire">
    <h2>{e(cat.pluriel)} au registre</h2>
    <div class="an-cadre">
      <table class="an-table">
        <thead>
          <tr><th scope="col">Dénomination</th><th scope="col">Catégorie</th>
          <th scope="col">Pays</th><th scope="col">Agrément</th>
          <th scope="col">Depuis</th><th scope="col">État</th></tr>
        </thead>
        <tbody>
{lignes}
        </tbody>
      </table>
    </div>
  </section>

  <nav class="cat-autres" aria-label="Autres catégories">
    <h2>Autres catégories</h2>
    <p>{autres}</p>
  </nav>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{cat.pluriel} agréées ({cat.sigle}) — {SITE_COURT}",
                     description=f"{cat.role} {len(groupe)} inscriptions au "
                                 f"registre de l'AMF-UMOA.",
                     corps=corps, chemin=f"acteurs/{cle}/", base_url=base_url,
                     jsonld=jsonld, classe="page-categorie")


def _fiche_ligne(intitule: str, valeur: str) -> str:
    return (f"<div class=\"fiche-ligne\"><dt>{intitule}</dt>"
            f"<dd>{valeur}</dd></div>") if valeur else ""


def page_acteur(a, tous: list, textes: list[Texte], releve: str,
                base_url: str, gens: list | None = None,
                fonds: list | None = None) -> str:
    cat = a.cat
    par_slug = {t.slug: t for t in textes}
    lib, cls = a.statut

    feminin = cat.genre == "f"
    determinant = "une" if feminin else "un"
    accord = "e" if feminin else ""
    depuis = (f" depuis le {date_francaise(a.date_agrement)}"
              if a.date_agrement else "")
    chapeau = (f"{a.nom} est {determinant} {cat.singulier.lower()} "
               f"inscrit{accord} au registre des acteurs agréés du Marché "
               f"Financier Régional de l'UMOA{depuis}. {cat.role}")

    identite = "".join([
        _fiche_ligne("Catégorie",
                     f'<a href="../">{e(cat.singulier)}</a> '
                     f'<span class="sigle">{e(cat.sigle)}</span>'),
        _fiche_ligne("Numéro d'agrément", e(a.agrement)),
        _fiche_ligne("Date d'agrément", date_francaise(a.date_agrement)),
        _fiche_ligne("Entrée sur le marché", date_francaise(a.date_entree_marche)),
        _fiche_ligne("Constitution", date_francaise(a.date_creation)),
        _fiche_ligne("Forme juridique", e(a.forme_juridique)),
        _fiche_ligne("Registre du commerce", f"<span class=\"mono\">{e(a.rccm)}</span>"
                     if a.rccm else ""),
        _fiche_ligne("Pays du siège", e(a.pays)
                     + (" <span class=\"hors-umoa\">hors UMOA</span>"
                        if a.hors_umoa else "")),
        _fiche_ligne("Siège", e(a.siege)),
        _fiche_ligne("Boîte postale", e(a.boite_postale)),
        _fiche_ligne("Référence au registre",
                     f'<span class="mono">{e(a.code)}</span>' if a.code else ""),
        _fiche_ligne("Décision d'agrément",
                     f'<span class="mono">{e(a.decision.rsplit(".", 1)[0])}</span>'
                     '<span class="fiche-glose">référence de la décision au '
                     "registre&nbsp;; l'Autorité n'en publie pas le texte</span>"
                     if a.decision else ""),
        _fiche_ligne("Registre officiel",
                     '<a href="https://www.amf-umoa.org/accueil/intervenant" '
                     'rel="noopener external">Fiche à l\'AMF-UMOA</a>'),
    ])

    def _liste(valeurs, rendu) -> str:
        return ('<ul class="fiche-valeurs">'
                + "".join(f"<li>{rendu(v)}</li>" for v in valeurs)
                + "</ul>") if valeurs else ""

    contact = "".join([
        _fiche_ligne("Site web",
                     f'<a href="{e(a.site_web)}" rel="noopener nofollow external">'
                     f'{e(a.site_web.split("//")[-1].rstrip("/"))}</a>'
                     if a.site_web else ""),
        _fiche_ligne("Courriel" + ("s" if len(a.courriels) > 1 else ""),
                     _liste(a.courriels,
                            lambda v: f'<a href="mailto:{e(v)}">{e(v)}</a>')),
        _fiche_ligne("Téléphone" + ("s" if len(a.telephones) > 1 else ""),
                     _liste(a.telephones, e)),
        _fiche_ligne("Télécopie", _liste(a.fax, e)),
    ])

    liens = acteurs_homologues(a, tous)
    bloc_liens = ""
    if liens:
        items = "\n".join(
            f'<li><a href="../../{b.chemin}/">{e(b.nom)}</a>'
            f'<span class="renvoi-objet">{e(b.cat.singulier)}</span></li>'
            for b in liens)
        bloc_liens = f"""
  <section class="textes-lies">
    <h2>Autres agréments de la même société</h2>
    <p class="renvoi-avis">Un même établissement peut détenir plusieurs
    agréments, chacun ouvrant un métier distinct.</p>
    <ul class="textes-lies-liste">
{items}
    </ul>
  </section>"""

    bloc_gens = bloc_personnes_acteur(gens or [])

    bloc_fonds = ""
    if fonds:
        items = "\n".join(
            f'<li><a href="../../../opc/{o.chemin}/">{e(o.nom_lisible)}</a>'
            f'<span class="renvoi-objet">{e(o.fam.singulier)}'
            f'{"" if o.actif else " · clos"}</span></li>'
            for o in sorted(fonds, key=lambda x: (0 if x.actif else 1, x.nom))[:30])
        bloc_fonds = f"""
  <section class="textes-lies">
    <h2>Organismes gérés</h2>
    <p class="renvoi-avis">{len(fonds)} organismes de placement collectif sont
    agréés sous la gestion de cette société.</p>
    <ul class="textes-lies-liste">
{items}
    </ul>
  </section>"""

    renvois = _renvois_textes(cat.textes[:8], par_slug, "../../../textes/")

    ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": a.nom,
        "description": chapeau[:300],
        "url": f"{base_url.rstrip('/')}/acteurs/{a.chemin}/",
        "address": {"@type": "PostalAddress", "addressCountry": a.pays,
                    "streetAddress": a.siege} if a.siege else None,
        "sameAs": [a.site_web] if a.site_web else None,
    }
    ld = {k: v for k, v in ld.items() if v is not None}

    corps = f"""
<div class="conteneur conteneur-fiche">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../../../">Accueil</a> <span>›</span>
    <a href="../../">Acteurs agréés</a> <span>›</span>
    <a href="../">{e(cat.pluriel)}</a> <span>›</span>
    <span aria-current="page">{e(a.nom)}</span>
  </nav>

  <header class="acteur-entete">
    <p class="surtitre">{icone(cat.icone, 15)}{e(cat.singulier)}</p>
    <h1>{e(a.nom)}</h1>
    <p class="acteur-etat"><span class="badge {cls}">{lib}</span>
      <span class="acteur-pays">{e(a.pays)}</span></p>
    <p class="chapeau">{e(chapeau)}</p>
  </header>

  <section class="fiche-bloc">
    <h2>Identification</h2>
    <dl class="fiche-dl">
{identite}
    </dl>
  </section>

  {f'''<section class="fiche-bloc">
    <h2>Coordonnées</h2>
    <dl class="fiche-dl">
{contact}
    </dl>
    <p class="fiche-note">Toutes les coordonnées publiées au registre de
    l'Autorité sont reprises ici, sans tri&nbsp;; elles peuvent avoir changé
    depuis le relevé.</p>
  </section>''' if contact else ''}

  <section class="textes-lies">
    <h2>Textes applicables</h2>
    <ul class="textes-lies-liste">
{renvois}
    </ul>
    <p class="renvoi-plus"><a href="../">Notice complète de la catégorie</a></p>
  </section>
{bloc_fonds}
{bloc_gens}
{bloc_liens}

  <section class="fiche-source">
    <h2>Source</h2>
    <p>Fiche établie à partir du registre des acteurs agréés publié par
    l'AMF-UMOA, relevé du {date_francaise(releve)}. Le recueil n'ajoute aucune
    donnée à ce registre&nbsp;: il le met en regard des textes applicables.
    Pour toute vérification, consulter le
    <a href="https://www.amf-umoa.org/accueil/intervenant" rel="noopener external">registre
    officiel de l'Autorité</a>.</p>
  </section>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{a.nom} — {cat.sigle} agréé{accord} auprès de "
                           f"l'AMF-UMOA — {SITE_COURT}",
                     description=chapeau, corps=corps,
                     chemin=f"acteurs/{a.chemin}/", base_url=base_url,
                     jsonld=jsonld, classe="page-acteur")


# --------------------------------------------------------------------------
#  Organismes de placement collectif
# --------------------------------------------------------------------------

OPC_INTRO = (
    "Un organisme de placement collectif met en commun l'épargne de plusieurs "
    "investisseurs pour l'employer sur le marché. Chacun de ceux qui figurent "
    "ici a reçu un agrément de l'AMF-UMOA, distinct de celui de la société qui "
    "le gère : cette rubrique les recense, les rattache à leur gérant et "
    "renvoie aux textes qui encadrent leur fonctionnement."
)


def _ligne_opc(o, dans_famille: bool = False) -> str:
    cible = f"{o.slug}/" if dans_famille else f"{o.chemin}/"
    lib, cls = o.statut
    court = "En vigueur" if o.actif else "Clos"
    return (
        f'<tr data-cat="{o.famille}" data-pays="" '
        f'data-actif="{"1" if o.actif else "0"}" '
        f'data-nom="{e(sans_accent(o.nom + " " + o.fam.sigle + " " + o.societe_gestion + " " + o.agrement).upper())}">'
        f'<td class="an-nom"><a href="{cible}">{e(o.nom_lisible)}</a></td>'
        f'<td class="an-cat"><span class="sigle" title="{e(o.fam.singulier)}">'
        f'{e(o.fam.sigle)}</span></td>'
        f'<td class="an-pays">{e(o.societe_gestion)}</td>'
        f'<td class="an-agr">{e(o.agrement) or "—"}</td>'
        f'<td class="an-date">{e(o.date_agrement[:4]) or "—"}</td>'
        f'<td class="an-etat"><span class="badge {cls} petit">{court}</span></td>'
        "</tr>")


_EN_TETE_OPC = ('<tr><th scope="col">Dénomination</th><th scope="col">Famille</th>'
                '<th scope="col">Société de gestion</th><th scope="col">Agrément</th>'
                '<th scope="col">Depuis</th><th scope="col">État</th></tr>')


def page_opc(opc: list, releve: str, textes: list[Texte], base_url: str) -> str:
    groupes = opc_par_famille(opc)
    par_slug = {t.slug: t for t in textes}
    en_vigueur = [o for o in opc if o.actif]
    societes = sorted({o.societe_gestion for o in opc if o.societe_gestion})

    vignettes = "\n".join(f"""
    <a class="vignette" href="{cle}/">
      <span class="vignette-icone">{icone(FAMILLES[cle].icone, 26)}</span>
      <span class="vignette-nombre">{len(g)}</span>
      <span class="vignette-nom">{e(FAMILLES[cle].court)}</span>
    </a>""" for cle, g in groupes.items())

    sections = "\n".join(f"""
  <section class="cat-bloc" id="{cle}">
    <h2><a href="{cle}/">{e(FAMILLES[cle].pluriel)}</a>
      <span class="cat-sigle">{e(FAMILLES[cle].sigle)}</span></h2>
    <p class="cat-role">{e(FAMILLES[cle].role)}</p>
    <p class="cat-compte">{len(g)} agréé{'s' if len(g) > 1 else ''},
      dont {sum(1 for o in g if o.actif)} en vigueur ·
      <a href="{cle}/">Voir la notice et la liste</a></p>
  </section>""" for cle, g in groupes.items())

    filtres_fam = "\n".join(
        f'<option value="{cle}">{e(FAMILLES[cle].pluriel)}</option>'
        for cle in groupes)
    filtres_sg = "\n".join(f'<option value="{e(s)}">{e(s)}</option>'
                           for s in societes)
    lignes = "\n".join(_ligne_opc(o) for o in opc)
    communs = _renvois_textes([s for s, _ in OPC_TEXTES_COMMUNS], par_slug,
                              "../textes/", dict(OPC_TEXTES_COMMUNS))

    ld = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": "Organismes de placement collectif agréés de l'UMOA",
        "description": OPC_INTRO[:300],
        "url": f"{base_url.rstrip('/')}/opc/",
        "isPartOf": {"@type": "WebSite", "name": SITE_NOM,
                     "url": base_url.rstrip("/") + "/"},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(opc)},
    }

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">Organismes de placement collectif</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone("sgo")}</span>
    <h1>Organismes de placement collectif</h1>
    <p class="chapeau">{OPC_INTRO}</p>
    <p class="compte"><strong>{len(opc)}</strong> organismes agréés, dont
    <strong>{len(en_vigueur)}</strong> en vigueur, gérés par
    <strong>{len(societes)}</strong> sociétés de gestion.
    Relevé du {date_francaise(releve)}.</p>
  </header>

  <nav class="vignettes" aria-label="Familles d'organismes">
{vignettes}
  </nav>

  <section class="annuaire" id="annuaire">
    <h2>Répertoire</h2>
    <form class="an-filtres" role="search" onsubmit="return false">
      <p class="an-champ">
        <label for="an-q">Chercher un organisme</label>
        <input type="search" id="an-q" placeholder="Nom, société de gestion, agrément…"
               autocomplete="off" spellcheck="false">
      </p>
      <p class="an-champ">
        <label for="an-cat">Famille</label>
        <select id="an-cat"><option value="">Toutes</option>
{filtres_fam}
        </select>
      </p>
      <p class="an-champ">
        <label for="an-pays">Société de gestion</label>
        <select id="an-pays"><option value="">Toutes</option>
{filtres_sg}
        </select>
      </p>
      <p class="an-champ an-bascule">
        <label for="an-actifs">
          <input type="checkbox" id="an-actifs" checked>
          Masquer les organismes clos
        </label>
      </p>
    </form>
    <p class="an-etat" id="an-etat" role="status" aria-live="polite"></p>
    <div class="an-cadre">
      <table class="an-table" id="an-table" data-objet="organisme">
        <thead>{_EN_TETE_OPC}</thead>
        <tbody>
{lignes}
        </tbody>
      </table>
    </div>
    <p class="an-note">L'état reprend celui du registre de l'Autorité au jour du
    relevé. Un organisme clos peut rester en cours de liquidation&nbsp;; seul le
    registre officiel fait foi.</p>
  </section>

  <section class="cat-blocs">
    <h2 class="titre-rang">Les familles d'organismes</h2>
{sections}
  </section>

  <section class="textes-lies" id="textes-communs">
    <h2>Textes régissant la gestion collective</h2>
    <p class="renvoi-avis">Le régime a été refondu en 2021 puis précisé par une
    série de circulaires en 2022, qui couvrent l'agrément, l'information de
    l'investisseur, les frais, l'évaluation et les risques.</p>
    <ul class="textes-lies-liste">
{communs}
    </ul>
  </section>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"Organismes de placement collectif agréés — {SITE_COURT}",
                     description=OPC_INTRO, corps=corps, chemin="opc/",
                     base_url=base_url, jsonld=jsonld, classe="page-acteurs",
                     script_annuaire=True)


def page_famille_opc(cle: str, groupe: list, tous: list, textes: list[Texte],
                     releve: str, base_url: str) -> str:
    fam = FAMILLES[cle]
    par_slug = {t.slug: t for t in textes}
    en_vigueur = [o for o in groupe if o.actif]
    notice = "\n".join(f"<p>{e(p)}</p>" for p in fam.notice)
    lignes = "\n".join(_ligne_opc(o, dans_famille=True) for o in groupe)
    renvois = _renvois_textes(fam.textes, par_slug, "../../textes/")
    autres = "\n".join(
        f'<a href="../{c}/">{e(FAMILLES[c].pluriel)}</a>'
        for c in ORDRE_FAMILLES if c != cle and any(x.famille == c for x in tous))

    ld = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": f"{fam.pluriel} agréés sur le marché financier régional",
        "description": fam.role,
        "url": f"{base_url.rstrip('/')}/opc/{cle}/",
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(groupe)},
    }

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../../">Accueil</a> <span>›</span>
    <a href="../">Organismes de placement collectif</a> <span>›</span>
    <span aria-current="page">{e(fam.pluriel)}</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone(fam.icone)}</span>
    <p class="surtitre">{e(fam.sigle)}</p>
    <h1>{e(fam.pluriel)}</h1>
    <p class="chapeau">{e(fam.role)}</p>
    <p class="compte"><strong>{len(groupe)}</strong> agréé{'s' if len(groupe) > 1 else ''},
    dont <strong>{len(en_vigueur)}</strong> en vigueur.
    Relevé du {date_francaise(releve)}.</p>
  </header>

  <section class="cat-notice prose">
    <h2>Ce que recouvre la famille</h2>
{notice}
  </section>

  <section class="textes-lies">
    <h2>Textes applicables</h2>
    <ul class="textes-lies-liste">
{renvois}
    </ul>
    <p class="renvoi-plus"><a href="../#textes-communs">Textes communs à la
    gestion collective</a></p>
  </section>

  <section class="annuaire">
    <h2>{e(fam.pluriel)} au registre</h2>
    <div class="an-cadre">
      <table class="an-table">
        <thead>{_EN_TETE_OPC}</thead>
        <tbody>
{lignes}
        </tbody>
      </table>
    </div>
  </section>

  <nav class="cat-autres" aria-label="Autres familles">
    <h2>Autres familles</h2>
    <p>{autres}</p>
  </nav>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{fam.pluriel} agréés ({fam.sigle}) — {SITE_COURT}",
                     description=f"{fam.role} {len(groupe)} agréés au registre "
                                 f"de l'AMF-UMOA.",
                     corps=corps, chemin=f"opc/{cle}/", base_url=base_url,
                     jsonld=jsonld, classe="page-categorie")


def page_opc_fiche(o, tous: list, acteurs: list, textes: list[Texte],
                   releve: str, base_url: str) -> str:
    fam = o.fam
    par_slug = {t.slug: t for t in textes}
    lib, cls = o.statut
    accord = "e" if fam.genre == "f" else ""
    determinant = "une" if fam.genre == "f" else "un"

    gerant = next((a for a in acteurs if a.id == o.societe_gestion_id), None)
    depuis = f" depuis le {date_francaise(o.date_agrement)}" if o.date_agrement else ""
    chapeau = (f"{o.nom_lisible} est {determinant} {fam.singulier.lower()} agréé"
               f"{accord} par l'AMF-UMOA{depuis}"
               + (f", géré par {o.societe_gestion}." if o.societe_gestion else ".")
               + f" {fam.role}")

    lien_gerant = (f'<a href="../../../acteurs/{gerant.chemin}/">{e(o.societe_gestion)}</a>'
                   if gerant else e(o.societe_gestion))

    identite = "".join([
        _fiche_ligne("Famille",
                     f'<a href="../">{e(fam.singulier)}</a> '
                     f'<span class="sigle">{e(fam.sigle)}</span>'),
        _fiche_ligne("Société de gestion", lien_gerant),
        _fiche_ligne("Numéro d'agrément", e(o.agrement)),
        _fiche_ligne("Date d'agrément", date_francaise(o.date_agrement)),
        _fiche_ligne("Référence au registre",
                     f'<span class="mono">{e(o.code)}</span>' if o.code else ""),
        _fiche_ligne("Note d'information",
                     f'<span class="mono">{e(o.note_information.rsplit(".", 1)[0])}</span>'
                     '<span class="fiche-glose">référence au registre&nbsp;; '
                     "l'Autorité n'en publie pas le texte</span>"
                     if o.note_information else ""),
        _fiche_ligne("Décision d'agrément",
                     f'<span class="mono">{e(o.decision.rsplit(".", 1)[0])}</span>'
                     if o.decision else ""),
        _fiche_ligne("Registre officiel",
                     '<a href="https://www.amf-umoa.org/accueil/opcvm" '
                     'rel="noopener external">Fiche à l\'AMF-UMOA</a>'),
    ])

    freres = [x for x in tous
              if x.societe_gestion_id == o.societe_gestion_id and x.chemin != o.chemin]
    bloc_freres = ""
    if freres:
        items = "\n".join(
            f'<li><a href="../../{x.chemin}/">{e(x.nom_lisible)}</a>'
            f'<span class="renvoi-objet">{e(x.fam.singulier)}'
            f'{"" if x.actif else " · clos"}</span></li>'
            for x in sorted(freres, key=lambda y: (0 if y.actif else 1, y.nom))[:20])
        bloc_freres = f"""
  <section class="textes-lies">
    <h2>Autres organismes de la même société de gestion</h2>
    <p class="renvoi-avis">{e(o.societe_gestion)} gère {len(freres) + 1} organismes
    inscrits au registre.</p>
    <ul class="textes-lies-liste">
{items}
    </ul>
  </section>"""

    renvois = _renvois_textes(fam.textes[:8], par_slug, "../../../textes/")

    ld = {
        "@context": "https://schema.org", "@type": "FinancialProduct",
        "name": o.nom_lisible, "description": chapeau[:300],
        "url": f"{base_url.rstrip('/')}/opc/{o.chemin}/",
        "provider": {"@type": "Organization", "name": o.societe_gestion}
        if o.societe_gestion else None,
    }
    ld = {k: v for k, v in ld.items() if v is not None}

    corps = f"""
<div class="conteneur conteneur-fiche">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../../../">Accueil</a> <span>›</span>
    <a href="../../">Organismes de placement collectif</a> <span>›</span>
    <a href="../">{e(fam.pluriel)}</a> <span>›</span>
    <span aria-current="page">{e(o.nom_lisible)}</span>
  </nav>

  <header class="acteur-entete">
    <p class="surtitre">{icone(fam.icone, 15)}{e(fam.singulier)}</p>
    <h1>{e(o.nom_lisible)}</h1>
    <p class="acteur-etat"><span class="badge {cls}">{lib}</span>
      <span class="acteur-pays">{e(o.societe_gestion)}</span></p>
    <p class="chapeau">{e(chapeau)}</p>
  </header>

  <section class="fiche-bloc">
    <h2>Identification</h2>
    <dl class="fiche-dl">
{identite}
    </dl>
    <p class="fiche-note">L'intitulé est celui du registre, rendu lisible sans
    en modifier la substance&nbsp;: les taux, les millésimes et les mentions de
    compartiment sont conservés tels quels.</p>
  </section>

  <section class="textes-lies">
    <h2>Textes applicables</h2>
    <ul class="textes-lies-liste">
{renvois}
    </ul>
    <p class="renvoi-plus"><a href="../">Notice complète de la famille</a></p>
  </section>
{bloc_freres}

  <section class="fiche-source">
    <h2>Source</h2>
    <p>Fiche établie à partir du registre des organismes de placement collectif
    publié par l'AMF-UMOA, relevé du {date_francaise(releve)}. Ce recueil
    n'ajoute rien à ce registre&nbsp;: il le met en regard des textes
    applicables et le relie à la société de gestion. Ni valeur liquidative ni
    performance ne sont publiées ici&nbsp;: l'Autorité ne les diffuse pas.</p>
  </section>
</div>
"""
    jsonld = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return page_html(titre=f"{o.nom_lisible} — {fam.sigle} agréé{accord} "
                           f"AMF-UMOA — {SITE_COURT}",
                     description=chapeau, corps=corps,
                     chemin=f"opc/{o.chemin}/", base_url=base_url,
                     jsonld=jsonld, classe="page-acteur")


# --------------------------------------------------------------------------
#  Personnes
# --------------------------------------------------------------------------

PERSONNES_INTRO = (
    "Exercer une fonction réglementée sur le marché suppose une carte "
    "professionnelle délivrée par l'AMF-UMOA. Ce répertoire réunit les "
    "titulaires que le registre de l'Autorité rattache à chaque acteur agréé "
    "et les dirigeants relevés par le recueil dans des sources publiques."
)


def _ligne_personne(p) -> str:
    lien = (f'<a href="../acteurs/{p.societe_chemin}/">{e(p.societe)}</a>'
            if p.societe_chemin else e(p.societe))
    etat = "En fonction" if p.actif else "Non actif"
    cls = "actif" if p.actif else "inactif"
    return (
        f'<tr data-cat="{p.famille}" data-pays="{e(_cle_pays(p.pays))}" '
        f'data-actif="{"1" if p.actif else "0"}" '
        f'data-nom="{e(sans_accent(p.nom_complet + " " + p.societe + " " + p.fonction + " " + p.pays).upper())}">'
        f'<td class="an-nom"><span class="pers-nom">{e(p.nom_complet)}</span></td>'
        f'<td class="pers-fonction">{e(p.fonction) or "—"}</td>'
        f'<td class="an-pays">{lien}</td>'
        f'<td class="an-pays">{e(p.pays)}</td>'
        f'<td class="an-agr">{e(p.carte) or "—"}</td>'
        f'<td class="an-etat"><span class="badge {cls} petit">{etat}</span></td>'
        "</tr>")


def _cle_pays(pays: str) -> str:
    return sans_accent(pays or "").upper().replace(" ", "-").replace("'", "")


def page_personnes(personnes: list, releve: str, base_url: str) -> str:
    en_fonction = [p for p in personnes if p.actif]
    societes = len({p.societe for p in personnes if p.societe})
    pays = sorted({(_cle_pays(p.pays), p.pays) for p in personnes if p.pays},
                  key=lambda x: x[1])
    familles = []
    for cle, libelle, _ in FAMILLES_FONCTION:
        n = sum(1 for p in personnes if p.famille == cle)
        if n:
            familles.append((cle, libelle, n))

    vignettes = "\n".join(f"""
    <span class="vignette vignette-inerte">
      <span class="vignette-nombre">{n}</span>
      <span class="vignette-nom">{e(libelle)}</span>
    </span>""" for _, libelle, n in familles)

    filtres_fam = "\n".join(f'<option value="{cle}">{e(libelle)}</option>'
                            for cle, libelle, _ in familles)
    filtres_pays = "\n".join(f'<option value="{e(c)}">{e(n)}</option>'
                             for c, n in pays)
    lignes = "\n".join(_ligne_personne(p) for p in personnes)

    corps = f"""
<div class="conteneur">
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a> <span>›</span>
    <span aria-current="page">Personnes</span>
  </nav>
  <header class="section-entete">
    <span class="section-icone">{icone("acteurs")}</span>
    <h1>Personnes exerçant sur le marché</h1>
    <p class="chapeau">{PERSONNES_INTRO}</p>
    <p class="compte"><strong>{len(personnes)}</strong> personnes,
    dont <strong>{len(en_fonction)}</strong> en fonction, réparties dans
    <strong>{societes}</strong> sociétés. Relevé du {date_francaise(releve)}.</p>
  </header>

  <section class="avis avis-personnes">
    <p><strong>Cette page n'est pas indexée par les moteurs de recherche.</strong>
    Une fiche nominative que l'on trouverait en cherchant un nom propre n'a pas
    la même portée qu'une page de société&nbsp;; le registre de l'Autorité
    n'est pas davantage indexable.</p>
    <p>Le recueil ne reprend ni date ni lieu de naissance, ni photographie, bien
    que le registre les publie. Il ne reprend pas non plus les numéros de
    téléphone personnels. Une personne qui souhaite voir corriger ou retirer sa
    ligne peut le signaler&nbsp;: la correction doit d'abord être faite au
    registre, qui reste la source.</p>
  </section>

  <nav class="vignettes vignettes-compte" aria-label="Familles de fonctions">
{vignettes}
  </nav>

  <section class="annuaire" id="annuaire">
    <h2>Répertoire</h2>
    <form class="an-filtres" role="search" onsubmit="return false">
      <p class="an-champ">
        <label for="an-q">Chercher une personne</label>
        <input type="search" id="an-q" placeholder="Nom, société, fonction…"
               autocomplete="off" spellcheck="false">
      </p>
      <p class="an-champ">
        <label for="an-cat">Fonction</label>
        <select id="an-cat"><option value="">Toutes</option>
{filtres_fam}
        </select>
      </p>
      <p class="an-champ">
        <label for="an-pays">Pays</label>
        <select id="an-pays"><option value="">Tous</option>
{filtres_pays}
        </select>
      </p>
      <p class="an-champ an-bascule">
        <label for="an-actifs">
          <input type="checkbox" id="an-actifs" checked>
          Masquer les personnes non actives
        </label>
      </p>
    </form>
    <p class="an-etat" id="an-etat" role="status" aria-live="polite"></p>
    <div class="an-cadre">
      <table class="an-table" id="an-table" data-objet="personne">
        <thead>
          <tr><th scope="col">Nom</th><th scope="col">Fonction</th>
          <th scope="col">Société</th><th scope="col">Pays</th>
          <th scope="col">Carte</th><th scope="col">État</th></tr>
        </thead>
        <tbody>
{lignes}
        </tbody>
      </table>
    </div>
    <p class="an-note">La colonne «&nbsp;carte&nbsp;» reprend l'état
    d'avancement du dossier au registre — demande enregistrée, carte imprimée,
    validée. C'est un état administratif, non une attestation d'habilitation.</p>
  </section>

  <section class="fiche-source">
    <h2>Sources</h2>
    <p>Deux sources se croisent ici. Le registre des acteurs agréés de
    l'AMF-UMOA, qui rattache à chaque société les détenteurs de cartes
    professionnelles. Et le répertoire du recueil, constitué à partir de
    brvm.org, de l'annuaire de l'APSGI et de la presse spécialisée, qui couvre
    des dirigeants que le registre ne nomme pas. Un champ vide signifie
    «&nbsp;non trouvé dans une source publique vérifiable&nbsp;», jamais
    «&nbsp;inexistant&nbsp;».</p>
  </section>
</div>
"""
    return page_html(titre=f"Personnes exerçant sur le marché — {SITE_COURT}",
                     description=PERSONNES_INTRO, corps=corps,
                     chemin="personnes/", base_url=base_url,
                     classe="page-acteurs", script_annuaire=True,
                     indexable=False)


def bloc_personnes_acteur(gens: list) -> str:
    """Encart des personnes rattachées à un acteur, sur sa fiche."""
    if not gens:
        return ""
    en_fonction = [p for p in gens if p.actif]
    lignes = "\n".join(
        f'<li><span class="pers-nom">{e(p.nom_complet)}</span>'
        f'<span class="renvoi-objet">{e(p.fonction)}'
        f'{"" if p.actif else " · non actif"}</span></li>'
        for p in gens[:40])
    reste = (f'<p class="renvoi-plus">et {len(gens) - 40} autres — '
             f'<a href="../../../personnes/">voir le répertoire</a></p>'
             if len(gens) > 40 else
             '<p class="renvoi-plus"><a href="../../../personnes/">'
             'Répertoire complet des personnes</a></p>')
    return f"""
  <section class="textes-lies">
    <h2>Personnes rattachées</h2>
    <p class="renvoi-avis">{len(gens)} personnes figurent au registre pour cette
    société, dont {len(en_fonction)} en fonction. Cette liste n'est pas
    indexée par les moteurs de recherche.</p>
    <ul class="textes-lies-liste">
{lignes}
    </ul>
    {reste}
  </section>"""


# --------------------------------------------------------------------------
#  Index de recherche
# --------------------------------------------------------------------------

def construire_index(textes: list[Texte], acteurs: list | None = None) -> dict:
    docs = []
    postings: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    longueurs: list[int] = []

    for i, t in enumerate(textes):
        docs.append([t.slug, t.titre_court, t.type_cle, t.annee,
                     1 if t.abroge else 0, t.numero, t.resume[:180]])

        # Le titre, le numéro et le résumé pèsent davantage que le corps.
        n_jetons = 0
        for champ, poids in ((t.titre, 6), (t.numero, 6),
                             (" ".join(t.tags), 4), (t.resume, 3),
                             (t.texte_brut, 1)):
            for j in jetons(champ):
                if j in MOTS_VIDES:
                    continue
                postings[j][i] += poids
                n_jetons += 1
        longueurs.append(n_jetons)

    # Les acteurs entrent dans le même index : chercher « Sirius » doit mener à
    # la société, chercher « SGI » aux deux — les textes et les agréés. Leur
    # chemin sert de clé ; le script de recherche les distingue au type.
    for a in acteurs or []:
        i = len(docs)
        docs.append([a.chemin, a.nom, "acteur", a.date_agrement[:4],
                     0 if a.actif else 1, a.agrement,
                     f"{a.cat.singulier} · {a.pays}. {a.cat.role}"[:180]])
        n_jetons = 0
        for champ, poids in ((a.nom, 8), (a.agrement, 6), (a.cat.sigle, 5),
                             (a.cat.pluriel, 3), (a.pays, 3),
                             (a.forme_juridique, 1), (a.siege, 1),
                             (a.cat.role, 1)):
            for j in jetons(champ or ""):
                if j in MOTS_VIDES:
                    continue
                postings[j][i] += poids
                n_jetons += 1
        longueurs.append(n_jetons)

    # La longueur sert à la normalisation BM25 : sans elle, un rapport annuel de
    # deux cents pages devance systématiquement l'instruction qui régit
    # précisément le sujet cherché, au seul motif qu'il cite le terme plus
    # souvent.
    for i, n in enumerate(longueurs):
        docs[i].append(n)

    n = len(docs)
    termes = {}
    for terme, m in postings.items():
        # Un terme présent dans presque tous les documents ne discrimine rien.
        if len(m) > n * 0.75 and len(terme) <= 4:
            continue
        termes[terme] = [[d, min(tf, 255)] for d, tf in
                         sorted(m.items(), key=lambda x: -x[1])[:400]]

    # La pondération inverse se déduit du nombre de documents porteurs du terme :
    # la stocker doublerait inutilement la taille de l'index, que le visiteur
    # télécharge intégralement au premier accès à la recherche.
    moyenne = sum(longueurs) / len(longueurs) if longueurs else 1
    return {"docs": docs, "termes": termes, "longueurMoyenne": round(moyenne)}


# --------------------------------------------------------------------------
#  Assemblage
# --------------------------------------------------------------------------

INTROS = {
    "base": "Le socle normatif du marché financier régional : la Convention "
            "créant l'Autorité, son Annexe, l'Avenant de 1997 et le Règlement "
            "Général, ainsi que les décisions qui l'ont modifié.",
    "instruction": "Textes d'application pris par l'AMF-UMOA. Ils précisent les "
                   "dispositions du Règlement Général : conditions d'agrément des "
                   "acteurs, modalités d'exercice de leur métier, visa des "
                   "opérations financières, reporting et procédures de sanction.",
    "circulaire": "Circulaires du Secrétaire Général de l'AMF-UMOA, qui précisent "
                  "les modalités pratiques d'application de la réglementation.",
    "decision": "Décisions du Conseil des Ministres de l'UMOA et de l'AMF-UMOA "
                "portant sur l'organisation et le contrôle du marché financier "
                "régional.",
    "autre": "Actes émanant du Conseil des Ministres de l'UEMOA ou d'autres "
             "organes de l'Union, qui régissent le marché financier régional sans "
             "figurer sur le site de l'Autorité — sa rubrique « Autres actes » "
             "est vide. Ils sont réunis ici à mesure qu'ils sont retrouvés.",
    "rapport": "Rapports annuels et études publiés par l'AMF-UMOA sur l'activité "
               "et le développement du marché financier régional.",
}


def construire(dossier_texte: Path, manifeste: Path, pdfs: Path,
               sortie: Path, base_url: str, inclure_pdf: bool = False,
               racine_brute: Path | None = None,
               fichier_acteurs: Path | None = None,
               fichier_opc: Path | None = None,
               fichier_personnes: Path | None = None) -> None:
    # Le nom d'hôte est insensible à la casse, mais les URL canoniques ne
    # doivent pas pour autant différer de l'adresse réellement servie : GitHub
    # Pages sert en minuscules alors que le nom de compte peut porter des
    # capitales. Le chemin, lui, reste sensible à la casse et n'est pas touché.
    if "://" in base_url:
        protocole, reste = base_url.split("://", 1)
        hote, barre, chemin = reste.partition("/")
        base_url = f"{protocole.lower()}://{hote.lower()}{barre}{chemin}"

    textes = charger(dossier_texte, manifeste)
    if not textes:
        raise SystemExit(f"Aucun JSON trouvé dans {dossier_texte}")

    if sortie.exists():
        shutil.rmtree(sortie)
    for d in ("textes", "assets", "data", "pdf"):
        (sortie / d).mkdir(parents=True, exist_ok=True)

    acteurs: list = []
    releve = ""
    if fichier_acteurs:
        acteurs, releve = charger_acteurs(fichier_acteurs)
    opc: list = []
    releve_opc = ""
    if fichier_opc:
        opc, releve_opc = charger_opc(fichier_opc)
    gens: list = []
    releve_gens = ""
    if fichier_personnes:
        gens, releve_gens = charger_personnes(fichier_personnes)

    # Feuilles de style et script
    ici = Path(__file__).parent / "assets"
    for nom in ("style.css", "recherche.js", "assistant.js", "pdf.js",
                "annuaire.js", "favicon.svg"):
        if (ici / nom).exists():
            shutil.copy(ici / nom, sortie / "assets" / nom)

    par_type = defaultdict(list)
    for t in textes:
        par_type[t.type_cle].append(t)

    global SECTIONS_PRESENTES, ACTEURS_PRESENTS, OPC_PRESENTS, PERSONNES_PRESENTES
    SECTIONS_PRESENTES = set(par_type)
    ACTEURS_PRESENTS = bool(acteurs)
    OPC_PRESENTS = bool(opc)
    PERSONNES_PRESENTES = bool(gens)
    gens_par_societe = personnes_par_societe(gens) if gens else {}
    opc_par_societe = produits_par_societe(opc) if opc else {}

    # Pages de documents
    for cle, groupe in par_type.items():
        ordonne = sorted(groupe,
                         key=lambda x: (x.rang, x.annee or "", x.numero.zfill(8)),
                         reverse=(cle != "base"))
        for i, t in enumerate(ordonne):
            voisins = {"prec": ordonne[i - 1] if i else None,
                       "suiv": ordonne[i + 1] if i + 1 < len(ordonne) else None}
            d = sortie / "textes" / t.slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(
                page_texte(t, base_url, voisins, inclure_pdf), encoding="utf-8")
            (sortie / "data" / f"{t.slug}.txt").write_text(
                f"{t.titre}\n{'=' * len(t.titre)}\n\n{t.texte_brut}\n",
                encoding="utf-8")

    # Pages de listes
    for cle in TYPES:
        if not par_type.get(cle):
            continue
        ordonne = sorted(par_type[cle],
                         key=lambda x: (x.rang, x.annee or "", x.numero.zfill(8)),
                         reverse=(cle != "base"))
        d = sortie / TYPES[cle][1]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            page_liste(cle, ordonne, base_url, INTROS[cle]), encoding="utf-8")

    # Acteurs agréés : la rubrique n'existe que si le relevé est présent.
    groupes_acteurs = acteurs_par_categorie(acteurs) if acteurs else {}
    if acteurs:
        d = sortie / "acteurs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            page_acteurs(acteurs, releve, textes, base_url), encoding="utf-8")
        for cle, groupe in groupes_acteurs.items():
            dc = d / cle
            dc.mkdir(parents=True, exist_ok=True)
            (dc / "index.html").write_text(
                page_categorie_acteurs(cle, groupe, acteurs, textes, releve,
                                       base_url), encoding="utf-8")
            for a in groupe:
                da = dc / a.slug
                da.mkdir(parents=True, exist_ok=True)
                (da / "index.html").write_text(
                    page_acteur(a, acteurs, textes, releve, base_url,
                                gens_par_societe.get(a.chemin, []),
                                opc_par_societe.get(a.id, [])),
                    encoding="utf-8")

    if gens:
        d = sortie / "personnes"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            page_personnes(gens, releve_gens, base_url), encoding="utf-8")

    groupes_opc = opc_par_famille(opc) if opc else {}
    if opc:
        d = sortie / "opc"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            page_opc(opc, releve_opc, textes, base_url), encoding="utf-8")
        for cle, groupe in groupes_opc.items():
            df = d / cle
            df.mkdir(parents=True, exist_ok=True)
            (df / "index.html").write_text(
                page_famille_opc(cle, groupe, opc, textes, releve_opc, base_url),
                encoding="utf-8")
            for o in groupe:
                do = df / o.slug
                do.mkdir(parents=True, exist_ok=True)
                (do / "index.html").write_text(
                    page_opc_fiche(o, opc, acteurs, textes, releve_opc, base_url),
                    encoding="utf-8")

    # Pages transverses
    (sortie / "index.html").write_text(page_accueil(textes, acteurs, base_url),
                                       encoding="utf-8")
    for nom, contenu in (("chronologie", page_chronologie(textes, base_url)),
                         ("recherche", page_recherche(base_url)),
                         ("a-propos", page_apropos(textes, base_url))):
        (sortie / nom).mkdir(parents=True, exist_ok=True)
        (sortie / nom / "index.html").write_text(contenu, encoding="utf-8")

    # Index de recherche
    (sortie / "data" / "index-recherche.json").write_text(
        json.dumps(construire_index(textes, acteurs), ensure_ascii=False,
                   separators=(",", ":")), encoding="utf-8")

    # PDF originaux : copiés seulement sur demande explicite, car le corpus
    # complet pèse plusieurs centaines de Mo — trop pour un dépôt Git ordinaire.
    copies = 0
    if inclure_pdf and pdfs.exists():
        for t in textes:
            src = pdfs / t.pdf
            if src.exists():
                shutil.copy(src, sortie / "pdf" / t.pdf)
                copies += 1
    else:
        (sortie / "pdf").rmdir()

    # Sitemap
    aujourdhui = date.today().isoformat()
    urls = [("", "1.0"), ("recherche/", "0.5"), ("chronologie/", "0.7"),
            ("a-propos/", "0.5")]
    urls += [(TYPES[c][1] + "/", "0.8") for c in par_type]
    urls += [(f"textes/{t.slug}/", "0.9") for t in textes]
    # La page des personnes est volontairement absente du plan du site : elle
    # n'est pas indexable, l'y déclarer serait contradictoire.
    if opc:
        urls += [("opc/", "0.8")]
        urls += [(f"opc/{c}/", "0.7") for c in groupes_opc]
        urls += [(f"opc/{o.chemin}/", "0.6") for o in opc]
    if acteurs:
        urls += [("acteurs/", "0.8")]
        urls += [(f"acteurs/{c}/", "0.7") for c in groupes_acteurs]
        urls += [(f"acteurs/{a.chemin}/", "0.6") for a in acteurs]
    entrees = "\n".join(
        f"  <url><loc>{base_url.rstrip('/')}/{u}</loc>"
        f"<lastmod>{aujourdhui}</lastmod><priority>{p}</priority></url>"
        for u, p in urls)
    (sortie / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entrees}\n</urlset>\n", encoding="utf-8")

    # « Disallow » n'empêche pas l'indexation : il empêche la lecture, donc le
    # robot ne voit jamais la balise « noindex » et peut tout de même faire
    # figurer l'adresse. Les moteurs classiques sont donc laissés libres de
    # lire /personnes/, où la balise leur dit de ne pas indexer ; seuls les
    # robots d'archivage et d'entraînement, qui ne l'observent pas, en sont
    # écartés par le chemin.
    moissonneurs = ("ia_archiver", "archive.org_bot", "GPTBot", "CCBot",
                    "ClaudeBot", "anthropic-ai", "Google-Extended",
                    "Applebot-Extended", "PerplexityBot", "Bytespider",
                    "Amazonbot", "meta-externalagent")
    blocs = ["User-agent: *", "Allow: /", ""]
    for robot in moissonneurs:
        blocs += [f"User-agent: {robot}", "Disallow: /personnes/", ""]
    blocs.append(f"Sitemap: {base_url.rstrip('/')}/sitemap.xml")
    (sortie / "robots.txt").write_text("\n".join(blocs) + "\n", encoding="utf-8")

    (sortie / ".nojekyll").write_text("", encoding="utf-8")

    # Fichiers déposés tels quels à la racine du site : preuves de propriété
    # exigées par les moteurs de recherche, fichier CNAME d'un domaine
    # personnalisé, ads.txt… Ils ne sont pas générés, seulement recopiés.
    recopies: list[str] = []
    if racine_brute and racine_brute.is_dir():
        for f in sorted(racine_brute.iterdir()):
            if f.is_file() and not f.name.startswith(".") \
                    and f.name.lower() != "readme.md":
                shutil.copy(f, sortie / f.name)
                recopies.append(f.name)

    taille = sum(f.stat().st_size for f in sortie.rglob("*") if f.is_file())
    print(f"Site généré dans {sortie}")
    print(f"  {len(textes)} documents, {len(urls)} URLs, "
          + (f"{copies} PDF copiés" if inclure_pdf
             else "PDF liés vers amf-umoa.org"))
    if acteurs:
        print(f"  {len(acteurs)} acteurs agréés en {len(groupes_acteurs)} "
              f"catégories (relevé {releve})")
    if opc:
        print(f"  {len(opc)} organismes de placement collectif en "
              f"{len(groupes_opc)} familles (relevé {releve_opc})")
    if gens:
        print(f"  {len(gens)} personnes, non indexées (relevé {releve_gens})")
    elif fichier_acteurs:
        print(f"  annuaire des acteurs absent ({fichier_acteurs}) : "
              f"rubrique non produite")
    if recopies:
        print(f"  déposés à la racine : {', '.join(recopies)}")
    print(f"  index de recherche : "
          f"{(sortie / 'data' / 'index-recherche.json').stat().st_size // 1024} ko")
    print(f"  poids total : {taille / 1_048_576:.1f} Mo")


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère le site du corpus AMF-UMOA")
    ap.add_argument("--texte", default="texte", help="dossier des JSON issus de l'OCR")
    ap.add_argument("--manifeste", default="manifest.json")
    ap.add_argument("--pdf", default="pdf")
    ap.add_argument("--sortie", default="site")
    ap.add_argument("--base-url", default="https://exemple.github.io/textes-mfr-umoa")
    ap.add_argument("--inclure-pdf", action="store_true",
                    help="copier les PDF dans le site (plusieurs centaines de Mo)")
    ap.add_argument("--racine", default="racine",
                    help="dossier de fichiers à déposer tels quels à la racine")
    ap.add_argument("--acteurs", default="acteurs/acteurs.json",
                    help="relevé du registre des acteurs agréés de l'AMF-UMOA")
    ap.add_argument("--opc", default="produits/opc.json",
                    help="relevé du registre des organismes de placement collectif")
    ap.add_argument("--personnes", default="personnes/personnes.json",
                    help="répertoire des personnes exerçant sur le marché")
    a = ap.parse_args()
    construire(Path(a.texte), Path(a.manifeste), Path(a.pdf),
               Path(a.sortie), a.base_url, a.inclure_pdf, Path(a.racine),
               Path(a.acteurs), Path(a.opc), Path(a.personnes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
