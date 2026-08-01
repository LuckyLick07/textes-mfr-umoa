#!/usr/bin/env python3
"""
Modèle de données et structuration du corpus AMF-UMOA.

Deux responsabilités :

1. Normaliser les métadonnées brutes de l'API (titres hétérogènes, casse
   erratique, numérotations variables) en identifiants stables et propres,
   utilisables comme URLs pérennes.

2. Reconstruire une structure documentaire à partir du texte plat issu de
   l'OCR : titres, articles, alinéas, énumérations. C'est cette structure qui
   permet de produire du HTML sémantique — donc indexable et citable — plutôt
   qu'un bloc de texte opaque.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
#  Typologie
# --------------------------------------------------------------------------

# Libellé au singulier, dossier d'URL, libellé au pluriel. Le pluriel est
# explicite : « Texte de base » ne se met pas au pluriel en ajoutant un s à la
# fin de l'expression.
TYPES = {
    "base": ("Texte de base", "textes-de-base", "Textes de base"),
    "instruction": ("Instruction", "instructions", "Instructions"),
    "circulaire": ("Circulaire", "circulaires", "Circulaires"),
    "decision": ("Décision", "decisions", "Décisions"),
    # Actes du Conseil des Ministres de l'UEMOA et textes voisins que le site
    # de l'Autorité mentionne sans les publier : sa rubrique « Autres actes »
    # est vide. Ils entrent dans le recueil par le dossier « apports ».
    "autre": ("Autre acte", "autres-actes", "Autres actes"),
    "rapport": ("Rapport", "rapports", "Rapports"),
}

# Les six textes fondamentaux sont des fichiers statiques du site source :
# ils n'ont pas d'entrée dans l'API et sont donc décrits explicitement.
AMF = "https://www.amf-umoa.org"
# Endpoint de téléchargement direct du site source, stable et authoritatif :
# le recueil y renvoie plutôt que d'héberger des centaines de Mo de scans.
URL_DOC = AMF + "/service/api/elastic/download/actualite/{id}/doc"

TEXTES_DE_BASE = {
    "base_01_convention": dict(
        titre="Convention portant création de l’Autorité des Marchés Financiers "
              "de l’Union Monétaire Ouest Africaine",
        court="Convention portant création de l’AMF-UMOA",
        slug="convention-creation-amf-umoa",
        date="1996-07-03",
        rang=1,
        url=AMF + "/assets/docs/convention/CONVENTION.pdf",
        resume="Traité constitutif signé le 3 juillet 1996 entre les États de "
               "l’UMOA, créant l’organe de régulation du Marché Financier Régional.",
    ),
    "base_02_annexe": dict(
        titre="Annexe à la Convention portant composition, organisation, "
              "fonctionnement et attributions de l’AMF-UMOA",
        court="Annexe à la Convention",
        slug="annexe-convention-amf-umoa",
        date="1996-07-03",
        rang=2,
        url=AMF + "/assets/docs/convention/ANNEXE.pdf",
        resume="Premier dispositif normatif de base du Marché Financier Régional. "
               "Régit la composition et le fonctionnement de l’Autorité ainsi que "
               "le contrôle de l’appel public à l’épargne.",
    ),
    "base_03_avenant": dict(
        titre="Avenant à la Convention portant création de l’AMF-UMOA",
        court="Avenant à la Convention",
        slug="avenant-convention-amf-umoa",
        date="1997-07-03",
        rang=3,
        url=AMF + "/assets/docs/convention/AVENANT.pdf",
        resume="Avenant du 3 juillet 1997 consécutif à l’adhésion de la "
               "Guinée-Bissau à la zone franc de l’Union.",
    ),
    "base_04_reglement_general": dict(
        titre="Règlement Général relatif à l’organisation, au fonctionnement et "
              "au contrôle du Marché Financier Régional de l’UMOA",
        court="Règlement Général",
        slug="reglement-general",
        date="1997-11-28",
        rang=4,
        url=AMF + "/assets/docs/general/Reglement_General.pdf",
        resume="Texte de base adopté le 28 novembre 1997 par la Décision n°001/97 "
               "du Conseil des Ministres. Définit l’organisation, le fonctionnement "
               "et le contrôle du marché financier régional.",
    ),
    "base_05_decision_modif_art37": dict(
        titre="Décision portant modification des dispositions de l’article 37 du "
              "Règlement Général",
        court="Décision modifiant l’article 37 du Règlement Général",
        slug="decision-modification-article-37-reglement-general",
        date="1998-03-27",
        rang=5,
        url=AMF + "/assets/docs/general/Decision_CM_000.pdf",
        resume="Modifie l’article 37 du Règlement Général relatif au Marché "
               "Financier Régional de l’UMOA.",
    ),
    "base_06_decision_modif_art136": dict(
        titre="Décision n° CM 05/09/2005 portant modification de l’article 136 du "
              "Règlement Général",
        court="Décision modifiant l’article 136 du Règlement Général",
        slug="decision-modification-article-136-reglement-general",
        date="2005-09-16",
        rang=6,
        url=AMF + "/assets/docs/general/Decision_CM_05092005_du_16-09-2005.pdf",
        resume="Modifie l’article 136 du Règlement Général. Dernière révision en "
               "date du Règlement Général.",
    ),
}

MOIS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre",
    12: "décembre",
}


# --------------------------------------------------------------------------
#  Utilitaires texte
# --------------------------------------------------------------------------

def sans_accent(t: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )


def slugifier(t: str) -> str:
    t = sans_accent(t.replace("’", "'").replace("°", "")).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return re.sub(r"-{2,}", "-", t).strip("-")[:90]


def date_francaise(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        a, m, j = (int(x) for x in iso[:10].split("-"))
    except (ValueError, AttributeError):
        return ""
    return f"{'1er' if j == 1 else j} {MOIS[m]} {a}"


# Les intitulés du corpus sont saisis en capitales sans accents. Mettre le
# titre en bas de casse le rend lisible, mais produit « Decision », « Marche »,
# « Agrement ». Ce relevé, établi sur le vocabulaire réellement présent dans les
# titres, rétablit l'orthographe.
ACCENTS = {
    "decision": "Décision", "marche": "Marché", "regional": "Régional",
    "developpement": "Développement", "boursiere": "Boursière",
    "etude": "Étude", "operations": "Opérations", "financieres": "Financières",
    "financiere": "Financière", "comite": "Comité", "reunion": "Réunion",
    "journee": "Journée", "references": "Références", "agrement": "Agrément",
    "irreguliere": "Irrégulière", "presidence": "Présidence", "vise": "Visé",
    "epargne": "Épargne", "societes": "Sociétés", "intermediation":
    "Intermédiation", "generale": "Générale", "general": "Général",
    "reglement": "Règlement", "depositaire": "Dépositaire",
    "conformite": "Conformité", "regles": "Règles", "activites": "Activités",
    "continuite": "Continuité", "emission": "Émission",
    "securisees": "Sécurisées", "entites": "Entités", "maitres": "Maîtres",
    "proportionnalite": "Proportionnalité", "reglementation": "Réglementation",
}

SIGLES = ("AMF-UMOA", "UMOA", "UEMOA", "CREPMF", "BRVM", "SGI", "DC/BR",
          "OPCVM", "OPC", "IFRS", "SUKUK", "BCEAO", "CFA", "TCC", "SGO",
          "APE", "MFR", "OHADA", "LBC", "AMF")


def titre_propre(t: str) -> str:
    """Rend lisible un intitulé saisi tout en capitales.

    Trois retouches : passage en bas de casse, rétablissement des accents et
    des sigles, et maintien en capitales de la référence qui suit « n° » —
    « n° CM/SJ/001/03/2016 » ne doit pas devenir « n° cm/sj/o01/03/2016 ».
    """
    t = " ".join((t or "").split())
    lettres = [c for c in t if c.isalpha()]
    if not lettres or sum(c.isupper() for c in lettres) / len(lettres) <= 0.85:
        return t

    t = t.capitalize()

    for sansaccent, correct in ACCENTS.items():
        t = re.sub(rf"\b{sansaccent}\b",
                   lambda m, c=correct: c if m.group(0)[0].isupper() else c.lower(),
                   t, flags=re.IGNORECASE)

    for sigle in SIGLES:
        t = re.sub(rf"\b{re.escape(sigle.lower())}\b", sigle, t,
                   flags=re.IGNORECASE)

    t = re.sub(r"\bn\s*°\s*", "n° ", t, flags=re.IGNORECASE)
    # La référence elle-même reprend ses capitales.
    t = re.sub(r"(n°\s*)([0-9a-z][0-9a-z/\-\.]*)",
               lambda m: m.group(1) + m.group(2).upper(), t)
    return t


# --------------------------------------------------------------------------
#  Structuration du texte
# --------------------------------------------------------------------------

_TITRE_MAJEUR = re.compile(
    r"^\s*(TITRE|CHAPITRE|SOUS-TITRE|LIVRE)\s+"
    r"([IVXLC]+|PREMIER|[0-9]+)\s*[:\.\-–]?\s*(.*)$",
    re.IGNORECASE,
)
_SECTION = re.compile(r"^\s*SECTION\s+([IVXLC]+|[0-9]+)\s*[:\.\-–]?\s*(.*)$",
                      re.IGNORECASE)
_ARTICLE = re.compile(
    r"^\s*ART(?:ICLE|\.)\s*(premier|1\s*er|[0-9]+(?:\s*(?:bis|ter|quater))?)"
    r"\s*[:\.\-–)]?\s*(.*)$",
    re.IGNORECASE,
)
_PUCE = re.compile(r"^\s*[-–—•*·]\s+(.+)$")
_NUMEROTE = re.compile(r"^\s*(\d{1,2}[\.\)°]|[a-z][\.\)])\s+(.+)$")
_PIED = re.compile(
    r"^\s*(page\s+\d+(\s*/\s*\d+)?|\d{1,3}|[-–—\s]*\d+[-–—\s]*)\s*$",
    re.IGNORECASE,
)
# Les formulaires annexes utilisent des lignes de pointillés que l'OCR rend en
# longues suites de lettres. Le critère est volontairement très restrictif —
# vingt caractères et une même lettre six fois — pour ne jamais toucher un mot
# réel, même long.
_POINTILLES = re.compile(r"\b[A-Za-zÀ-ÿ]{20,}\b")


_MOT = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_COMPOSE = re.compile(r"([A-Za-zÀ-ÿ]{3,})-([A-Za-zÀ-ÿ]{3,})")


def lexique(pages_par_document: list[list[str]]) -> tuple[dict[str, int], set[str]]:
    """Relève la fréquence des mots et les composés à trait d'union attestés."""
    frequences: dict[str, int] = {}
    composes: set[str] = set()
    for pages in pages_par_document:
        for texte in pages:
            for m in _MOT.finditer(texte):
                mot = m.group(0).lower()
                frequences[mot] = frequences.get(mot, 0) + 1
            for m in _COMPOSE.finditer(texte):
                composes.add((m.group(1) + "-" + m.group(2)).lower())
    return frequences, composes


def reparer_composes(texte: str, frequences: dict[str, int],
                     composes: set[str]) -> str:
    """Rétablit les traits d'union supprimés à tort lors du recollage des césures.

    Une césure de fin de ligne est ambiguë : « informa-tion » doit être recollé
    sans trait d'union, « négociateur-compensateur » doit le conserver. La levée
    d'ambiguïté se fait sur le corpus lui-même — on ne rétablit un trait d'union
    que si la forme composée y est attestée ailleurs, et si les deux éléments y
    sont des mots courants alors que leur concaténation reste rare.
    """
    def remplacer(m: re.Match) -> str:
        mot = m.group(0)
        bas = mot.lower()
        if frequences.get(bas, 0) > 2 or len(bas) < 12:
            return mot
        for i in range(4, len(bas) - 3):
            gauche, droite = bas[:i], bas[i:]
            if (f"{gauche}-{droite}" in composes
                    and frequences.get(gauche, 0) >= 4
                    and frequences.get(droite, 0) >= 4):
                return mot[:i] + "-" + mot[i:]
        return mot

    return _MOT.sub(remplacer, texte)


def _nettoyer_pointilles(ligne: str) -> str:
    def remplacer(m: re.Match) -> str:
        mot = m.group(0)
        frequence = max(mot.lower().count(c) for c in set(mot.lower()))
        return "…" if frequence >= 6 else mot
    return _POINTILLES.sub(remplacer, ligne)


# --------------------------------------------------------------------------
#  Résidus du papier à en-tête
# --------------------------------------------------------------------------
# Le bas de page du papier officiel — adresse du siège, téléphone, télécopie,
# adresses électroniques — et le rappel du numéro de l'acte reviennent sur
# chaque page scannée ; l'OCR les restitue au milieu du texte, où ils n'ont
# aucun sens documentaire. Trois familles de règles les écartent. Elles sont
# volontairement étroites : mieux vaut laisser passer un résidu que
# retrancher une ligne du texte normatif — les visas (« Vu l'Instruction
# n°… ») et les blocs de signature (« Fait à Abidjan, le… ») ne sont jamais
# touchés.

# Marqueurs d'adresse et de téléphone : jamais du texte normatif. L'OCR
# défigure « Joseph ANOMA » de mille façons, mais le nom de rue, l'indicatif
# ivoirien et la boîte postale restent reconnaissables.
_CONTACT_FORT = re.compile(
    r"\banoma\b|joseph\s+anoma|abidjan\s*[-–]?\s*plateau|plateau\s+aven"
    r"|\b[b3]pm\s*[‘']?\s*[i1l]?8|b\.?\s*p\.?\s*:?\s*1878"
    r"|[-+({\[]\s*[-+]?\s*2\s*2\s*5\s*[)}\]]|\(\s*225\s*\)"
    r"|\b(?:te[l1]|tél|téll|té)\s*\.?\s*:|\bfax\s*\.?\s*:",
    re.IGNORECASE)
# Adresses web et courriels : résidu probable, sauf au sein d'une phrase
# rédigée qui renvoie le lecteur au site officiel.
_CONTACT_WEB = re.compile(
    r"@|www\s*\.|crepmf\s*\.\s*org|amf[\s-]?umoa\s*\.\s*org", re.IGNORECASE)
_PHRASE = re.compile(
    r"\b(sont|est|sera|seront|peut|peuvent|doivent|doit|publi|disponibl"
    r"|consult|figur|adress|transm)", re.IGNORECASE)
_COMPTEUR = re.compile(
    r"^\W{0,4}(?:page\s+)?\d{1,3}\s*(?:/|sur)\s*\d{1,3}\W{0,4}$",
    re.IGNORECASE)
# Rappel isolé du numéro de l'acte : « Instruction n° 67/CREPMF/2021 » seul
# sur sa ligne. La forme rédigée (« relative à… », « portant… ») est du
# texte et reste ; la citation en visa commence par « Vu » et reste aussi.
_RAPPEL_ACTE = re.compile(
    r"^\W{0,8}[il1t]?(?:nstruction|circulaire|d[ée]cision)s?\s*n\W{0,4}\S",
    re.IGNORECASE)
_RAPPEL_REDIGE = re.compile(
    r"relative|relatif|portant|modifiant|fixant|abroge|vis[ée]e", re.IGNORECASE)

_GENRES_STRUCTURE = (_TITRE_MAJEUR, _SECTION, _ARTICLE, _PUCE, _NUMEROTE)


def _signature_ligne(ligne: str) -> str:
    plate = re.sub(r"\d+", "#", sans_accent(ligne).lower())
    return re.sub(r"[^a-z#]+", " ", plate).strip()


def epurer_residus(pages: list[dict]) -> tuple[list[dict], int]:
    """Écarte les résidus d'en-tête et de pied de page.

    Une ligne est retirée si elle relève des coordonnées du papier officiel,
    d'un compteur de pages, d'un rappel isolé du numéro de l'acte, ou si sa
    forme — chiffres neutralisés — revient en bord de page sur au moins
    trois pages du document : c'est la définition d'un élément de gabarit.
    """
    decoupes = [p.get("texte", "").split("\n") for p in pages]

    # Relevé des lignes de bord de page, chiffres neutralisés, pour repérer
    # les éléments de gabarit répétés que les motifs fixes ne couvrent pas.
    frequences: dict[str, set[int]] = {}
    for num, lignes in enumerate(decoupes):
        pleines = [l for l in lignes if l.strip()]
        for l in pleines[:3] + pleines[-5:]:
            if len(l) > 80 or any(m.match(l) for m in _GENRES_STRUCTURE):
                continue
            frequences.setdefault(_signature_ligne(l), set()).add(num)

    def est_residu(ligne: str, en_bord: bool) -> bool:
        s = ligne.strip()
        if not s:
            return False
        if len(s) < 200 and _CONTACT_FORT.search(s):
            return True
        if len(s) < 120 and _CONTACT_WEB.search(s) and not _PHRASE.search(s):
            return True
        if _COMPTEUR.match(s):
            return True
        if (len(s) <= 90 and _RAPPEL_ACTE.match(s)
                and re.search(r"\d", s) and not _RAPPEL_REDIGE.search(s)
                and not _PUCE.match(s) and not _NUMEROTE.match(s)):
            return True
        if (en_bord and len(s) <= 80
                and not any(m.match(s) for m in _GENRES_STRUCTURE)
                and len(frequences.get(_signature_ligne(s), ())) >= 3):
            return True
        return False

    retires = 0
    resultat: list[dict] = []
    for p, lignes in zip(pages, decoupes):
        indices_pleines = [i for i, l in enumerate(lignes) if l.strip()]
        bords = set(indices_pleines[:3] + indices_pleines[-5:])
        gardees = []
        for i, l in enumerate(lignes):
            if l.strip() and est_residu(l, i in bords):
                retires += 1
            else:
                gardees.append(l)
        resultat.append(dict(p, texte="\n".join(gardees)))
    return resultat, retires


@dataclass
class Bloc:
    genre: str            # titre | section | article | paragraphe | puce | numerote
    texte: str
    marque: str = ""      # numéro d'article ou de titre
    page: int = 0


def _est_fin_de_paragraphe(ligne: str, suivante: str, largeur: float) -> bool:
    """Décide si une ligne clôt un paragraphe, dans un texte OCR ré-enveloppé."""
    if not suivante.strip():
        return True
    if ligne.rstrip().endswith((".", ";", ":", "!", "?", "»")):
        # Fin de phrase, mais une ligne pleine peut poursuivre le paragraphe.
        return len(ligne) < largeur * 0.85
    # Ligne nettement courte : probable fin de bloc.
    return len(ligne) < largeur * 0.55


def _romain(brut: str) -> str:
    """Répare la confusion I/l/1 des numéros romains lus par l'OCR.

    « TITRE Il » est presque toujours « TITRE II » : le l minuscule et le
    chiffre 1 se substituent au I dans les petites capitales. La retouche ne
    s'applique qu'aux jetons mêlant lettres romaines et caractères confus —
    un numéro purement arabe (« TITRE 2 ») reste tel quel.
    """
    t = brut.strip()
    if re.fullmatch(r"[IVXLCivxlc1l]+", t) and re.search(r"[IVXCivxcl]", t):
        t = t.replace("1", "I").replace("l", "I")
    return t.upper()


def structurer(pages: list[dict]) -> list[Bloc]:
    """Transforme le texte plat de l'OCR en blocs sémantiques."""
    blocs: list[Bloc] = []

    for p in pages:
        lignes = [_nettoyer_pointilles(l) for l in p.get("texte", "").split("\n")]
        # Retire numéros de page et en-têtes résiduels.
        lignes = [l for l in lignes if not _PIED.match(l)]
        if not lignes:
            continue

        pleines = [len(l) for l in lignes if len(l.strip()) > 12]
        largeur = (sorted(pleines)[len(pleines) // 2] if pleines else 70)

        tampon: list[str] = []
        genre_courant = "paragraphe"

        def vider():
            nonlocal tampon, genre_courant
            if tampon:
                txt = " ".join(x.strip() for x in tampon if x.strip())
                if txt:
                    blocs.append(Bloc(genre_courant, txt, page=p.get("numero", 0)))
            tampon = []
            genre_courant = "paragraphe"

        i = 0
        while i < len(lignes):
            ligne = lignes[i]
            suivante = lignes[i + 1] if i + 1 < len(lignes) else ""

            if not ligne.strip():
                vider()
                i += 1
                continue

            if m := _TITRE_MAJEUR.match(ligne):
                vider()
                mot, num, reste = m.group(1).upper(), _romain(m.group(2)), m.group(3)
                intitule = reste.strip()
                # L'intitulé peut déborder sur la ligne suivante.
                if not intitule and suivante.strip() and len(suivante) < largeur:
                    intitule = suivante.strip()
                    i += 1
                blocs.append(Bloc("titre", intitule, f"{mot} {num}",
                                  p.get("numero", 0)))
                i += 1
                continue

            if m := _SECTION.match(ligne):
                vider()
                intitule = m.group(2).strip()
                if not intitule and suivante.strip() and len(suivante) < largeur:
                    intitule = suivante.strip()
                    i += 1
                blocs.append(Bloc("section", intitule,
                                  f"Section {_romain(m.group(1))}",
                                  p.get("numero", 0)))
                i += 1
                continue

            if m := _ARTICLE.match(ligne):
                vider()
                num = re.sub(r"\s+", " ", m.group(1).strip().lower())
                num = "premier" if num in ("premier", "1 er", "1er") else num
                blocs.append(Bloc("article", m.group(2).strip(),
                                  f"Article {num}", p.get("numero", 0)))
                i += 1
                continue

            if m := _PUCE.match(ligne):
                vider()
                contenu = [m.group(1)]
                while (i + 1 < len(lignes) and lignes[i + 1].strip()
                       and not _PUCE.match(lignes[i + 1])
                       and not _ARTICLE.match(lignes[i + 1])
                       and not _NUMEROTE.match(lignes[i + 1])
                       and len(lignes[i + 1]) >= largeur * 0.5):
                    i += 1
                    contenu.append(lignes[i].strip())
                blocs.append(Bloc("puce", " ".join(contenu), page=p.get("numero", 0)))
                i += 1
                continue

            if m := _NUMEROTE.match(ligne):
                vider()
                blocs.append(Bloc("numerote", m.group(2).strip(), m.group(1),
                                  p.get("numero", 0)))
                i += 1
                continue

            tampon.append(ligne)
            if _est_fin_de_paragraphe(ligne, suivante, largeur):
                vider()
            i += 1

        vider()

    # Fusionne les paragraphes trop courts avec le précédent : artefact fréquent
    # des sauts de page au milieu d'une phrase.
    fusionnes: list[Bloc] = []
    for b in blocs:
        if (fusionnes and b.genre == "paragraphe"
                and fusionnes[-1].genre == "paragraphe"
                and len(b.texte) < 45
                and not fusionnes[-1].texte.rstrip().endswith((".", ";", ":"))):
            fusionnes[-1].texte += " " + b.texte
        else:
            fusionnes.append(b)
    return fusionnes


# --------------------------------------------------------------------------
#  Références croisées
# --------------------------------------------------------------------------

_REF_INSTRUCTION = re.compile(
    r"[Ii]nstruction\s+n?°?\s*(\d{1,3})\s*(?:[/\-]\s*(\d{4}))?", re.IGNORECASE)
_REF_CIRCULAIRE = re.compile(
    r"[Cc]irculaire\s+n?°?\s*(\d{1,3})\s*(?:[/\-]\s*(\d{4}))?", re.IGNORECASE)
_REF_ARTICLE_RG = re.compile(
    r"article\s+(\d{1,3})\s+du\s+R[èe]glement\s+G[ée]n[ée]ral", re.IGNORECASE)


def detecter_references(texte: str) -> dict[str, list[str]]:
    """Repère les renvois vers d'autres textes du corpus."""
    refs = {"instructions": [], "circulaires": [], "articles_rg": []}
    for m in _REF_INSTRUCTION.finditer(texte):
        refs["instructions"].append(m.group(1))
    for m in _REF_CIRCULAIRE.finditer(texte):
        refs["circulaires"].append(m.group(1))
    for m in _REF_ARTICLE_RG.finditer(texte):
        refs["articles_rg"].append(m.group(1))
    return {k: sorted(set(v), key=lambda x: int(x)) for k, v in refs.items()}


# --------------------------------------------------------------------------
#  Document
# --------------------------------------------------------------------------

@dataclass
class Texte:
    identifiant: str          # nom de fichier sans extension
    type_cle: str             # base | instruction | circulaire | decision | rapport
    slug: str
    titre: str
    titre_court: str
    numero: str
    date_iso: str
    resume: str
    abroge: bool
    tags: list[str]
    source_url: str          # page du site officiel qui liste le document
    pdf: str                 # nom du fichier local (copie optionnelle)
    pdf_url: str             # lien direct vers le PDF officiel, référence faisant foi
    reference: str = ""      # référence complète telle qu'elle figure au titre
    annee_texte: str = ""    # année portée par la référence, distincte de la mise en ligne
    blocs: list[Bloc] = field(default_factory=list)
    pages: int = 0
    confiance: float = 0.0
    mode: str = "ocr"
    pages_faibles: list[int] = field(default_factory=list)
    references: dict = field(default_factory=dict)
    rang: int = 999
    abroge_par: str = ""       # référence du texte publié qui prononce l'abrogation
    abroge_par_slug: str = ""  # fiche de ce texte dans le recueil, si présente
    residus_retires: int = 0   # lignes de gabarit écartées par l'épuration

    @property
    def annee(self) -> str:
        """Année de référence du texte.

        Le champ `date` de l'API est la date de mise en ligne sur le site
        officiel, pas celle de l'acte : un lot entier de circulaires de 2021 et
        2022 y porte la même date de septembre 2023. L'année inscrite dans la
        référence est donc la seule fiable pour classer et pour identifier.
        """
        return self.annee_texte or (self.date_iso[:4] if self.date_iso else "")

    @property
    def date_texte(self) -> str:
        return date_francaise(self.date_iso)

    @property
    def libelle_type(self) -> str:
        return TYPES[self.type_cle][0]

    @property
    def libelle_pluriel(self) -> str:
        return TYPES[self.type_cle][2]

    @property
    def dossier_type(self) -> str:
        return TYPES[self.type_cle][1]

    @property
    def texte_brut(self) -> str:
        return "\n\n".join(
            (f"{b.marque} — {b.texte}" if b.marque else b.texte) for b in self.blocs
        )


_REFERENCE = re.compile(r"n\s*°\s*([0-9A-Z][0-9A-Za-z/\-\.]*)", re.IGNORECASE)
# Pas de frontière de mot en fin de motif : certaines références accolent une
# lettre au millésime, comme « 41/2009R » pour une instruction révisée.
_ANNEE = re.compile(r"(?<![0-9])((?:19|20)\d{2})")
# Les instructions des premières années s'écrivent « N°02/97 », « N°13/98 ».
_ANNEE_COURTE = re.compile(r"[/\-](\d{2})[A-Za-z]*$")


def analyser_titre(titre: str) -> tuple[str, str, str]:
    """Extrait de l'intitulé la référence complète, le numéro seul et l'année.

    Les références du corpus prennent des formes très variables :
    « N°016-2022 », « N°81/AMF-UMOA/2025 », « N°59/2019/AMF-UMOA/REVISEE »,
    « N°CM/10/09/2022 », « N°41/2009R ». On normalise d'abord les espaces
    autour des barres obliques, fréquents dans les intitulés saisis à la main.
    """
    normalise = re.sub(r"\s*/\s*", "/", titre or "")

    reference = numero = ""
    if m := _REFERENCE.search(normalise):
        reference = m.group(1).rstrip(".-/")
        if d := re.match(r"\d{1,3}", reference):
            numero = d.group(0)

    # L'année portée par la référence prime sur celle du reste de l'intitulé.
    annees = _ANNEE.findall(reference) or _ANNEE.findall(normalise)
    annee = annees[-1] if annees else ""

    # À défaut, millésime sur deux chiffres : l'Organe a été créé en 1996, donc
    # 96-99 renvoie au XXe siècle et le reste au XXIe.
    if not annee and (c := _ANNEE_COURTE.search(reference)):
        court = int(c.group(1))
        annee = str(1900 + court if court >= 90 else 2000 + court)

    return reference, numero, annee


def charger(dossier_texte: Path, manifeste: Path | None,
            apports: Path | None = None,
            statuts: Path | None = None) -> list[Texte]:
    """Assemble les sorties OCR et les métadonnées en une liste de textes."""
    meta_par_id: dict[str, dict] = {}
    if manifeste and manifeste.exists():
        for it in json.loads(manifeste.read_text(encoding="utf-8")):
            meta_par_id[str(it.get("id"))] = it

    # Métadonnées des documents apportés hors canal officiel, décrites par leur
    # nom de fichier et consignées dans un fichier lisible et modifiable.
    meta_apports: dict[str, dict] = {}
    if apports is None:
        apports = Path("apports/metadonnees.json")
    if apports.exists():
        meta_apports = json.loads(apports.read_text(encoding="utf-8"))

    # Statuts d'abrogation attestés. La source officielle publie un champ
    # « abroge » mais ne le renseigne jamais ; certains textes du recueil
    # prononcent pourtant expressément l'abrogation d'un autre. Ce relevé,
    # vérifié clause par clause, reporte cette information sur le texte
    # abrogé en citant la disposition qui la fonde — jamais une appréciation
    # propre du recueil.
    if statuts is None:
        statuts = Path("corrections/statuts.json")
    donnees_statuts: dict[str, dict] = {}
    if statuts.exists():
        donnees_statuts = {
            k: v for k, v in
            json.loads(statuts.read_text(encoding="utf-8")).items()
            if not k.startswith("_") and isinstance(v, dict)
        }

    # Le lexique se construit sur l'ensemble du corpus avant toute
    # structuration : c'est lui qui permet de trancher les césures ambiguës.
    fichiers = sorted(dossier_texte.glob("*.json"))
    donnees = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in fichiers}
    frequences, composes = lexique(
        [[p.get("texte", "") for p in d.get("detail", [])] for d in donnees.values()]
    )

    textes: list[Texte] = []
    for fjson in fichiers:
        brut = donnees[fjson.stem]
        ident = fjson.stem

        if ident in TEXTES_DE_BASE:
            b = TEXTES_DE_BASE[ident]
            t = Texte(
                identifiant=ident, type_cle="base", slug=b["slug"],
                titre=b["titre"], titre_court=b["court"], numero="",
                date_iso=b["date"], resume=b["resume"], abroge=False,
                tags=["Texte de base"],
                source_url=AMF + "/reglementation/convention",
                pdf=ident + ".pdf", pdf_url=b["url"], rang=b["rang"],
            )
        elif ident in meta_apports:
            a = meta_apports[ident]
            titre = a.get("titre") or ident
            reference, numero_court, annee = analyser_titre(titre)
            noyau = numero_court or reference
            if noyau and annee and annee not in noyau:
                noyau = f"{noyau}-{annee}"
            type_cle = a.get("type") if a.get("type") in TYPES else "autre"
            t = Texte(
                identifiant=ident, type_cle=type_cle,
                slug=a.get("slug") or (slugifier(f"{TYPES[type_cle][0]}-{noyau}")
                                       if noyau else slugifier(titre)),
                titre=titre, titre_court=titre,
                numero=f"n° {reference}" if reference else "",
                date_iso=(a.get("date") or "")[:10],
                resume=" ".join((a.get("resume") or "").split()),
                abroge=bool(a.get("abroge")),
                reference=reference, annee_texte=annee or (a.get("date") or "")[:4],
                tags=[x for x in (a.get("tags") or []) if x] or ["Autre acte"],
                source_url=a.get("source") or "",
                pdf=ident + ".pdf",
                pdf_url=a.get("source") or "",
            )

        else:
            partie = ident.split("_")
            type_cle = partie[0] if partie[0] in TYPES else "instruction"
            doc_id = partie[-1]
            m = meta_par_id.get(doc_id, {})
            brut_titre = m.get("titre") or ident
            titre = titre_propre(brut_titre)
            resume = " ".join((m.get("resume") or "").split())
            reference, numero_court, annee = analyser_titre(brut_titre)
            numero = f"n° {reference}" if reference else ""
            abroge = bool(m.get("abroge")) or "abrog" in brut_titre.lower()

            # Adresse lisible et stable, construite sur la référence officielle
            # et l'année du texte — jamais sur la date de mise en ligne, qui est
            # commune à des lots entiers et provoquerait des collisions.
            noyau = numero_court or reference
            if noyau and annee and annee not in noyau:
                noyau = f"{noyau}-{annee}"
            slug = slugifier(f"{TYPES[type_cle][0]}-{noyau}") if noyau \
                else slugifier(titre)

            t = Texte(
                identifiant=ident, type_cle=type_cle, slug=slug,
                titre=titre, titre_court=titre, numero=numero,
                date_iso=(m.get("date") or "")[:10], resume=resume,
                abroge=abroge, reference=reference, annee_texte=annee,
                tags=[x for x in (m.get("tags") or []) if x],
                source_url=(f"{AMF}/publication/rapport" if type_cle == "rapport"
                            else f"{AMF}/reglementation/{type_cle}"),
                pdf=ident + ".pdf",
                pdf_url=URL_DOC.format(id=doc_id),
            )

        if statut_impose := donnees_statuts.get(ident):
            t.abroge = True
            t.abroge_par = statut_impose.get("par", "")
            t.abroge_par_slug = statut_impose.get("par_slug", "")

        t.pages = brut.get("pages", 0)
        t.confiance = brut.get("confiance_moyenne", 0.0)
        t.mode = brut.get("mode", "ocr")
        t.pages_faibles = brut.get("pages_faibles", [])
        pages = [dict(p, texte=reparer_composes(p.get("texte", ""),
                                                frequences, composes))
                 for p in brut.get("detail", [])]
        pages, t.residus_retires = epurer_residus(pages)
        t.blocs = structurer(pages)
        t.references = detecter_references(t.texte_brut)
        textes.append(t)

    # Unicité des slugs
    vus: dict[str, int] = {}
    for t in textes:
        if t.slug in vus:
            vus[t.slug] += 1
            t.slug = f"{t.slug}-{vus[t.slug]}"
        else:
            vus[t.slug] = 1

    textes.sort(key=lambda x: (x.rang, x.annee or "0000", x.numero, x.titre))
    return textes
