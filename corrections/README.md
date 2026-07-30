# Corrections de relecture

Chaque fichier `.json` de ce dossier décrit des corrections validées à
réappliquer après la reconnaissance optique. Elles sont rejouées à chaque
construction du site, de sorte que régénérer l'OCR depuis zéro ne détruit
jamais le travail de relecture.

Format :

```json
{
  "instruction_1000065": [
    {"page": 2, "avant": "1 600 000 000", "apres": "1 500 000 000"},
    {"page": 3, "remplacer_page": "texte intégral corrigé de la page"}
  ]
}
```

L'application est idempotente : une correction déjà en place est ignorée.
Vérifier toute correction contre le PDF original avant de l'inscrire ici.
