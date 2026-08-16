#!/usr/bin/env python3
"""
Illustrations vectorielles du site — traits fins et guillochés.

Tout est engendré ici en SVG inline afin que les couleurs suivent les
variables CSS (mode clair / sombre) et qu'aucune image externe ne soit
nécessaire. Les motifs guillochés — entrelacs harmoniques des billets de
banque et des documents officiels — font le lien visuel entre la matière
financière et la matière juridique du recueil.

Toutes les figures sont décoratives : aria-hidden, jamais porteuses de sens.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------------
#  Outils de tracé
# --------------------------------------------------------------------------

def _p(x: float, y: float) -> str:
    """Coordonnée compacte, une décimale."""
    return f"{x:.1f} {y:.1f}"


def _chemin_sinus(largeur: float, milieu: float, amplitude: float,
                  periode: float, phase: float, pas: float = 3.0) -> str:
    """Une sinusoïde en segments courts, prolongée d'un pas de chaque côté
    pour que la découpe d'un motif répété reste invisible."""
    pts = []
    x = -pas
    while x <= largeur + pas:
        y = milieu + amplitude * math.sin(2 * math.pi * x / periode + phase)
        pts.append(_p(x, y))
        x += pas
    return "M" + "L".join(pts)


def _rosette(cx: float, cy: float, rayon: float, creux: float,
             lobes: int, tours: int, pas_deg: float = 2.0) -> list[str]:
    """Rosette guillochée : la même courbe r(θ) = R − a + a·sin(nθ),
    répétée en la faisant tourner légèrement — le « tour de machine »
    des fonds de billets."""
    chemins = []
    for t in range(tours):
        rot = t * (2 * math.pi / lobes) / tours
        pts = []
        deg = 0.0
        while deg <= 360.0:
            th = math.radians(deg)
            r = rayon - creux + creux * math.sin(lobes * th)
            pts.append(_p(cx + r * math.cos(th + rot), cy + r * math.sin(th + rot)))
            deg += pas_deg
        chemins.append("M" + "L".join(pts) + "Z")
    return chemins


# --------------------------------------------------------------------------
#  Bande guillochée (séparateur horizontal)
# --------------------------------------------------------------------------

def bande_guillochee(ident: str, hauteur: int = 22) -> str:
    """Tresse de sinusoïdes en motif répété. `ident` doit être unique dans la
    page (les définitions SVG partagent l'espace d'identifiants du document)."""
    periode = 96.0
    mi = hauteur / 2
    a = hauteur * 0.32
    courbes = []
    for k, (amp, ph, cls) in enumerate([
        ( a,  0.0,            "gui-1"),
        (-a,  0.0,            "gui-1"),
        ( a,  math.pi / 2,    "gui-2"),
        (-a,  math.pi / 2,    "gui-2"),
        ( a * .55, math.pi/4, "gui-3"),
        (-a * .55, math.pi/4, "gui-3"),
    ]):
        d = _chemin_sinus(periode, mi, amp, periode, ph)
        courbes.append(f'<path class="{cls}" d="{d}"/>')
    return (
        f'<svg class="guilloche" aria-hidden="true" focusable="false" '
        f'preserveAspectRatio="none" height="{hauteur}" width="100%">'
        f'<defs><pattern id="{ident}" patternUnits="userSpaceOnUse" '
        f'width="{periode:.0f}" height="{hauteur}">{"".join(courbes)}</pattern></defs>'
        f'<rect width="100%" height="{hauteur}" fill="url(#{ident})"/></svg>'
    )


# --------------------------------------------------------------------------
#  Sceau rosette (pied de page, sceau de document)
# --------------------------------------------------------------------------

def sceau_rosette(taille: int = 92) -> str:
    """Petit sceau guilloché, comme la rosette sèche d'un acte officiel."""
    c = 50.0
    chemins = _rosette(c, c, 34, 7, 9, 5, pas_deg=3.0)
    interieur = _rosette(c, c, 19, 5, 6, 3, pas_deg=4.0)
    trames = "".join(f'<path d="{d}"/>' for d in chemins + interieur)
    return (
        f'<svg class="sceau" aria-hidden="true" focusable="false" '
        f'viewBox="0 0 100 100" width="{taille}" height="{taille}">'
        f'<circle cx="50" cy="50" r="46"/>'
        f'<circle cx="50" cy="50" r="42.5"/>'
        f'{trames}'
        f'<circle cx="50" cy="50" r="3.2"/>'
        f'</svg>'
    )


# --------------------------------------------------------------------------
#  Marque d'en-tête (petit emblème à côté du titre du site)
# --------------------------------------------------------------------------

EMBLEME = """<svg class="embleme" aria-hidden="true" focusable="false" viewBox="0 0 40 40" width="34" height="34">
  <rect x="1.5" y="1.5" width="37" height="37" rx="8" class="emb-fond"/>
  <path d="M12 8.5h11l5 5V31a1.6 1.6 0 0 1-1.6 1.6H12A1.6 1.6 0 0 1 10.4 31V10.1A1.6 1.6 0 0 1 12 8.5z" class="emb-page"/>
  <path d="M23 8.5l5 5h-5z" class="emb-coin"/>
  <path d="M14 18h12M14 22h12M14 26h8" class="emb-lignes"/>
  <path d="M13.5 13.4h6" class="emb-titre"/>
</svg>"""


# --------------------------------------------------------------------------
#  Illustration du bandeau d'accueil
#  Colonnes de l'institution, courbe de marché, acte scellé — en traits fins,
#  sur une grande rosette guillochée.
# --------------------------------------------------------------------------

def illustration_heros() -> str:
    rosette = "".join(
        f'<path d="{d}"/>' for d in _rosette(310, 152, 128, 26, 8, 6, pas_deg=2.5)
    )
    # Courbe de cours : ascension avec respirations, nœuds pointés.
    noeuds = [(18, 268), (92, 240), (158, 252), (224, 196), (289, 208), (368, 138), (438, 118)]
    courbe = "M" + "L".join(_p(x, y) for x, y in noeuds)
    points = "".join(f'<circle cx="{x}" cy="{y}" r="3.4" class="illu-noeud"/>'
                     for x, y in noeuds[1:-1])
    aire = courbe + f"L{_p(438, 300)}L{_p(18, 300)}Z"

    colonnes = "".join(
        f'<path d="M{x} 152v64" class="illu-fin"/>'
        f'<path d="M{x-7} 150h14M{x-7} 218h14" class="illu-fin"/>'
        for x in (76, 116, 156, 196)
    )

    return f"""<svg class="heros-illu" aria-hidden="true" focusable="false" viewBox="0 0 470 320" role="presentation">
  <g class="illu-rosette">{rosette}</g>
  <g class="illu-institution">
    <path d="M34 140 136 96 238 140" class="illu-fin"/>
    <path d="M46 141h180" class="illu-moy"/>
    {colonnes}
    <path d="M52 224h168M42 233h188M32 242h208" class="illu-fin"/>
  </g>
  <path d="{aire}" class="illu-aire"/>
  <path d="{courbe}" class="illu-courbe"/>
  {points}
  <g class="illu-acte" transform="rotate(-5 366 226)">
    <rect x="316" y="162" width="100" height="128" rx="4" class="illu-feuille"/>
    <path d="M330 184h72M330 200h72M330 216h72M330 232h46" class="illu-texte"/>
    <circle cx="392" cy="262" r="13" class="illu-cachet"/>
    <circle cx="392" cy="262" r="9" class="illu-cachet-fin"/>
    <path d="M386 272l-6 14 8-5 6 6 2-13" class="illu-cachet-fin"/>
  </g>
  <path d="M64 58h12M70 52v12M258 34h10M263 29v10M432 66h10M437 61v10" class="illu-etoile"/>
</svg>"""


# --------------------------------------------------------------------------
#  Icônes par rubrique — traits fins 24×24, couleur héritée (currentColor)
# --------------------------------------------------------------------------

def _icone(corps: str, taille: int = 24) -> str:
    return (f'<svg class="icone" aria-hidden="true" focusable="false" '
            f'viewBox="0 0 24 24" width="{taille}" height="{taille}" '
            f'fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round">{corps}</svg>')

_CORPS_ICONES = {
    # Balance : les textes fondateurs, la norme.
    "base": (
        '<path d="M12 4v16M8 20h8"/>'
        '<path d="M4.5 7h15"/>'
        '<path d="M6.5 7l-3 6a3.2 3.2 0 0 0 6 0z"/>'
        '<path d="M17.5 7l-3 6a3.2 3.2 0 0 0 6 0z"/>'
        '<circle cx="12" cy="5.5" r="1.4"/>'
    ),
    # Boussole : les instructions donnent le cap d'application.
    "instruction": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M15.5 8.5l-2.2 5-4.8 2 2.2-5z"/>'
        '<path d="M12 3.5v1.6M12 18.9v1.6M3.5 12h1.6M18.9 12h1.6"/>'
    ),
    # Pli postal : la circulaire circule.
    "circulaire": (
        '<rect x="3" y="6" width="18" height="13" rx="1.8"/>'
        '<path d="M3.6 7.2 12 13.4l8.4-6.2"/>'
    ),
    # Tampon : la décision fait acte.
    "decision": (
        '<path d="M9.5 10.5V7a2.5 2.5 0 0 1 5 0v3.5"/>'
        '<path d="M6.5 14.5c0-2.2 2.5-2.2 2.5-4h6c0 1.8 2.5 1.8 2.5 4z"/>'
        '<path d="M5.5 18h13v-3.5h-13z"/>'
        '<path d="M8 21h8"/>'
    ),
    # Feuillets assemblés : les autres actes.
    "autre": (
        '<path d="M12 3 3.5 8 12 13l8.5-5z"/>'
        '<path d="M4.5 12 12 16.5 19.5 12"/>'
        '<path d="M4.5 16 12 20.5 19.5 16"/>'
    ),
    # Document à barres : le rapport chiffré.
    "rapport": (
        '<rect x="5" y="3.5" width="14" height="17" rx="1.8"/>'
        '<path d="M9 16.5v-4M12 16.5v-7M15 16.5v-2.5"/>'
        '<path d="M9 7h4"/>'
    ),
    # Cadran : la chronologie.
    "chronologie": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 7.5V12l3.2 2.2"/>'
        '<path d="M12 3.5v1M12 19.5v1M3.5 12h1M19.5 12h1"/>'
    ),
    # Loupe : la recherche.
    "recherche": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M15.3 15.3 20.5 20.5"/>'
    ),
    # Livre ouvert : la méthode, l'à-propos.
    "apropos": (
        '<path d="M12 6.5C10.5 5 8 4.5 4 4.5v14c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2v-14c-4 0-6.5.5-8 2z"/>'
        '<path d="M12 6.5v14"/>'
    ),

    # --- Acteurs agréés -------------------------------------------------
    # Trois jetons reliés : la population des intervenants du marché.
    "acteurs": (
        '<circle cx="12" cy="6" r="2.6"/>'
        '<circle cx="5.5" cy="17" r="2.6"/>'
        '<circle cx="18.5" cy="17" r="2.6"/>'
        '<path d="M10.6 8.3 7 14.7M13.4 8.3 17 14.7M8.1 17h7.8"/>'
    ),
    # Façade à colonnes : la Bourse.
    "bourse": (
        '<path d="M3.5 9 12 4l8.5 5"/>'
        '<path d="M5.5 9v8M9.8 9v8M14.2 9v8M18.5 9v8"/>'
        '<path d="M3.5 20h17"/>'
    ),
    # Coffre à cadran : la conservation centrale des titres.
    "depositaire": (
        '<rect x="3.5" y="4.5" width="17" height="15"/>'
        '<circle cx="11" cy="12" r="3.4"/>'
        '<path d="M11 12h3.6M17.5 8.5v7"/>'
    ),
    # Double flèche : l'intermédiation, l'ordre porté au marché.
    "sgi": (
        '<path d="M3.5 9h14"/><path d="M14.5 5.8 17.8 9l-3.3 3.2"/>'
        '<path d="M20.5 15h-14"/><path d="M9.5 11.8 6.2 15l3.3 3.2"/>'
    ),
    # Registre et cadenas : la tenue de compte-conservation.
    "tcc": (
        '<path d="M5 4.5h9.5a2 2 0 0 1 2 2v13H7a2 2 0 0 1-2-2z"/>'
        '<path d="M5 16.5h11.5"/><path d="M8.2 8h6M8.2 11h6"/>'
        '<circle cx="19" cy="8.6" r="2.1"/><path d="M19 10.7v4.4l1.4 1"/>'
    ),
    # Parts rassemblées dans un contenant : la gestion collective.
    "sgo": (
        '<path d="M4 8.5h16l-1.6 11H5.6z"/>'
        '<path d="M4 8.5 8 4h8l4 4.5"/>'
        '<path d="M9.5 12.2v4M14.5 12.2v4"/>'
    ),
    # Action nominative : la SICAV, société dont on devient actionnaire.
    "sicav": (
        '<rect x="3.5" y="6" width="17" height="12"/>'
        '<circle cx="8.5" cy="12" r="2.4"/>'
        '<path d="M13.5 10h4M13.5 14h4"/>'
    ),
    # Mallette : le patrimoine confié en gestion.
    "sgp": (
        '<rect x="3.5" y="7.5" width="17" height="11"/>'
        '<path d="M9 7.5V6a1.6 1.6 0 0 1 1.6-1.6h2.8A1.6 1.6 0 0 1 15 6v1.5"/>'
        '<path d="M3.5 12.5h17"/><path d="M11 11.5h2v2h-2z"/>'
    ),
    # Entonnoir : des créances vers un titre négociable.
    "titrisation": (
        '<path d="M3.5 4.5h17l-6.5 7.5v7.5l-4-2.2V12z"/>'
        '<path d="M7.5 8h9"/>'
    ),
    # Marches et fanion : l'accompagnement vers la cote.
    "listing": (
        '<path d="M3.5 19.5h5v-5h5v-5h5"/>'
        '<path d="M16.5 4v6"/><path d="M16.5 4.4h4.2l-1.4 1.7 1.4 1.7h-4.2"/>'
    ),
    # Bulle et courbe : le conseil en investissement.
    "conseil": (
        '<path d="M4 5h16v10H9.5L5 18.5V15H4z"/>'
        '<path d="M7.5 11.5 10 9l2.4 2 4.1-4"/>'
    ),
    # Deux maillons : la mise en relation.
    "apporteur": (
        '<path d="M9.8 14.2 14.2 9.8"/>'
        '<path d="M12.6 7 14 5.6a3.6 3.6 0 0 1 5.1 5.1L17.7 12"/>'
        '<path d="M11.4 17 10 18.4a3.6 3.6 0 0 1-5.1-5.1L6.3 12"/>'
    ),
    # Cadran gradué : la notation.
    "notation": (
        '<path d="M3.5 17a8.5 8.5 0 0 1 17 0"/>'
        '<path d="M12 17 16 10.5"/><circle cx="12" cy="17" r="1.2"/>'
        '<path d="M4.6 12.4l1.5.9M12 8.5v1.7M19.4 12.4l-1.5.9"/>'
    ),
    # Écu : la garantie apportée aux souscripteurs.
    "garantie": (
        '<path d="M12 3.5 5 6v6c0 4 3 6.8 7 8.5 4-1.7 7-4.5 7-8.5V6z"/>'
        '<path d="M8.8 11.8 11 14l4.2-4.2"/>'
    ),
}


def icone(cle: str, taille: int = 24) -> str:
    """Icône d'une rubrique ; les clés inconnues retombent sur « autre »."""
    return _icone(_CORPS_ICONES.get(cle, _CORPS_ICONES["autre"]), taille)
