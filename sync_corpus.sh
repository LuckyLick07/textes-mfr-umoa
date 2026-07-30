#!/bin/bash
# Recopie les PDF transités vers le corpus de travail en appliquant les noms
# canoniques attendus par le pipeline, et écarte les fichiers non conformes.
# Idempotent : relançable sans effet de bord.

SRC=/mnt/user-data/uploads/amf-umoa-corpus/pdf
DST=/home/claude/corpus/pdf
mkdir -p "$DST"

for f in "$SRC"/*.pdf; do
  [ -e "$f" ] || continue
  n=$(basename "$f")
  case "$n" in
    base_CONVENTION.pdf)                         n=base_01_convention.pdf ;;
    base_ANNEXE.pdf)                             n=base_02_annexe.pdf ;;
    base_AVENANT.pdf)                            n=base_03_avenant.pdf ;;
    base_Reglement_General.pdf)                  n=base_04_reglement_general.pdf ;;
    base_Decision_CM_000.pdf)                    n=base_05_decision_modif_art37.pdf ;;
    base_Decision_CM_05092005_du_16-09-2005.pdf) n=base_06_decision_modif_art136.pdf ;;
  esac
  [ -s "$DST/$n" ] || cp "$f" "$DST/$n"
done

# Supprime les noms non canoniques éventuellement présents
rm -f "$DST"/base_CONVENTION.pdf "$DST"/base_ANNEXE.pdf "$DST"/base_AVENANT.pdf \
      "$DST"/base_Reglement_General.pdf "$DST"/base_Decision_CM_000.pdf \
      "$DST"/base_Decision_CM_05092005_du_16-09-2005.pdf

# Écarte tout PDF vide ou tronqué : un fichier invalide ferait échouer l'OCR
for f in "$DST"/*.pdf; do
  [ -e "$f" ] || continue
  if [ ! -s "$f" ] || ! head -c 4 "$f" | grep -q '%PDF'; then
    echo "  écarté (vide ou invalide) : $(basename "$f")"
    rm -f "$f"
  fi
done

echo "corpus : $(ls -1 "$DST"/*.pdf 2>/dev/null | wc -l | tr -d ' ') PDF"
