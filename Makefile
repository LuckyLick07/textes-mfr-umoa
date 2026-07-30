# Chaîne de traitement du recueil AMF-UMOA
#
#   make corpus     télécharge les PDF depuis le site officiel
#   make ocr        reconnaissance optique des PDF non encore traités
#   make site       génère le site statique
#   make verifier   contrôles automatiques sur le site généré
#   make servir     sert le site en local sur http://localhost:8000
#   make tout       ocr + site + verifier
#   make suspects   signale les passages douteux à relire
#   make propre     supprime le site généré

PDF      ?= $(HOME)/amf-umoa-corpus/pdf
MANIFEST ?= $(HOME)/amf-umoa-corpus/manifest.json
TEXTE    ?= texte
SITE     ?= site
JOBS     ?= 4
BASE_URL ?= http://localhost:8000

PY := python3

.PHONY: tout corpus ocr site verifier servir suspects corrections propre aide

aide:
	@sed -n '2,14p' $(MAKEFILE_LIST) | sed 's/^# \{0,1\}//'

corpus:
	bash telecharger-corpus-amf.sh
	@cp -f $(MANIFEST) ./manifest.json 2>/dev/null || true
	@echo "manifeste copié à la racine du dépôt"

ocr:
	@test -d "$(PDF)" || { echo "PDF introuvables dans $(PDF) — lancer 'make corpus'"; exit 1; }
	$(PY) pipeline/ocr_pipeline.py "$(PDF)" -o $(TEXTE) -j $(JOBS)

corrections:
	@shopt -s nullglob 2>/dev/null || true; \
	for f in corrections/*.json; do \
	  [ -e "$$f" ] || continue; \
	  echo "→ $$f"; \
	  $(PY) pipeline/relire.py appliquer "$$f" --texte $(TEXTE); \
	done

site: corrections
	$(PY) pipeline/build_site.py --texte $(TEXTE) --manifeste manifest.json \
	      --sortie $(SITE) --base-url "$(BASE_URL)"

verifier:
	$(PY) pipeline/verifier.py $(SITE)

suspects:
	$(PY) pipeline/relire.py suspects $(TEXTE)

tout: ocr site verifier

servir: site
	@echo "→ http://localhost:8000"
	@cd $(SITE) && $(PY) -m http.server 8000

propre:
	rm -rf $(SITE)
