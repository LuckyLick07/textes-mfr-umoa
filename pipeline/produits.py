#!/usr/bin/env python3
"""
Registre des organismes de placement collectif agréés par l'AMF-UMOA.

Pendant du module `acteurs.py`, pour les produits : là où celui-ci recense
qui peut exercer, celui-ci recense ce qui a été agréé — les fonds communs de
placement, les fonds de titrisation, les SICAV et les véhicules apparentés.

La source est le registre public de l'Autorité :

    https://www.amf-umoa.org/service/api/elastic/fcp?size=50&page=N

Chaque organisme est rattaché à sa société de gestion, laquelle figure déjà
au registre des acteurs : la fiche d'un fonds renvoie à celle de son gérant,
et réciproquement.

Usage :
    produits.py collecter --sortie produits/opc.json
    produits.py collecter --depuis-tsv brut/fcp.tsv --sortie produits/opc.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from acteurs import NAVIGATEUR, VIDES, sans_accent, slugifier

AMF = "https://www.amf-umoa.org"
API_OPC = AMF + "/service/api/elastic/fcp?size={taille}&page={page}"
REGISTRE = AMF + "/accueil/opcvm"


# --------------------------------------------------------------------------
#  Familles d'organismes
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Famille:
    cle: str
    types: tuple[int, ...]
    singulier: str
    pluriel: str
    court: str
    sigle: str
    genre: str
    role: str
    notice: tuple[str, ...]
    textes: tuple[str, ...] = ()
    icone: str = "sgo"


FAMILLES: dict[str, Famille] = {}


def _f(f: Famille) -> None:
    FAMILLES[f.cle] = f


_f(Famille(
    cle="fcp", types=(1,), icone="sgo",
    singulier="Fonds commun de placement",
    pluriel="Fonds communs de placement",
    court="FCP", sigle="FCP", genre="m",
    role="Copropriété de valeurs mobilières ouverte à l'épargne, gérée pour le "
         "compte des porteurs de parts.",
    notice=(
        "Le fonds commun de placement est la forme la plus répandue de "
        "l'épargne collective dans l'Union. Il n'a pas la personnalité "
        "morale : c'est une copropriété d'instruments financiers, dont "
        "l'investisseur détient des parts. Une société de gestion agréée "
        "l'administre, arrête sa politique d'investissement et calcule sa "
        "valeur liquidative ; un teneur de compte distinct en conserve les "
        "actifs.",
        "L'agrément du fonds est distinct de celui de sa société de gestion. "
        "Il suppose un prospectus, un document d'informations clés destiné à "
        "l'investisseur, et le respect de règles d'allocation d'actifs qui "
        "bornent la concentration des risques. Les frais, l'évaluation des "
        "actifs et les outils de gestion de la liquidité relèvent de "
        "circulaires propres.",
    ),
    textes=("instruction-66-2021", "circulaire-003-2022", "circulaire-005-2022",
            "circulaire-006-2022", "circulaire-011-2022", "circulaire-012-2022",
            "circulaire-014-2022", "instruction-46-2011", "instruction-45-2011",
            "instruction-22-1999"),
))

_f(Famille(
    cle="sicav", types=(2,), icone="sicav",
    singulier="Société d'investissement à capital variable",
    pluriel="Sociétés d'investissement à capital variable",
    court="SICAV", sigle="SICAV", genre="f",
    role="Organisme de placement collectif constitué en société, dont "
         "l'investisseur devient actionnaire.",
    notice=(
        "La SICAV poursuit le même objet qu'un fonds commun de placement, mais "
        "sous forme de société anonyme : l'investisseur y est actionnaire et "
        "non copropriétaire, et son capital varie au gré des souscriptions et "
        "des rachats.",
        "La forme reste rare dans l'Union — quelques unités seulement — la "
        "place lui préférant le fonds commun, plus léger à constituer. Une "
        "circulaire encadre la transformation d'un FCP en SICAV.",
    ),
    textes=("instruction-66-2021", "instruction-21-1999", "instruction-22-1999",
            "circulaire-001-2022", "instruction-46-2011"),
))

_f(Famille(
    cle="fcpr", types=(3,), icone="sgp",
    singulier="Fonds commun de placement à risques",
    pluriel="Fonds communs de placement à risques",
    court="FCPR", sigle="FCPR", genre="m",
    role="Fonds investi en titres d'entreprises non cotées, au service du "
         "capital-investissement.",
    notice=(
        "Le fonds commun de placement à risques finance des entreprises qui "
        "ne sont pas admises à la cote. Son actif est donc peu liquide et son "
        "horizon long, ce qui le réserve en pratique aux investisseurs "
        "avertis et aux institutionnels.",
        "Le registre y range aussi plusieurs fonds d'épargne salariale "
        "constitués au profit du personnel d'une entreprise déterminée.",
    ),
    textes=("instruction-66-2021", "instruction-46-2011", "circulaire-015-2022"),
))

_f(Famille(
    cle="fctc", types=(4,), icone="titrisation",
    singulier="Fonds commun de titrisation de créances",
    pluriel="Fonds communs de titrisation de créances",
    court="Titrisation", sigle="FCTC", genre="m",
    role="Véhicule qui acquiert un portefeuille de créances et le finance en "
         "émettant des titres.",
    notice=(
        "Le fonds commun de titrisation de créances acquiert des créances — "
        "crédits immobiliers, factures d'énergie, encours bancaires — et "
        "finance cette acquisition en émettant des titres souscrits par des "
        "investisseurs. Les flux des créances remboursent les titres : le "
        "risque passe du cédant au marché.",
        "Le fonds est constitué et représenté par une société de gestion "
        "spécialement agréée. Il est souvent découpé en compartiments, chacun "
        "portant sa propre émission — d'où les intitulés à tranches et à "
        "millésimes que porte le registre.",
    ),
    textes=("instruction-43-2010", "instruction-44-2010"),
))

_f(Famille(
    cle="fces", types=(999954,), icone="garantie",
    singulier="Fonds commun d'émission de sukuks",
    pluriel="Fonds communs d'émission de sukuks",
    court="Sukuks", sigle="FCES", genre="m",
    role="Véhicule d'émission de certificats d'investissement conformes aux "
         "principes de la finance islamique.",
    notice=(
        "Le sukuk n'est pas un titre de dette au sens classique : il "
        "représente une part de propriété dans un actif sous-jacent, dont le "
        "porteur perçoit les revenus. Cette construction permet aux États et "
        "aux entreprises de l'Union de lever des fonds auprès d'investisseurs "
        "attachés aux principes de la finance islamique.",
        "Plusieurs États de l'Union y ont eu recours. Le montage passe par un "
        "fonds dédié, agréé et administré comme un véhicule de titrisation, "
        "et se double d'un conseil de conformité aux principes de la finance "
        "islamique.",
    ),
    textes=("instruction-n-69-2023", "instruction-70-2023", "instruction-43-2010"),
))

_f(Famille(
    cle="fcpe", types=(999953,), icone="sgp",
    singulier="Fonds commun de placement d'entreprise",
    pluriel="Fonds communs de placement d'entreprise",
    court="Épargne salariale", sigle="FCPE", genre="m",
    role="Fonds constitué au profit des salariés d'une entreprise déterminée.",
    notice=(
        "Le fonds commun de placement d'entreprise accueille l'épargne "
        "constituée par les salariés d'une même entreprise, souvent en vue de "
        "la retraite. Sa souscription est réservée à ce collectif.",
        "La catégorie reste marginale au registre, plusieurs fonds "
        "d'entreprise étant classés parmi les fonds à risques ou les fonds "
        "communs ordinaires selon leur composition.",
    ),
    textes=("instruction-66-2021", "instruction-46-2011"),
))


ORDRE = list(FAMILLES)
TYPE_VERS_CLE = {t: f.cle for f in FAMILLES.values() for t in f.types}

TEXTES_COMMUNS = (
    ("instruction-66-2021",
     "Régime d'ensemble des organismes de placement collectif et de leurs "
     "sociétés de gestion."),
    ("circulaire-002-2022",
     "Agrément, modification et retrait d'agrément des sociétés de gestion d'OPC."),
    ("circulaire-003-2022",
     "Pièces à joindre à la demande d'agrément d'un OPC."),
    ("circulaire-004-2022", "Contrat et missions du dépositaire."),
    ("circulaire-005-2022", "Contenu du prospectus."),
    ("circulaire-006-2022", "Document d'informations clés remis à l'investisseur."),
    ("circulaire-007-2022", "Exigences en matière de communications publicitaires."),
    ("circulaire-008-2022", "Rapports périodiques."),
    ("circulaire-011-2022", "Frais supportés par l'organisme."),
    ("circulaire-012-2022", "Évaluation de l'organisme et de ses actifs."),
    ("circulaire-013-2022", "Classes de parts et d'actions."),
    ("circulaire-014-2022", "Outils de gestion de la liquidité."),
    ("circulaire-015-2022", "Gestion des risques."),
    ("circulaire-016-2022", "Conflits d'intérêts et règles de conduite."),
    ("circulaire-17-2025",
     "Proportionnalité des exigences applicables aux sociétés de gestion."),
)


# --------------------------------------------------------------------------
#  Normalisation
# --------------------------------------------------------------------------

def _propre(v) -> str:
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
    return "" if d.year < 1990 else d.isoformat()


# Les intitulés du registre sont saisis en capitales et sans accents. Ce relevé,
# établi sur le vocabulaire réellement présent dans les dénominations de fonds,
# rétablit l'orthographe.
MOTS = {
    "ETAT": "État", "ETATS": "États", "SENEGAL": "Sénégal", "BENIN": "Bénin",
    "COTE": "Côte", "ENERGIES": "Énergies", "ENERGIE": "Énergie",
    "TRESOR": "Trésor", "TRESORERIE": "Trésorerie", "SECURITE": "Sécurité",
    "SERENITE": "Sérénité", "QUIETUDE": "Quiétude", "DIVERSIFIE": "Diversifié",
    "MONETAIRE": "Monétaire", "LIQUIDITE": "Liquidité", "EPARGNE": "Épargne",
    "EMISSION": "Émission", "CREANCES": "Créances", "SOCIETE": "Société",
    "ELITE": "Élite", "DEDIE": "Dédié", "PROSPERITE": "Prospérité",
    "SOLIDARITE": "Solidarité", "ETHIQUE": "Éthique", "GENERAL": "Général",
    "GENERALE": "Générale", "DEVELOPPEMENT": "Développement",
    "RESERVE": "Réserve", "PREMIERE": "Première", "REGIONAL": "Régional",
    "REGIONALE": "Régionale", "PLACEMENT": "Placement", "COMPLEMENTAIRE":
    "Complémentaire", "PREVOYANCE": "Prévoyance", "IMMOBILIERE": "Immobilière",
    "SANTE": "Santé", "AVENIR": "Avenir", "OPPORTUNITES": "Opportunités",
    "DUREE": "Durée", "MARCHE": "Marché", "TITRISATION": "Titrisation",
    "EMERGENCE": "Émergence", "IVOIRE": "Ivoire", "SUR": "Sûr",
    "SENEGAL": "Sénégal", "DIVERSIFIEE": "Diversifiée",
    "EQUILIBRE": "Équilibré", "SECURISE": "Sécurisé",
}

# Sigles et raisons sociales qui restent en capitales dans un intitulé.
SIGLES = {
    "FCP", "FCPE", "FCPR", "FCTC", "FCES", "SICAV", "OPC", "OPCVM", "RMBS",
    "BOA", "BOAD", "NSIA", "CGF", "BNI", "BNDE", "SOAGA", "ALC", "KF", "BSIC",
    "SONATEL", "SENELEC", "SONABHY", "SONABEL", "SODECI", "SODEFOR", "CNRA",
    "CIE", "IFC", "DP", "PME", "UEMOA", "SN", "CI", "EPT", "NME", "SCCI",
    "BHS", "UCA", "AAM", "PAM", "SGO", "SMF", "BRM", "GAAM", "IAM", "KAM",
    "BAM", "SG", "AGA", "MAC", "CRAT", "CRBC", "COFINA", "ZAKA", "SUKUK",
    "IJARA", "SOGEPA", "ATOM", "DPCI", "BNETD", "CMT", "FI", "FS", "WAEMU",
    "UCAWAL", "OAM", "TAWFIR", "HALAL",
}


def _nom_propre(t: str) -> str:
    """Rend lisible un intitulé saisi en capitales, sans toucher aux sigles,
    aux taux, aux millésimes ni aux mentions de compartiment."""
    t = _propre(t)
    lettres = [c for c in t if c.isalpha()]
    if not lettres or sum(c.isupper() for c in lettres) / len(lettres) <= 0.85:
        return t
    petits = {"de", "du", "des", "et", "en", "la", "le", "les", "à", "au", "aux",
              "pour", "d", "l"}

    def segment(bout: str, premier: bool) -> str:
        """Un fragment sans séparateur : sigle conservé, mot accentué, sinon
        capitale initiale."""
        haut = bout.upper()
        if haut in MOTS:
            return MOTS[haut]
        if haut in SIGLES:
            return haut
        bas = bout.lower()
        return bas if (not premier and bas in petits) else bas.capitalize()

    mots = []
    for i, mot in enumerate(t.split(" ")):
        if re.search(r"\d", mot) or "%" in mot:
            mots.append(mot)
            continue
        # Les traits d'union et les apostrophes séparent deux mots pleins :
        # « SAMBA-NSIA » et « D'IVOIRE » doivent l'un et l'autre être traités
        # segment par segment.
        bouts = re.split(r"([-'’])", mot)
        rendu, premier = [], i == 0
        for bout in bouts:
            if bout in "-'’":
                rendu.append(bout)
                continue
            if bout:
                rendu.append(segment(bout, premier or len(rendu) > 0))
        mots.append("".join(rendu))
    return " ".join(mots)


def normaliser(brut: dict) -> dict | None:
    type_id = brut.get("typeFcpId")
    cle = TYPE_VERS_CLE.get(int(type_id)) if str(type_id).lstrip("-").isdigit() else None
    if not cle:
        return None
    nom = _propre(brut.get("lib"))
    if not nom:
        return None
    return {
        "id": str(brut.get("id")),
        "code": _propre(brut.get("code")),
        "nom": nom,
        "nom_lisible": _nom_propre(nom),
        "slug": slugifier(nom),
        "famille": cle,
        "societe_gestion": _propre(brut.get("acteurLib")),
        "societe_gestion_id": str(brut.get("acteurId") or ""),
        "agrement": re.sub(r"\s*/\s*", "/", _propre(brut.get("agrement"))),
        "date_agrement": _jour(brut.get("dateAgrement")),
        "note_information": _propre(brut.get("noteInfo")),
        "decision": _propre(brut.get("decision")),
        "prospectus": _propre(brut.get("prospectusUrl")),
        "actif": brut.get("actif") in (True, "true"),
        "retire_du_registre": brut.get("isDeleted") in (True, "true"),
    }


def _cle_tri(f: dict) -> tuple:
    return (ORDRE.index(f["famille"]), 0 if f["actif"] else 1,
            f["date_agrement"] or "", sans_accent(f["nom"]))


def desambiguiser(fiches: list[dict]) -> list[dict]:
    """Le registre porte des homonymes stricts (même fonds réagréé, tranches
    successives d'un compartiment) : le slug est suffixé par le millésime puis
    par l'identifiant."""
    vus: dict[tuple[str, str], int] = {}
    for f in fiches:
        base, k = f["slug"], (f["famille"], f["slug"])
        if k not in vus:
            vus[k] = 1
            continue
        annee = f["date_agrement"][:4]
        f["slug"] = f"{base}-{annee}" if annee else f"{base}-{f['id']}"
        if (f["famille"], f["slug"]) in vus:
            f["slug"] = f"{base}-{f['id']}"
        vus[(f["famille"], f["slug"])] = 1
    return fiches


# --------------------------------------------------------------------------
#  Collecte
# --------------------------------------------------------------------------

def interroger(taille: int = 50, pages_max: int = 60) -> list[dict]:
    bruts: list[dict] = []
    for page in range(pages_max):
        requete = urllib.request.Request(API_OPC.format(taille=taille, page=page),
                                         headers={"User-Agent": NAVIGATEUR})
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            lot = json.loads(reponse.read().decode("utf-8"))
        if not isinstance(lot, list):
            raise SystemExit(f"Réponse inattendue : {str(lot)[:200]}")
        for o in lot:
            for lourd in ("noteInfoBytes", "decisionBytes", "prospectusBytes",
                          "codeSecret"):
                o.pop(lourd, None)
            bruts.append(o)
        if len(lot) < taille:
            break
    return bruts


def depuis_tsv(chemin: Path) -> list[dict]:
    """Relevé déposé par le navigateur, le bac à sable n'atteignant pas l'API."""
    lignes = chemin.read_text(encoding="utf-8").rstrip("\n").split("\n")
    colonnes = lignes[0].split("§")
    return [dict(zip(colonnes, l.split("§"))) for l in lignes[1:]
            if l.count("§") == len(colonnes) - 1]


def construire_jeu(bruts: list[dict], releve: str | None = None) -> dict:
    fiches = [f for f in (normaliser(b) for b in bruts) if f]
    uniques: dict[tuple, dict] = {}
    for f in fiches:
        uniques.setdefault((f["id"], f["code"]), f)
    fiches = desambiguiser(sorted(uniques.values(), key=_cle_tri))
    return {
        "source": REGISTRE,
        "api": API_OPC.format(taille=50, page=0),
        "releve": releve or date.today().isoformat(),
        "nombre": len(fiches),
        "opc": fiches,
    }


def comparer(ancien: dict | None, nouveau: dict) -> dict:
    if not ancien:
        return {"entrants": [], "sortants": [], "changements": []}
    ida = {a["id"]: a for a in ancien.get("opc", [])}
    idn = {a["id"]: a for a in nouveau["opc"]}
    suivis = ("nom", "agrement", "date_agrement", "actif", "societe_gestion")
    changements = []
    for k, a in idn.items():
        v = ida.get(k)
        if not v:
            continue
        ecarts = [(c, v.get(c), a.get(c)) for c in suivis if v.get(c) != a.get(c)]
        if ecarts:
            changements.append({"nom": a["nom"], "famille": a["famille"],
                                "ecarts": ecarts})
    return {
        "entrants": [idn[k] for k in idn.keys() - ida.keys()],
        "sortants": [ida[k] for k in ida.keys() - idn.keys()],
        "changements": changements,
    }


# --------------------------------------------------------------------------
#  Chargement
# --------------------------------------------------------------------------

@dataclass
class Opc:
    donnees: dict = field(repr=False)

    def __getattr__(self, nom):
        try:
            return self.donnees[nom]
        except KeyError as exc:
            raise AttributeError(nom) from exc

    @property
    def fam(self) -> Famille:
        return FAMILLES[self.donnees["famille"]]

    @property
    def chemin(self) -> str:
        return f"{self.donnees['famille']}/{self.donnees['slug']}"

    @property
    def statut(self) -> tuple[str, str]:
        return ("En vigueur", "actif") if self.donnees["actif"] \
            else ("Clos ou non actif", "inactif")


def charger(chemin: Path) -> tuple[list[Opc], str]:
    if not chemin.exists():
        return [], ""
    jeu = json.loads(chemin.read_text(encoding="utf-8"))
    opc = [Opc(o) for o in jeu.get("opc", [])]
    inconnues = {o.famille for o in opc} - set(FAMILLES)
    if inconnues:
        raise SystemExit(f"Familles d'OPC inconnues : {sorted(inconnues)}")
    return opc, jeu.get("releve", "")


def par_famille(opc: list[Opc]) -> dict[str, list[Opc]]:
    groupes: dict[str, list[Opc]] = {c: [] for c in ORDRE}
    for o in opc:
        groupes[o.famille].append(o)
    return {c: g for c, g in groupes.items() if g}


def par_societe(opc: list[Opc]) -> dict[str, list[Opc]]:
    """Organismes rangés sous l'identifiant de leur société de gestion."""
    out: dict[str, list[Opc]] = {}
    for o in opc:
        if o.societe_gestion_id:
            out.setdefault(o.societe_gestion_id, []).append(o)
    return out


# --------------------------------------------------------------------------
#  Ligne de commande
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("collecter", help="interroge le registre des OPC")
    c.add_argument("--sortie", default="produits/opc.json")
    c.add_argument("--depuis-tsv", help="relevé déposé par le navigateur")
    c.add_argument("--releve")
    a = ap.parse_args()

    if a.depuis_tsv:
        bruts = depuis_tsv(Path(a.depuis_tsv))
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
    for f in jeu["opc"]:
        groupes[f["famille"]] = groupes.get(f["famille"], 0) + 1
    print(f"{jeu['nombre']} organismes écrits dans {sortie} "
          f"(relevé {jeu['releve']})")
    for cle in ORDRE:
        if cle in groupes:
            print(f"  {groupes[cle]:>4}  {FAMILLES[cle].pluriel}")
    if ancien:
        print(f"  entrants : {len(diff['entrants'])} · "
              f"sortants : {len(diff['sortants'])} · "
              f"modifiés : {len(diff['changements'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
