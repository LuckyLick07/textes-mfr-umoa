#!/usr/bin/env python3
"""
Registre des personnes exerçant sur le Marché Financier Régional.

Troisième pendant de `acteurs.py` et `produits.py` : qui exerce, dans quelle
société, à quel titre. Deux sources se croisent ici.

La première est le registre de l'AMF-UMOA, qui rattache à chaque acteur agréé
les détenteurs de cartes professionnelles — la carte est le titre qui autorise
une personne physique à exercer une fonction réglementée. Elle est atteinte par
la fiche détaillée d'un acteur :

    https://www.amf-umoa.org/service/api/elastic/acteur?size=1&page=0&id=<id>

La seconde est le répertoire constitué par le recueil à partir de sources
publiques — brvm.org, l'annuaire de l'APSGI, la presse spécialisée —, qui
couvre les dirigeants que le registre ne nomme pas et porte des intitulés de
fonction plus parlants.

Deux règles gouvernent ce module.

Rien de ce qui relève de l'état civil n'est repris : ni date ni lieu de
naissance, ni photographie, bien que le registre les publie. Le nom complet
associé à une date de naissance est la combinaison qui sert à usurper une
identité, et ces champs n'aident en rien à comprendre le marché.

Les pages produites ne sont pas indexables. Le registre de l'Autorité ne l'est
pas davantage : une fiche nominative que l'on trouve en cherchant un nom propre
n'a pas la même portée qu'une page de société.

Usage :
    personnes.py assembler --detenteurs brut/detenteurs.tsv \\
                           --repertoire brut/xl_contacts.tsv \\
                           --acteurs acteurs/acteurs.json \\
                           --sortie personnes/personnes.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from acteurs import VIDES, slugifier

# Le registre publie ces champs ; le recueil ne les reprend pas.
CHAMPS_ECARTES = ("dateNaissance", "lieuNaissance", "photo", "WhatsApp")

# L'état de carte du registre décrit l'avancement d'un dossier, non la validité
# d'un titre : « saisi » signifie que la demande est enregistrée, « imprimé »
# que la carte est fabriquée. Le présenter autrement serait le surinterpréter.
ETATS = {
    "SAISI": "Enregistrée",
    "IMPRIME": "Imprimée",
    "VALIDE_DA": "Validée",
    "VALIDE_CI": "Validée",
}

# Le registre écrit les pays en capitales ; la mise en forme automatique de la
# casse donnerait « Côte D'Ivoire ».
PAYS = {
    "BENIN": "Bénin", "BURKINAFASO": "Burkina Faso",
    "COTEDIVOIRE": "Côte d'Ivoire", "GUINEEBISSAU": "Guinée-Bissau",
    "MALI": "Mali", "NIGER": "Niger", "SENEGAL": "Sénégal", "TOGO": "Togo",
    "FRANCE": "France", "MAURICE": "Maurice",
}


def _pays(v: str) -> str:
    """La graphie du registre varie — accentuée ou non, avec ou sans
    apostrophe : la clé de correspondance les ignore."""
    t = _propre(v)
    return PAYS.get(_cle(t), t)

# Fonctions réglementaires regroupées en familles, pour que le répertoire se
# filtre autrement que par un intitulé exact.
FAMILLES_FONCTION = (
    ("direction", "Direction générale",
     ("directeur general", "directrice generale", "president directeur",
      "administrateur directeur", "directeur executif", "gerant",
      "president du conseil", "administrateur")),
    ("controle", "Contrôle et conformité",
     ("controle interne", "controleur", "conformite", "rcci", "risques",
      "audit", "deontologue")),
    ("marche", "Métiers de marché",
     ("negociateur", "compensateur", "marche des capitaux", "trader",
      "analyste", "ingenierie")),
    ("gestion", "Gestion d'actifs",
     ("gestionnaire de portefeuille", "gerant de fonds", "gestion d'actifs",
      "gestionnaire de fonds")),
    ("conservation", "Tenue de compte et conservation",
     ("teneur de compte", "conservateur", "back office", "operations")),
    ("clientele", "Relation clientèle",
     ("clientele", "commercial", "charge d'affaires")),
    ("autre", "Autres fonctions", ()),
)


def _sans_accent(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "")
                   if unicodedata.category(c) != "Mn")


def _cle(*bouts: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _sans_accent(" ".join(bouts)).upper())


def _propre(v) -> str:
    if v is None:
        return ""
    t = re.sub(r"\s+", " ", str(v)).strip().strip(";,")
    return "" if t.lower() in VIDES else t


def _nom_propre(t: str) -> str:
    """Les noms sont saisis en capitales ; les prénoms le sont irrégulièrement."""
    t = _propre(t)
    if not t:
        return ""
    lettres = [c for c in t if c.isalpha()]
    if not lettres or sum(c.isupper() for c in lettres) / len(lettres) <= 0.8:
        return t
    petits = {"de", "du", "des", "le", "la", "van", "von", "ben", "el"}
    mots = []
    for i, mot in enumerate(t.split(" ")):
        bouts = re.split(r"([-'’])", mot)
        rendu = []
        for b in bouts:
            if b in "-'’" or not b:
                rendu.append(b)
                continue
            bas = b.lower()
            rendu.append(bas if (i and bas in petits and not rendu)
                         else bas.capitalize())
        mots.append("".join(rendu))
    return " ".join(mots)


def famille_fonction(fonction: str) -> str:
    f = _sans_accent(fonction).lower()
    for cle, _, motifs in FAMILLES_FONCTION:
        if any(m in f for m in motifs):
            return cle
    return "autre"


def lire_tsv(chemin: Path) -> list[dict]:
    lignes = chemin.read_text(encoding="utf-8").rstrip("\n").split("\n")
    colonnes = lignes[0].split("§")
    return [dict(zip(colonnes, l.split("§"))) for l in lignes[1:]
            if l.count("§") == len(colonnes) - 1]


# --------------------------------------------------------------------------
#  Assemblage
# --------------------------------------------------------------------------

def assembler(detenteurs: list[dict], repertoire: list[dict],
              acteurs: list[dict]) -> list[dict]:
    """Croise les deux sources. La carte professionnelle prime pour le
    rattachement à un acteur agréé ; le répertoire complète l'intitulé de
    fonction et les coordonnées professionnelles."""
    # Une même société peut détenir plusieurs agréments — SGI et listing
    # sponsor, par exemple. Ses porteurs de cartes se rattachent à chacune de
    # ses fiches, la carte étant délivrée à l'établissement.
    par_cle_acteur: dict[str, list[dict]] = {}
    for a in acteurs:
        par_cle_acteur.setdefault(_cle(a["nom"]), []).append(a)
    fiches: dict[str, dict] = {}

    for d in detenteurs:
        nom, prenom = _propre(d.get("nom")), _propre(d.get("prenom"))
        if not nom and not prenom:
            continue
        societe = _propre(d.get("acteurLib"))
        k = _cle(societe, nom, prenom)
        chemins = [x["categorie"] + "/" + x["slug"]
                   for x in par_cle_acteur.get(_cle(societe), [])]
        fiches[k] = {
            "nom": _nom_propre(nom),
            "prenom": _nom_propre(prenom),
            "societe": societe,
            "societe_chemin": chemins[0] if chemins else "",
            "societe_chemins": chemins,
            "categorie_societe": d.get("acteurType", ""),
            "pays": _pays(d.get("acteurPays")),
            "fonction": _propre(d.get("fonctionReglementaire")) or _propre(d.get("fonction")),
            "carte": ETATS.get(_propre(d.get("etatCarte")), ""),
            "actif": d.get("actif") == "true",
            "reference": _propre(d.get("ref")),
            "sources": ["registre"],
            "telephone": "",
            "courriel": "",
        }

    for c in repertoire:
        nom, prenom = _propre(c.get("Nom")), _propre(c.get("Prénoms"))
        if not nom and not prenom:
            continue
        societe = _propre(c.get("Institution"))
        k = _cle(societe, nom, prenom)
        chemins = [x["categorie"] + "/" + x["slug"]
                   for x in par_cle_acteur.get(_cle(societe), [])]
        # Le téléphone et le courriel du répertoire sont ceux publiés par la
        # société ; la colonne WhatsApp, qui porte des mobiles personnels,
        # n'est pas reprise.
        tel, mail = _propre(c.get("Téléphone")), _propre(c.get("E-mail"))
        if k in fiches:
            f = fiches[k]
            f["sources"].append("repertoire")
            fonction = _propre(c.get("Fonction"))
            if fonction and len(fonction) > len(f["fonction"]):
                f["fonction"] = fonction
            f["telephone"] = f["telephone"] or tel
            f["courriel"] = f["courriel"] or mail
            continue
        fiches[k] = {
            "nom": _nom_propre(nom),
            "prenom": _nom_propre(prenom),
            "societe": societe,
            "societe_chemin": chemins[0] if chemins else "",
            "societe_chemins": chemins,
            "categorie_societe": _propre(c.get("Type")),
            "pays": _pays(c.get("Pays")),
            "fonction": _propre(c.get("Fonction")),
            "carte": "",
            "actif": True,
            "reference": "",
            "sources": ["repertoire"],
            "telephone": tel,
            "courriel": mail,
        }

    sortie = []
    vus: dict[str, int] = {}
    for k, f in fiches.items():
        f["famille"] = famille_fonction(f["fonction"])
        base = slugifier(f"{f['prenom']} {f['nom']}") or slugifier(k)
        n = vus.get(base, 0) + 1
        vus[base] = n
        f["slug"] = base if n == 1 else f"{base}-{n}"
        sortie.append(f)
    sortie.sort(key=lambda f: (0 if f["actif"] else 1,
                               _sans_accent(f["nom"]).upper(),
                               _sans_accent(f["prenom"]).upper()))
    return sortie


def construire_jeu(personnes: list[dict], releve: str | None = None) -> dict:
    return {
        "sources": {
            "registre": "https://www.amf-umoa.org/accueil/intervenant",
            "repertoire": "Répertoire du recueil, constitué à partir de "
                          "brvm.org, de l'annuaire de l'APSGI et de la presse "
                          "spécialisée.",
        },
        "champs_ecartes": list(CHAMPS_ECARTES),
        "releve": releve or date.today().isoformat(),
        "nombre": len(personnes),
        "personnes": personnes,
    }


# --------------------------------------------------------------------------
#  Chargement
# --------------------------------------------------------------------------

@dataclass
class Personne:
    donnees: dict = field(repr=False)

    def __getattr__(self, nom):
        try:
            return self.donnees[nom]
        except KeyError as exc:
            raise AttributeError(nom) from exc

    @property
    def nom_complet(self) -> str:
        return " ".join(x for x in (self.donnees["prenom"], self.donnees["nom"]) if x)

    @property
    def libelle_famille(self) -> str:
        for cle, libelle, _ in FAMILLES_FONCTION:
            if cle == self.donnees["famille"]:
                return libelle
        return "Autres fonctions"


def charger(chemin: Path) -> tuple[list[Personne], str]:
    if not chemin.exists():
        return [], ""
    jeu = json.loads(chemin.read_text(encoding="utf-8"))
    return [Personne(p) for p in jeu.get("personnes", [])], jeu.get("releve", "")


def par_societe(personnes: list[Personne]) -> dict[str, list[Personne]]:
    out: dict[str, list[Personne]] = {}
    for p in personnes:
        for chemin in (p.donnees.get("societe_chemins")
                       or ([p.societe_chemin] if p.societe_chemin else [])):
            out.setdefault(chemin, []).append(p)
    for g in out.values():
        g.sort(key=lambda p: (0 if p.famille == "direction" else 1,
                              0 if p.actif else 1, p.nom))
    return out


# --------------------------------------------------------------------------
#  Ligne de commande
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("assembler", help="croise les deux sources")
    c.add_argument("--detenteurs", default="brut/detenteurs.tsv")
    c.add_argument("--repertoire", default="brut/xl_contacts.tsv")
    c.add_argument("--acteurs", default="acteurs/acteurs.json")
    c.add_argument("--sortie", default="personnes/personnes.json")
    c.add_argument("--releve")
    a = ap.parse_args()

    detenteurs = lire_tsv(Path(a.detenteurs)) if Path(a.detenteurs).exists() else []
    repertoire = lire_tsv(Path(a.repertoire)) if Path(a.repertoire).exists() else []
    acteurs = json.loads(Path(a.acteurs).read_text(encoding="utf-8"))["acteurs"]

    personnes = assembler(detenteurs, repertoire, acteurs)
    jeu = construire_jeu(personnes, a.releve)
    sortie = Path(a.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(jeu, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")

    familles: dict[str, int] = {}
    for p in personnes:
        familles[p["famille"]] = familles.get(p["famille"], 0) + 1
    rattachees = sum(1 for p in personnes if p["societe_chemin"])
    print(f"{len(personnes)} personnes écrites dans {sortie} "
          f"(relevé {jeu['releve']})")
    print(f"  {rattachees} rattachées à un acteur agréé du recueil")
    print(f"  {sum(1 for p in personnes if p['actif'])} en fonction au registre")
    for cle, libelle, _ in FAMILLES_FONCTION:
        if familles.get(cle):
            print(f"  {familles[cle]:>5}  {libelle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
