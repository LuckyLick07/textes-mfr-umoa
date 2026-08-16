#!/usr/bin/env python3
"""
Annuaire des acteurs agréés du Marché Financier Régional de l'UMOA.

Ce module tient le pendant « acteurs » de ce que `corpus.py` tient pour les
textes : la description des catégories d'agrément, la normalisation des
enregistrements publiés par l'AMF-UMOA, et leur chargement pour la
construction du site.

La source est le registre public de l'Autorité, interrogé par la même API
elasticsearch que le reste du recueil :

    https://www.amf-umoa.org/service/api/elastic/acteur?size=25&page=N

Le registre est la seule source : aucune donnée n'est inventée ici. Ce qu'y
ajoute le recueil est éditorial — le rattachement de chaque catégorie aux
textes qui la régissent, et une notice expliquant le métier.

Usage :
    acteurs.py collecter --sortie acteurs/acteurs.json
    acteurs.py collecter --depuis-brut dump.json --sortie acteurs/acteurs.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

AMF = "https://www.amf-umoa.org"
API_ACTEURS = AMF + "/service/api/elastic/acteur?size={taille}&page={page}"
REGISTRE = AMF + "/accueil/intervenant"
NAVIGATEUR = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Valeurs de remplissage rencontrées dans le registre, qui ne portent aucune
# information et qu'il vaut mieux ne pas afficher.
VIDES = {"", "-", "--", "_", "__", "néant", "neant", "n/a", "na", "nd", "n",
         "xxxxxx", "-xxxxxx", "xxx", "0", "226", "228", "sans objet", ".",
         "autorité", "autorite"}

# Le registre stocke les pays en capitales ; la mise en forme automatique de la
# casse écrirait « Côte D'Ivoire ». Les huit États de l'Union et les quelques
# pays tiers rencontrés sont donc nommés explicitement.
PAYS = {
    "BEN": "Bénin", "BFA": "Burkina Faso", "CIV": "Côte d'Ivoire",
    "GNB": "Guinée-Bissau", "MLI": "Mali", "NER": "Niger",
    "SEN": "Sénégal", "TGO": "Togo",
    "FRA": "France", "MUS": "Maurice", "MAR": "Maroc", "NGA": "Nigeria",
}
# Les huit États parties à la Convention : un acteur dont le siège est ailleurs
# intervient sur le marché sans y être établi.
UMOA = ("BEN", "BFA", "CIV", "GNB", "MLI", "NER", "SEN", "TGO")


# --------------------------------------------------------------------------
#  Catégories d'agrément
# --------------------------------------------------------------------------
#
# `types` : identifiants de catégorie utilisés par le registre de l'Autorité.
# `textes` : slugs des documents du recueil qui régissent la catégorie ; ils
#            sont vérifiés à la construction, un slug inconnu arrête le
#            programme plutôt que de produire un lien mort.

@dataclass(frozen=True)
class Categorie:
    cle: str
    types: tuple[int, ...]
    singulier: str
    pluriel: str
    court: str                     # libellé bref, pour les vignettes
    sigle: str
    genre: str                     # « m » ou « f » : accord du chapeau
    role: str                      # une phrase : ce que fait l'acteur
    notice: tuple[str, ...]        # paragraphes de la notice de catégorie
    textes: tuple[str, ...] = ()
    icone: str = "acteurs"


CATEGORIES: dict[str, Categorie] = {}


def _c(cat: Categorie) -> None:
    CATEGORIES[cat.cle] = cat


_c(Categorie(
    cle="bourse", types=(1,), icone="bourse",
    singulier="Bourse", pluriel="Bourses", sigle="BRVM",
    court="Bourse", genre="f",
    role="Organise la cotation et la négociation des valeurs mobilières pour "
         "l'ensemble des huit États de l'Union.",
    notice=(
        "La Bourse Régionale des Valeurs Mobilières est l'une des deux "
        "structures centrales du marché. Elle est titulaire d'une concession "
        "de service public : elle organise le marché des titres cotés, en "
        "assure la cotation et la diffusion des cours, et prononce "
        "l'inscription des sociétés à la cote après le visa de l'Autorité sur "
        "l'opération d'appel public à l'épargne.",
        "Le marché financier régional est unique et commun aux huit États de "
        "l'UMOA : il n'existe qu'une bourse, dont le siège est à Abidjan et "
        "qui dispose d'antennes nationales dans chaque État. Sa gouvernance, "
        "son contrôle interne, ses systèmes d'information et les fonctions "
        "qui y exigent une carte professionnelle font l'objet d'instructions "
        "propres, distinctes de celles applicables aux intervenants "
        "commerciaux.",
    ),
    textes=("instruction-02-1997", "instruction-75-2023", "instruction-77-2023",
            "instruction-79-2023", "instruction-73-2023", "instruction-26-2001",
            "instruction-18-1999", "circulaire-001-2016", "circulaire-002-2016"),
))

_c(Categorie(
    cle="depositaire-central", types=(2,), icone="depositaire",
    singulier="Dépositaire central / Banque de règlement",
    pluriel="Dépositaire central / Banque de règlement", sigle="DC/BR",
    court="Dépositaire central", genre="m",
    role="Conserve les titres à l'échelle du marché et assure le règlement-"
         "livraison des opérations.",
    notice=(
        "Le Dépositaire Central / Banque de Règlement est la seconde structure "
        "centrale. Il tient la comptabilité-titres du marché, dénoue les "
        "opérations en assurant simultanément le règlement des espèces et la "
        "livraison des titres, et exerce les fonctions de banque de règlement "
        "pour le compte des intervenants.",
        "Comme la Bourse, il est concessionnaire de service public et relève "
        "d'un corps d'instructions dédié — gouvernance, contrôle interne, "
        "systèmes d'information, cartes professionnelles. L'inscription en "
        "compte des clients finaux auprès du dépositaire, engagée en 2025, "
        "modifie sensiblement la chaîne de conservation.",
    ),
    textes=("instruction-03-1997", "instruction-76-2023", "instruction-78-2023",
            "instruction-80-2023", "instruction-74-2023", "instruction-81-2025",
            "instruction-26-2001"),
))

_c(Categorie(
    cle="sgi", types=(3,), icone="sgi",
    singulier="Société de gestion et d'intermédiation",
    pluriel="Sociétés de gestion et d'intermédiation", sigle="SGI",
    court="SGI", genre="f",
    role="Seul intermédiaire habilité à négocier les titres cotés ; exerce "
         "aussi la conservation, la gestion sous mandat et le conseil.",
    notice=(
        "Les SGI sont le métier central du marché : elles détiennent le "
        "monopole de la négociation des valeurs mobilières cotées à la BRVM. "
        "Un investisseur, particulier ou institutionnel, ne peut passer un "
        "ordre de bourse que par leur intermédiaire. À titre principal, elles "
        "exercent également la tenue de compte-conservation des titres de "
        "leurs clients ; à titre accessoire, la gestion sous mandat, le "
        "conseil financier et le placement de titres.",
        "L'agrément est délivré par l'Autorité après avis technique des "
        "structures centrales. Il suppose la forme de société anonyme, un "
        "capital social minimum et le respect permanent de normes "
        "prudentielles, des dirigeants titulaires d'une carte "
        "professionnelle, un dispositif de contrôle interne et un système "
        "d'information conforme aux exigences fixées par circulaire. Les "
        "fonds de la clientèle font l'objet d'une obligation de cantonnement.",
    ),
    textes=("instruction-67-2021", "instruction-65-2021", "instruction-62-2020",
            "instruction-04-1997", "instruction-40-2009", "instruction-39-2009",
            "instruction-17-1999", "instruction-20-1999", "instruction-60-2020",
            "instruction-57-2018", "circulaire-001-2019", "circulaire-001-2010"),
))

_c(Categorie(
    cle="tcc", types=(7,), icone="tcc",
    singulier="Teneur de comptes conservateurs",
    pluriel="Teneurs de comptes conservateurs", sigle="TCC",
    court="Teneurs de comptes", genre="m",
    role="Tient les comptes-titres des investisseurs et conserve leurs avoirs.",
    notice=(
        "La tenue de compte-conservation consiste à inscrire les titres au nom "
        "de leur propriétaire et à en assurer la garde. Elle est exercée par "
        "les SGI au titre de leur agrément, et par les banques de l'Union "
        "spécialement agréées à cet effet : c'est cette seconde population que "
        "recense la présente catégorie.",
        "L'ouverture de cette fonction aux banques résulte d'une modification "
        "de l'article 37 du Règlement Général, décidée par le Conseil des "
        "Ministres en 1998 et mise en œuvre par instruction la même année. Les "
        "comptes-titres et espèces sont normalisés, et le sort des comptes "
        "inactifs et des avoirs sans maître est encadré depuis 2022.",
    ),
    textes=("instruction-16-1998",
            "decision-modification-article-37-reglement-general",
            "instruction-68-2021", "instruction-71-2023",
            "decision-cm-10-09-2022", "instruction-81-2025"),
))

_c(Categorie(
    cle="tcgac", types=(1000003200,), icone="tcc",
    singulier="Teneur de compte et gestionnaire des avoirs consignés",
    pluriel="Teneurs de compte et gestionnaires des avoirs consignés",
    sigle="TCGAC",
    court="Avoirs consignés", genre="m",
    role="Caisse des dépôts approuvée pour tenir des comptes-titres et gérer "
         "les avoirs consignés.",
    notice=(
        "Les caisses des dépôts et consignations des États de l'Union peuvent "
        "être approuvées par l'Autorité en qualité de teneur de comptes. "
        "S'y ajoute la gestion des avoirs consignés : les titres et espèces "
        "dont le titulaire ne se manifeste plus, transférés au terme du délai "
        "réglementaire hors des livres du teneur de compte d'origine.",
        "Cette qualité, créée par l'instruction n° 72 de 2023, prolonge le "
        "dispositif sur les comptes inactifs et les avoirs sans maître adopté "
        "par le Conseil des Ministres en 2022.",
    ),
    textes=("instruction-72-2023", "instruction-71-2023",
            "decision-cm-10-09-2022"),
))

_c(Categorie(
    cle="societe-gestion-opc", types=(5,), icone="sgo",
    singulier="Société de gestion d'OPC",
    pluriel="Sociétés de gestion d'organismes de placement collectif",
    sigle="SGO",
    court="Sociétés de gestion d'OPC", genre="f",
    role="Crée et gère les FCP et SICAV : sélectionne les actifs, calcule la "
         "valeur liquidative, rend compte aux porteurs.",
    notice=(
        "Une société de gestion d'organismes de placement collectif conçoit "
        "les fonds — fonds communs de placement et sociétés d'investissement à "
        "capital variable —, en assure la gestion financière et administrative "
        "et répond de leur conformité. Elle n'est pas dépositaire des actifs : "
        "cette fonction revient à un teneur de compte distinct, ce qui protège "
        "les porteurs en séparant la gestion de la garde.",
        "Le régime a été refondu par l'instruction n° 66 de 2021 puis par la "
        "série de seize circulaires de 2022, qui couvrent l'agrément des "
        "fonds, le prospectus, le document d'informations clés, les frais, "
        "l'évaluation des actifs, la gestion de la liquidité et des risques et "
        "les conflits d'intérêts. Une circulaire de 2025 module ces exigences "
        "selon un principe de proportionnalité.",
    ),
    textes=("instruction-66-2021", "circulaire-002-2022", "circulaire-003-2022",
            "circulaire-005-2022", "circulaire-006-2022", "circulaire-010-2022",
            "circulaire-011-2022", "circulaire-012-2022", "circulaire-015-2022",
            "circulaire-016-2022", "circulaire-17-2025", "instruction-45-2011",
            "instruction-n-69-2023"),
))

_c(Categorie(
    cle="sicav", types=(6,), icone="sicav",
    singulier="Société d'investissement à capital variable",
    pluriel="Sociétés d'investissement à capital variable", sigle="SICAV",
    court="SICAV", genre="f",
    role="Organisme de placement collectif constitué en société, dont "
         "l'investisseur devient actionnaire.",
    notice=(
        "La SICAV est l'une des deux formes d'organisme de placement "
        "collectif. À la différence du fonds commun de placement, qui est une "
        "copropriété sans personnalité morale, elle est une société : "
        "l'investisseur y est actionnaire et son capital varie au gré des "
        "souscriptions et des rachats.",
        "Les SICAV agréées figurent au registre en leur nom propre, alors que "
        "les FCP sont rattachés à leur société de gestion. La classification "
        "des organismes, les règles d'allocation d'actifs et les modalités de "
        "transformation d'un FCP en SICAV relèvent d'instructions et "
        "circulaires dédiées.",
    ),
    textes=("instruction-21-1999", "instruction-22-1999", "instruction-46-2011",
            "instruction-66-2021", "instruction-23-1999", "instruction-24-1999",
            "circulaire-001-2022"),
))

_c(Categorie(
    cle="sgp", types=(4,), icone="sgp",
    singulier="Société de gestion de patrimoine",
    pluriel="Sociétés de gestion de patrimoine", sigle="SGP",
    court="Gestion de patrimoine", genre="f",
    role="Gère des portefeuilles de titres pour le compte de tiers, sur "
         "mandat, sans détenir les avoirs.",
    notice=(
        "La société de gestion de patrimoine exerce la gestion individuelle de "
        "portefeuilles : elle prend les décisions d'investissement pour le "
        "compte de son client, dans les limites d'un mandat écrit. Elle ne "
        "conserve ni les titres ni les espèces, qui restent déposés chez un "
        "teneur de compte, et transmet ses ordres à une SGI.",
        "Le régime remonte à l'instruction n° 5 de 1997 ; les tarifs sont "
        "homologués par l'Autorité et l'activité de gestion sous mandat a été "
        "précisée en 2020.",
    ),
    textes=("instruction-05-1997", "instruction-60-2020", "instruction-19-1999",
            "instruction-17-1999"),
))

_c(Categorie(
    cle="societe-gestion-fctc", types=(11,), icone="titrisation",
    singulier="Société de gestion de FCTC",
    pluriel="Sociétés de gestion de fonds communs de titrisation de créances",
    sigle="SG-FCTC",
    court="Titrisation", genre="f",
    role="Constitue et gère les véhicules de titrisation qui transforment des "
         "créances en titres négociables.",
    notice=(
        "La titrisation consiste à céder un portefeuille de créances à un "
        "fonds commun de titrisation, qui finance cette acquisition en "
        "émettant des titres souscrits par des investisseurs. La société de "
        "gestion constitue le fonds, le représente à l'égard des tiers et en "
        "assure la gestion jusqu'à son extinction.",
        "Deux instructions de 2010 séparent l'agrément de la société de "
        "gestion de celui du fonds lui-même, dont la note d'information reçoit "
        "un visa de l'Autorité.",
    ),
    textes=("instruction-44-2010", "instruction-43-2010"),
))

_c(Categorie(
    cle="listing-sponsor", types=(16,), icone="listing",
    singulier="Listing sponsor", pluriel="Listing sponsors", sigle="LS",
    court="Listing sponsors", genre="m",
    role="Accompagne les PME candidates au troisième compartiment de la BRVM "
         "et les suit après l'admission.",
    notice=(
        "Le listing sponsor est né avec le troisième compartiment de la BRVM, "
        "réservé aux petites et moyennes entreprises. Il prépare la société "
        "candidate à l'admission, atteste de la qualité de l'information "
        "diffusée, et l'accompagne durant les années qui suivent son "
        "introduction — période pendant laquelle la présence d'un sponsor est "
        "obligatoire.",
        "La fonction est ouverte à des professions variées : SGI, cabinets "
        "d'expertise comptable, cabinets d'audit et de conseil. Plusieurs "
        "sociétés figurent donc au registre à la fois comme SGI et comme "
        "listing sponsor, au titre de deux agréments distincts.",
    ),
    textes=("instruction-55-2018", "instruction-52-2017"),
))

_c(Categorie(
    cle="conseil-investissement-boursier", types=(9,), icone="conseil",
    singulier="Conseil en investissements boursiers",
    pluriel="Conseils en investissements boursiers", sigle="CIB",
    court="Conseils (CIB)", genre="m",
    role="Fournit des recommandations d'investissement à titre habituel, sans "
         "recevoir de fonds ni de titres.",
    notice=(
        "Le conseil en investissements boursiers analyse les valeurs et "
        "formule des recommandations à ses clients. Il ne reçoit ni fonds ni "
        "titres, ne passe pas d'ordres et n'exerce aucune gestion : c'est ce "
        "qui le distingue de la société de gestion de patrimoine.",
        "L'activité relève d'une habilitation — et non d'un agrément au sens "
        "plein — délivrée dans les mêmes formes que celle des apporteurs "
        "d'affaires et des démarcheurs, régime refondu par l'instruction "
        "n° 53 de 2017.",
    ),
    textes=("instruction-53-2017", "instruction-06-1997"),
))

_c(Categorie(
    cle="apporteur-affaires", types=(8,), icone="apporteur",
    singulier="Apporteur d'affaires", pluriel="Apporteurs d'affaires",
    sigle="AA",
    court="Apporteurs d'affaires", genre="m",
    role="Met en relation des investisseurs avec les intervenants agréés, sans "
         "manier ni fonds ni titres.",
    notice=(
        "L'apporteur d'affaires prospecte la clientèle et l'oriente vers un "
        "intervenant agréé, dont il est le correspondant. Il ne peut ni "
        "recevoir de fonds, ni détenir de titres, ni exécuter d'ordres : son "
        "rôle s'arrête à la mise en relation, rémunérée par l'intervenant "
        "auquel il apporte l'affaire.",
        "C'est la catégorie la plus nombreuse du registre, et la seule où "
        "figurent des personnes physiques à côté de sociétés. L'habilitation "
        "est délivrée pour une durée déterminée et renouvelable ; elle "
        "s'éteint faute de renouvellement, ce qui explique le nombre "
        "d'habilitations aujourd'hui inactives.",
    ),
    textes=("instruction-53-2017", "instruction-06-1997"),
))

_c(Categorie(
    cle="agence-notation", types=(13,), icone="notation",
    singulier="Agence de notation", pluriel="Agences de notation", sigle="AN",
    court="Agences de notation", genre="f",
    role="Évalue la qualité de crédit des émetteurs et des titres offerts au "
         "public.",
    notice=(
        "La notation financière est une condition pratique de l'appel public à "
        "l'épargne par emprunt obligataire : l'émetteur qui n'apporte pas de "
        "garantie approuvée doit présenter une notation délivrée par une "
        "agence reconnue par l'Autorité.",
        "Les conditions d'exercice — indépendance, méthodologie publiée, "
        "prévention des conflits d'intérêts — sont fixées par l'instruction "
        "n° 37 de 2009.",
    ),
    textes=("instruction-37-2009", "instruction-38-2009"),
))

_c(Categorie(
    cle="organisme-garantie", types=(12,), icone="garantie",
    singulier="Organisme de garantie", pluriel="Organismes de garantie",
    sigle="OG",
    court="Organismes de garantie", genre="m",
    role="Garantit le remboursement d'emprunts obligataires émis par appel "
         "public à l'épargne.",
    notice=(
        "Un émetteur qui n'est pas noté doit faire garantir son emprunt. "
        "L'organisme garant s'engage à première demande à payer les échéances "
        "défaillantes, ce qui reporte sur lui le risque de crédit supporté par "
        "les souscripteurs. Sa capacité à tenir cet engagement est examinée "
        "par l'Autorité, qui l'approuve opération par opération.",
        "On y trouve des institutions financières de développement régionales "
        "et internationales, dont certaines n'ont pas leur siège dans l'Union.",
    ),
    textes=("instruction-38-2009", "circulaire-004-2004"),
))


ORDRE = list(CATEGORIES)
TYPE_VERS_CLE = {t: c.cle for c in CATEGORIES.values() for t in c.types}

# Textes qui s'appliquent à tous les acteurs agréés, quelle que soit la
# catégorie : ils sont rappelés une fois sur la page d'ensemble plutôt que
# répétés dans chaque notice.
TEXTES_COMMUNS = (
    ("reglement-general",
     "Fixe les conditions d'agrément et les obligations des intervenants."),
    ("instruction-64-2020",
     "Conditions de traitement des dossiers de demande d'agrément."),
    ("instruction-51-2016",
     "Avis technique des structures centrales dans le processus d'agrément."),
    ("instruction-32-2005",
     "Procédure de retrait d'agrément des intervenants agréés."),
    ("circulaire-001-2021",
     "Modification du capital ou de l'actionnariat d'un intervenant agréé."),
    ("instruction-41-2009-2",
     "Délivrance des cartes professionnelles."),
    ("instruction-61-2020",
     "Organisation du système de contrôle interne des acteurs."),
    ("instruction-59-2019-2",
     "Lutte contre le blanchiment, le financement du terrorisme et de la "
     "prolifération."),
    ("instruction-58-2019",
     "Commissariat aux comptes auprès des structures agréées."),
    ("instruction-27-2001",
     "Informations que les intervenants commerciaux transmettent à l'Autorité."),
    ("instruction-39-2009",
     "Implantation d'un intervenant hors de son État de siège."),
    ("instruction-54-2017",
     "Redevances, frais et commissions perçus par l'Autorité."),
    ("instruction-50-2016",
     "Traitement des plaintes et réclamations."),
    ("instruction-56-2018",
     "Procédure de prise de sanctions."),
)


# --------------------------------------------------------------------------
#  Normalisation
# --------------------------------------------------------------------------

def slugifier(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.replace("’", "'"))
                if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.replace("°", "")).lower()
    return re.sub(r"-{2,}", "-", t).strip("-")[:70]


def _propre(v) -> str:
    """Nettoie une valeur du registre ; renvoie une chaîne vide si elle est
    de remplissage."""
    if v is None:
        return ""
    t = re.sub(r"\s+", " ", str(v)).strip().strip(";,")
    return "" if t.lower() in VIDES else t


def _jour(v) -> str:
    t = _propre(v)
    if not t:
        return ""
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00")).date()
    except ValueError:
        return ""
    # Le registre porte quelques dates sentinelles (1900-01-01, 1905-06-21)
    # qui signifient « inconnue » plutôt qu'une date réelle.
    return "" if d.year < 1990 else d.isoformat()


def _adresse(v: str) -> str:
    t = _propre(v)
    t = re.sub(r"[\s.,;:-]*Adresse\s+Postale\s*:?\s*$", "", t, flags=re.I)
    return t.strip(" .,;:-")


def _site(v: str) -> str:
    t = _propre(v)
    if not t or "@" in t:          # quelques courriels égarés dans la colonne
        return ""
    if not t.startswith(("http://", "https://")):
        t = "https://" + t.lstrip("/")
    return t if re.match(r"^https?://[\w.-]+\.[a-z]{2,}", t, re.I) else ""


def _courriels(v: str) -> list[str]:
    """Toutes les adresses électroniques d'un champ du registre.

    L'Autorité y concatène parfois plusieurs adresses, séparées par une barre
    oblique, un point-virgule ou une espace. Elles sont toutes reprises.
    """
    t = _propre(v)
    if not t:
        return []
    vues, sortie = set(), []
    for m in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t):
        adresse = m.strip(" .,;")
        if adresse.lower() not in vues:
            vues.add(adresse.lower())
            sortie.append(adresse)
    return sortie


def _numeros(v: str) -> list[str]:
    """Numéros de téléphone d'un champ, séparés par « / » ou « ; »."""
    t = _propre(v)
    if not t:
        return []
    bouts = [b.strip(" .,;-") for b in re.split(r"\s*[;/]\s*|\s{2,}", t)]
    return [b for b in bouts if sum(c.isdigit() for c in b) >= 6]


def normaliser(brut: dict) -> dict | None:
    """Convertit un enregistrement du registre en fiche du recueil.

    Renvoie None pour les catégories que le recueil ne présente pas.
    """
    type_id = brut.get("typeId")
    cle = TYPE_VERS_CLE.get(int(type_id)) if type_id is not None else None
    if not cle:
        return None

    nom = _propre(brut.get("lib"))
    if not nom:
        return None

    forme = _propre(brut.get("formeJuridiqueLib"))
    personne_physique = forme.lower().startswith("personne physique")

    code_pays = _propre(brut.get("paysCode")).upper()
    fiche = {
        "id": str(brut.get("id")),
        "code": _propre(brut.get("code")),
        "reference": _propre(brut.get("ref")),
        "nom": nom,
        "slug": slugifier(nom),
        "categorie": cle,
        "pays": PAYS.get(code_pays) or _propre(brut.get("paysLib")).capitalize(),
        "pays_code": code_pays,
        "hors_umoa": bool(code_pays) and code_pays not in UMOA,
        "forme_juridique": forme,
        "personne_physique": personne_physique,
        "siege": _adresse(brut.get("siege")),
        "boite_postale": _propre(brut.get("bp")),
        "rccm": _propre(brut.get("rccm")),
        "agrement": re.sub(r"\s*/\s*", "/", _propre(brut.get("agrement"))),
        "date_agrement": _jour(brut.get("dateAgrement")),
        "date_entree_marche": _jour(brut.get("dateEntreMarche")),
        "date_creation": _jour(brut.get("dateCreation")),
        "decision": _propre(brut.get("decision")),
        "actif": brut.get("actif") in (True, "true"),
        "retire_du_registre": brut.get("isDeleted") in (True, "true"),
    }

    # Toutes les coordonnées publiées au registre sont reprises, pour les
    # personnes physiques habilitées comme pour les sociétés : l'Autorité les
    # publie au titre de l'agrément, et un correspondant joignable est le
    # premier usage attendu d'un annuaire.
    fiche["site_web"] = _site(brut.get("siteWeb"))
    fiche["courriels"] = _courriels(brut.get("mail"))
    fiche["telephones"] = _numeros(brut.get("telephone"))
    fiche["fax"] = _numeros(brut.get("fax"))

    return fiche


def _cle_tri(f: dict) -> tuple:
    return (ORDRE.index(f["categorie"]), 0 if f["actif"] else 1,
            sans_accent(f["nom"]))


def sans_accent(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn").upper()


def desambiguiser(fiches: list[dict]) -> list[dict]:
    """Rend les slugs uniques à l'intérieur d'une même catégorie.

    Deux sociétés homonymes existent au registre (même nom, même catégorie,
    agréments distincts) ; on suffixe alors par l'année d'agrément puis par
    l'identifiant.
    """
    vus: dict[tuple[str, str], int] = {}
    for f in fiches:
        base = f["slug"]
        k = (f["categorie"], base)
        if k not in vus:
            vus[k] = 1
            continue
        vus[k] += 1
        annee = f["date_agrement"][:4]
        f["slug"] = f"{base}-{annee}" if annee else f"{base}-{f['id']}"
        if (f["categorie"], f["slug"]) in vus:
            f["slug"] = f"{base}-{f['id']}"
        vus[(f["categorie"], f["slug"])] = 1
    return fiches


# --------------------------------------------------------------------------
#  Collecte
# --------------------------------------------------------------------------

def _lire(url: str, delai: int = 120):
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def interroger(taille: int = 25, pages_max: int = 60) -> list[dict]:
    """Parcourt le registre page par page.

    La taille de page reste modeste : au-delà, le service renvoie une erreur
    de dépassement de tampon, car chaque enregistrement peut embarquer la
    décision d'agrément en pièce jointe.
    """
    bruts: list[dict] = []
    for page in range(pages_max):
        lot = _lire(API_ACTEURS.format(taille=taille, page=page))
        if not isinstance(lot, list):
            raise SystemExit(f"Réponse inattendue du registre : {str(lot)[:200]}")
        for a in lot:
            a.pop("decisionBytes", None)
            a.pop("codeSecret", None)
            bruts.append(a)
        if len(lot) < taille:
            break
    return bruts


def construire_jeu(bruts: list[dict], releve: str | None = None) -> dict:
    fiches = [f for f in (normaliser(b) for b in bruts) if f]
    # Le registre sert quelques doublons stricts (même identifiant, même code).
    uniques: dict[tuple, dict] = {}
    for f in fiches:
        uniques.setdefault((f["id"], f["code"], f["categorie"]), f)
    fiches = desambiguiser(sorted(uniques.values(), key=_cle_tri))
    return {
        "source": REGISTRE,
        "api": API_ACTEURS.format(taille=25, page=0),
        "releve": releve or date.today().isoformat(),
        "nombre": len(fiches),
        "acteurs": fiches,
    }


def consigner(diff: dict, jeu: dict, journal: Path) -> Path:
    """Écrit le relevé des mouvements d'agrément dans le journal du recueil."""
    journal.mkdir(parents=True, exist_ok=True)
    lignes = [f"# Relevé des agréments du {jeu['releve']}", "",
              f"{jeu['nombre']} inscriptions au registre de l'AMF-UMOA, dont "
              f"{sum(1 for a in jeu['acteurs'] if a['actif'])} actives.", ""]

    def bloc(titre: str, fiches: list[dict]) -> None:
        lignes.append(f"## {titre} ({len(fiches)})")
        lignes.append("")
        if not fiches:
            lignes.extend(["Aucun.", ""])
            return
        for f in sorted(fiches, key=lambda x: x["nom"]):
            cat = CATEGORIES[f["categorie"]].sigle
            lignes.append(f"- **{f['nom']}** — {cat}, {f['pays']}"
                          + (f", agrément {f['agrement']}" if f["agrement"] else "")
                          + (f" du {f['date_agrement']}" if f["date_agrement"] else ""))
        lignes.append("")

    bloc("Nouveaux inscrits", diff["entrants"])
    bloc("Retirés du registre", diff["sortants"])

    lignes.append(f"## Fiches modifiées ({len(diff['changements'])})")
    lignes.append("")
    if diff["changements"]:
        for c in sorted(diff["changements"], key=lambda x: x["nom"]):
            details = " ; ".join(f"{champ} : « {av} » → « {ap} »"
                                 for champ, av, ap in c["ecarts"])
            lignes.append(f"- **{c['nom']}** — {details}")
    else:
        lignes.append("Aucune.")
    lignes.append("")

    texte = "\n".join(lignes)
    (journal / f"agrements-{jeu['releve']}.md").write_text(texte, encoding="utf-8")
    dernier = journal / "derniers-agrements.md"
    dernier.write_text(texte, encoding="utf-8")
    return dernier


def comparer(ancien: dict | None, nouveau: dict) -> dict:
    """Différence entre deux relevés, pour le journal de veille."""
    if not ancien:
        return {"entrants": [], "sortants": [], "changements": []}
    ida = {(a["id"], a["categorie"]): a for a in ancien.get("acteurs", [])}
    idn = {(a["id"], a["categorie"]): a for a in nouveau["acteurs"]}
    suivis = ("nom", "agrement", "date_agrement", "actif", "siege", "site_web",
              "courriels", "telephones")
    changements = []
    for k, a in idn.items():
        v = ida.get(k)
        if not v:
            continue
        ecarts = [(c, v.get(c), a.get(c)) for c in suivis if v.get(c) != a.get(c)]
        if ecarts:
            changements.append({"nom": a["nom"], "categorie": a["categorie"],
                                "ecarts": ecarts})
    return {
        "entrants": [idn[k] for k in idn.keys() - ida.keys()],
        "sortants": [ida[k] for k in ida.keys() - idn.keys()],
        "changements": changements,
    }


# --------------------------------------------------------------------------
#  Chargement pour la construction du site
# --------------------------------------------------------------------------

@dataclass
class Acteur:
    donnees: dict = field(repr=False)

    def __getattr__(self, nom):
        try:
            return self.donnees[nom]
        except KeyError as exc:
            raise AttributeError(nom) from exc

    @property
    def cat(self) -> Categorie:
        return CATEGORIES[self.donnees["categorie"]]

    @property
    def chemin(self) -> str:
        return f"{self.donnees['categorie']}/{self.donnees['slug']}"

    @property
    def statut(self) -> tuple[str, str]:
        return ("En activité", "actif") if self.donnees["actif"] \
            else ("Non actif au registre", "inactif")


def charger(chemin: Path) -> tuple[list[Acteur], str]:
    """Renvoie (acteurs, date du relevé). Liste vide si le fichier manque."""
    if not chemin.exists():
        return [], ""
    jeu = json.loads(chemin.read_text(encoding="utf-8"))
    acteurs = [Acteur(a) for a in jeu.get("acteurs", [])]
    inconnues = {a.categorie for a in acteurs} - set(CATEGORIES)
    if inconnues:
        raise SystemExit(f"Catégories d'acteurs inconnues : {sorted(inconnues)}")
    return acteurs, jeu.get("releve", "")


def par_categorie(acteurs: list[Acteur]) -> dict[str, list[Acteur]]:
    groupes: dict[str, list[Acteur]] = {c: [] for c in ORDRE}
    for a in acteurs:
        groupes[a.categorie].append(a)
    return {c: g for c, g in groupes.items() if g}


def homologues(acteur: Acteur, acteurs: list[Acteur]) -> list[Acteur]:
    """Autres agréments détenus par la même société (même RCCM, ou même nom)."""
    rccm = re.sub(r"[^A-Z0-9]", "", sans_accent(acteur.rccm or ""))
    nom = sans_accent(acteur.nom)
    out = []
    for b in acteurs:
        if b is acteur or b.chemin == acteur.chemin:
            continue
        b_rccm = re.sub(r"[^A-Z0-9]", "", sans_accent(b.rccm or ""))
        if (rccm and len(rccm) > 6 and b_rccm == rccm) or sans_accent(b.nom) == nom:
            out.append(b)
    return out


# --------------------------------------------------------------------------
#  Ligne de commande
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("collecter", help="interroge le registre de l'AMF-UMOA")
    c.add_argument("--sortie", default="acteurs/acteurs.json")
    c.add_argument("--depuis-brut", help="fichier JSON déjà téléchargé "
                                         "(liste d'enregistrements du registre)")
    c.add_argument("--releve", help="date du relevé (par défaut : aujourd'hui)")
    c.add_argument("--journal", help="dossier où consigner les mouvements")
    a = ap.parse_args()

    if a.depuis_brut:
        bruts = json.loads(Path(a.depuis_brut).read_text(encoding="utf-8"))
    else:
        try:
            bruts = interroger()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Registre injoignable : {exc}", file=sys.stderr)
            return 1

    jeu = construire_jeu(bruts, a.releve)
    sortie = Path(a.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)

    ancien = json.loads(sortie.read_text(encoding="utf-8")) if sortie.exists() else None
    diff = comparer(ancien, jeu)

    sortie.write_text(json.dumps(jeu, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")

    groupes: dict[str, int] = {}
    for f in jeu["acteurs"]:
        groupes[f["categorie"]] = groupes.get(f["categorie"], 0) + 1
    print(f"{jeu['nombre']} acteurs écrits dans {sortie} (relevé {jeu['releve']})")
    for cle in ORDRE:
        if cle in groupes:
            print(f"  {groupes[cle]:>4}  {CATEGORIES[cle].pluriel}")
    if a.journal:
        chemin = consigner(diff, jeu, Path(a.journal))
        print(f"  mouvements consignés dans {chemin}")

    if ancien:
        print(f"  entrants : {len(diff['entrants'])} · "
              f"sortants : {len(diff['sortants'])} · "
              f"modifiés : {len(diff['changements'])}")
        for f in diff["entrants"]:
            print(f"    + {f['nom']} ({CATEGORIES[f['categorie']].sigle})")
        for f in diff["sortants"]:
            print(f"    − {f['nom']} ({CATEGORIES[f['categorie']].sigle})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
