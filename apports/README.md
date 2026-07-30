# Apports : documents obtenus hors canal officiel

Déposer ici un PDF suffit à le faire entrer dans le recueil. Le traitement est
automatique : reconnaissance du texte, création de la page, publication.

## Comment nommer le fichier

Le nom du fichier devient le titre affiché, et sert à en déduire le type et la
référence. Un nom bien formé donne donc une fiche correcte sans autre travail :

```
Reglement n°10-2022-CM-UEMOA relatif a la finance islamique.pdf
Decision n°CM-07-09-2021 portant loi uniforme sur les infractions boursieres.pdf
```

Le premier mot fixe le type — règlement, décision, instruction, circulaire,
directive, loi, avis — et à défaut le document rejoint la rubrique
« Autres actes ». La référence qui suit « n° » et l'année qu'elle contient sont
reconnues automatiquement.

## Pour préciser ou corriger

À la première prise en compte, une entrée est créée dans `metadonnees.json`
avec ce qui a pu être déduit du nom. Ce fichier reste modifiable : on peut y
compléter la date exacte, un résumé, l'adresse de la source, ou rectifier le
type. Les modifications sont reprises à la construction suivante.

## Portée

Cette voie sert aux textes que l'AMF-UMOA mentionne sans les publier, en
particulier les actes du Conseil des Ministres de l'UEMOA : sa rubrique
« Autres actes » est vide. Chaque page produite porte le même avertissement que
les autres et n'a aucune valeur juridique.
