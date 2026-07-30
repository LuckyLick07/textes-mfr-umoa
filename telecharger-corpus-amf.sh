#!/bin/bash
# =============================================================================
#  Récupération du corpus documentaire de l'AMF-UMOA
#  (Autorité des Marchés Financiers de l'Union Monétaire Ouest Africaine)
#
#  Ce script télécharge les textes réglementaires et les rapports publiés
#  sur www.amf-umoa.org, ainsi que le manifeste de métadonnées associé.
#
#  Usage :  bash telecharger-corpus-amf.sh
#  Reprise : relancer la même commande, les fichiers déjà présents sont ignorés.
# =============================================================================

set -uo pipefail

BASE="https://www.amf-umoa.org"
DEST="${HOME}/amf-umoa-corpus"
PDFDIR="${DEST}/pdf"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
PAUSE=0.3          # politesse envers le serveur, en secondes
CATEGORIES='Instruction|Circulaire|Decision|Rapport'

mkdir -p "${PDFDIR}"

echo ""
echo "  Corpus AMF-UMOA"
echo "  Destination : ${DEST}"
echo "  ---------------------------------------------------------------"
echo ""

# --- 1. Manifeste de métadonnées -------------------------------------------

echo "  [1/3] Téléchargement du manifeste de métadonnées..."
if ! curl -sS -A "${UA}" --compressed --retry 3 --retry-delay 2 --max-time 120 \
        "${BASE}/service/api/elastic/actualite?size=3000&page=0&langue=fr" \
        -o "${DEST}/manifest.json"; then
    echo "  ERREUR : le manifeste n'a pas pu être récupéré. Vérifie ta connexion."
    exit 1
fi

if [ ! -s "${DEST}/manifest.json" ]; then
    echo "  ERREUR : le manifeste reçu est vide."
    exit 1
fi
echo "        manifeste enregistré ($(wc -c < "${DEST}/manifest.json" | tr -d ' ') octets)"

# --- 2. Extraction des identifiants ----------------------------------------
# On isole chaque objet JSON, on garde ceux qui portent un document et qui
# relèvent des catégories visées, puis on lit l'identifiant et la catégorie.

echo "  [2/3] Analyse du manifeste..."

PARSED=0
if command -v python3 >/dev/null 2>&1 && python3 -c 'import json' >/dev/null 2>&1; then
    if python3 - "${DEST}/manifest.json" "${DEST}/.liste" <<'PYEOF' 2>/dev/null
import json, sys
cibles = {"Instruction", "Circulaire", "Decision", "Rapport"}
with open(sys.argv[1], encoding="utf-8") as f:
    items = json.load(f)
lignes = sorted(
    f'{it["id"]} {it["categorie"]}'
    for it in items
    if it.get("categorie") in cibles and it.get("documentUrl")
)
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write("\n".join(lignes) + "\n")
PYEOF
    then
        PARSED=1
        echo "        analyse JSON via python3"
    fi
fi

if [ "${PARSED}" -eq 0 ]; then
    echo "        analyse JSON via sed (python3 indisponible)"
    tr '{' '\n' < "${DEST}/manifest.json" \
      | grep -E "\"categorie\":\"(${CATEGORIES})\"" \
      | grep -v '"documentUrl":null' \
      | sed -E 's/.*"id":([0-9]+).*"categorie":"([A-Za-z]+)".*/\1 \2/' \
      | grep -E '^[0-9]+ [A-Za-z]+$' \
      | sort -u > "${DEST}/.liste"
fi

TOTAL=$(wc -l < "${DEST}/.liste" | tr -d ' ')

if [ "${TOTAL}" -lt 100 ]; then
    echo "  AVERTISSEMENT : seulement ${TOTAL} documents identifiés (environ 149 attendus)."
    echo "  Le format du site a peut-être changé. Le script continue quand même."
    echo ""
fi
echo "        ${TOTAL} documents identifiés"

# --- 3. Téléchargement ------------------------------------------------------

echo "  [3/3] Téléchargement des documents (plusieurs centaines de Mo)..."
echo ""

OK=0; SKIP=0; FAIL=0; N=0
FAILED_IDS=""

while read -r ID CAT; do
    N=$((N + 1))
    OUT="${PDFDIR}/$(echo "${CAT}" | tr '[:upper:]' '[:lower:]')_${ID}.pdf"

    if [ -s "${OUT}" ] && head -c 4 "${OUT}" | grep -q '%PDF'; then
        SKIP=$((SKIP + 1))
        continue
    fi

    printf "  %3d/%s  %-12s %s ... " "${N}" "${TOTAL}" "${CAT}" "${ID}"

    if curl -sS -A "${UA}" --compressed --retry 3 --retry-delay 2 --max-time 300 \
            "${BASE}/service/api/elastic/download/actualite/${ID}/doc" -o "${OUT}" \
       && [ -s "${OUT}" ] && head -c 4 "${OUT}" | grep -q '%PDF'; then
        SZ=$(( $(wc -c < "${OUT}") / 1024 ))
        printf "ok (%s ko)\n" "${SZ}"
        OK=$((OK + 1))
    else
        printf "ECHEC\n"
        rm -f "${OUT}"
        FAIL=$((FAIL + 1))
        FAILED_IDS="${FAILED_IDS} ${ID}"
    fi

    sleep "${PAUSE}"
done < "${DEST}/.liste"

# --- 4. Textes de base (fichiers statiques) --------------------------------

echo ""
echo "  Textes de base (Convention, Annexe, Règlement Général)..."

download_static () {
    local url="$1" out="${PDFDIR}/$2"
    if [ -s "${out}" ] && head -c 4 "${out}" | grep -q '%PDF'; then
        SKIP=$((SKIP + 1)); return
    fi
    printf "  %-46s ... " "$2"
    if curl -sS -A "${UA}" --compressed --retry 3 --retry-delay 2 --max-time 300 \
            "${url}" -o "${out}" \
       && [ -s "${out}" ] && head -c 4 "${out}" | grep -q '%PDF'; then
        printf "ok (%s ko)\n" "$(( $(wc -c < "${out}") / 1024 ))"
        OK=$((OK + 1))
    else
        printf "ECHEC\n"; rm -f "${out}"; FAIL=$((FAIL + 1))
    fi
    sleep "${PAUSE}"
}

download_static "${BASE}/assets/docs/convention/CONVENTION.pdf"                      "base_01_convention.pdf"
download_static "${BASE}/assets/docs/convention/ANNEXE.pdf"                          "base_02_annexe.pdf"
download_static "${BASE}/assets/docs/convention/AVENANT.pdf"                         "base_03_avenant.pdf"
download_static "${BASE}/assets/docs/general/Reglement_General.pdf"                  "base_04_reglement_general.pdf"
download_static "${BASE}/assets/docs/general/Decision_CM_000.pdf"                    "base_05_decision_modif_art37.pdf"
download_static "${BASE}/assets/docs/general/Decision_CM_05092005_du_16-09-2005.pdf" "base_06_decision_modif_art136.pdf"

# --- Bilan ------------------------------------------------------------------

rm -f "${DEST}/.liste"
COUNT=$(ls -1 "${PDFDIR}"/*.pdf 2>/dev/null | wc -l | tr -d ' ')
POIDS=$(du -sh "${DEST}" 2>/dev/null | cut -f1)

echo ""
echo "  ---------------------------------------------------------------"
echo "  Terminé."
echo "    téléchargés      : ${OK}"
echo "    déjà présents    : ${SKIP}"
echo "    échecs           : ${FAIL}"
echo "    total dans pdf/  : ${COUNT} fichiers  (${POIDS})"
echo ""
if [ "${FAIL}" -gt 0 ]; then
    echo "  Identifiants en échec :${FAILED_IDS}"
    echo "  Relance simplement le script, il reprendra là où il s'est arrêté."
    echo ""
fi
echo "  Dossier : ${DEST}"
echo "  ---------------------------------------------------------------"
echo ""
