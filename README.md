# Textes du Marché Financier Régional de l'UMOA

Recueil consultable et indexable des textes réglementaires du Marché Financier
Régional de l'Union Monétaire Ouest Africaine : Convention créant l'AMF-UMOA,
Annexe, Règlement Général, instructions, circulaires, décisions et rapports.

**Site publié :** _(à compléter après le premier déploiement)_

153 documents · 2 654 pages · 5,37 millions de caractères de texte
recherchable · corpus couvrant 1996 à 2025

## Le problème que ce dépôt résout

Les textes qui organisent le marché financier régional de l'UMOA sont publics et
mis en ligne par l'AMF-UMOA. Une part importante d'entre eux est toutefois
diffusée sous forme d'images scannées dépourvues de couche textuelle. Sur les
132 textes réglementaires du recueil, 94 sont dans ce cas : leurs pages ne
contiennent aucune police de caractères ni aucun opérateur de texte, seulement
des images encodées en JPEG ou en CCITT. Les 38 autres — dont, heureusement, la
Convention, l'Annexe et le Règlement Général — disposent d'un texte exploitable.

Les conséquences sont concrètes. Aucun moteur de recherche ne peut indexer le
contenu de ces documents, donc une recherche du type « capital minimum SGI UMOA »
ne remonte rien d'utile. À l'intérieur d'un fichier, la recherche par mot-clé est
impossible. Aucune disposition ne peut être copiée pour être citée. Un praticien
qui cherche la règle applicable doit ouvrir les fichiers un par un, sans savoir
lequel contient la réponse.

Ce dépôt applique une reconnaissance optique de caractères à ces documents, en
restitue le texte dans des pages HTML sémantiques, et publie le tout sous forme
de site statique. Le texte devient alors lisible, cherchable, citable et
indexable, tandis que le PDF officiel reste accessible en un clic depuis chaque
document et demeure la seule référence faisant foi.

## Chaîne de traitement

Le traitement se fait en quatre étapes, de la récupération à la publication.

**Récupération.** Le script `telecharger-corpus-amf.sh` interroge l'API du site
officiel pour obtenir le manifeste des documents, puis télécharge les PDF
correspondants ainsi que les six textes de base servis comme fichiers statiques.
Il est reprenable : relancé, il ignore ce qui est déjà présent.

```bash
bash telecharger-corpus-amf.sh          # → ~/amf-umoa-corpus/{manifest.json,pdf/}
```

**Reconnaissance.** `pipeline/ocr_pipeline.py` traite chaque PDF page par page.
Lorsqu'une couche textuelle exploitable existe, le texte est extrait directement.
Sinon la page est rendue en niveaux de gris à 300 dpi, redressée par
maximisation de la variance du profil de projection, puis soumise à Tesseract
avec le modèle français `tessdata_best`. Les pages dont l'indice de confiance
reste faible sont automatiquement retentées à 400 dpi, et signalées si le
résultat demeure douteux.

```bash
python3 pipeline/ocr_pipeline.py ~/amf-umoa-corpus/pdf -o texte -j 4
```

**Relecture.** `pipeline/relire.py` sert à fiabiliser ce que l'OCR ne garantit
pas. La sous-commande `suspects` signale les passages statistiquement douteux —
nombres mal formés, confusions I/l/1 et O/0, ponctuation aberrante, montants
chiffrés — afin de concentrer l'effort là où il compte. `extraire` rend les pages
en image pour comparaison visuelle avec le texte reconnu. `appliquer` réinjecte
les corrections validées, de façon idempotente.

```bash
python3 pipeline/relire.py suspects texte/instruction_1000065.json
python3 pipeline/relire.py extraire ~/amf-umoa-corpus/pdf/instruction_1000065.pdf \
        --pages 2,3 --sortie controle
python3 pipeline/relire.py appliquer corrections/instructions.json --texte texte
```

**Génération.** `pipeline/build_site.py` assemble les sorties OCR et les
métadonnées, restructure le texte en titres, sections, articles et alinéas, puis
écrit le site statique complet : une page par document avec le texte intégral en
HTML, index par type, chronologie, recherche plein texte côté client, balisage
schema.org `Legislation`, sitemap et `robots.txt`.

```bash
python3 pipeline/build_site.py --texte texte --manifeste manifest.json \
        --sortie site --base-url https://mon-compte.github.io/mon-depot
python3 pipeline/verifier.py site
```

Tout s'enchaîne par `make`. Voir le `Makefile` pour les cibles disponibles.

## Choix d'architecture

**Le site est entièrement statique.** Aucune base de données, aucun serveur
d'application : uniquement des fichiers HTML, CSS et JSON. C'est ce qui rend la
publication gratuite, la mise en cache triviale et la pérennité maximale. Un
recueil de textes juridiques doit pouvoir survivre à l'inattention de celui qui
l'a créé.

**Le texte intégral figure dans le HTML de chaque page**, et non dans un fichier
chargé après coup par du JavaScript. C'est la condition pour que les moteurs de
recherche l'indexent, ce qui est la raison d'être du projet.

**Les PDF ne sont pas hébergés par défaut.** Le corpus complet pèse plusieurs
centaines de mégaoctets, ce qui alourdirait le dépôt sans bénéfice : chaque page
renvoie directement vers le PDF officiel de l'AMF-UMOA, qui est la référence
faisant foi. L'option `--inclure-pdf` permet néanmoins d'embarquer les fichiers
si l'on souhaite constituer une archive autonome.

**Le dépôt versionne le texte, pas les images.** Les sorties OCR (`texte/*.json`)
et le manifeste sont suivis par Git ; les PDF sources ne le sont pas. Le site est
reconstruit en intégration continue à chaque modification du texte ou des
corrections, ce qui garde le dépôt léger tout en rendant chaque correction
traçable.

**Les corrections sont séparées de l'OCR.** Elles vivent dans `corrections/` et
sont réappliquées à chaque construction. Régénérer l'OCR depuis zéro ne détruit
donc jamais le travail de relecture.

## Fiabilité

La reconnaissance optique n'est jamais parfaite, et sur un texte juridique une
erreur sur un montant ou un numéro d'article n'est pas une coquille mais un
contresens. Trois mesures encadrent donc la chaîne.

Sur un scan de test reproduisant les défauts du corpus — inclinaison, bruit de
capteur, contraste réduit — la chaîne atteint 99,96 % d'exactitude au caractère
et 99,57 % au mot, et restitue correctement l'intégralité des éléments
juridiquement sensibles testés : montants en chiffres, pourcentages, dates et
numéros d'article.

Sur le corpus réel, les 132 textes réglementaires totalisent 1 209 pages et
2 488 674 caractères, dont 38 documents disposaient déjà d'une couche textuelle
exploitable — c'est notamment le cas de la Convention, de l'Annexe et du
Règlement Général, les textes les plus consultés, qui ne subissent donc aucune
reconnaissance. Pour les autres, l'indice de confiance moyen s'établit à
92,5 %, aucun document ne descend sous 85 %, et six pages seulement restent
signalées comme nécessitant une vérification : quatre formulaires annexes à
cases et pointillés, et deux pages à en-tête tamponné.

Les 21 rapports annuels et études, soit 1 445 pages, sont d'une nature
différente : très chargés en tableaux et graphiques, ils plafonnent à 79 % de
confiance moyenne avec 48 pages signalées. Ils sont fournis pour le contexte de
marché qu'ils apportent, pas comme source normative.

Trois défauts ont été identifiés et corrigés au cours de la mise au point, et
méritent d'être signalés parce qu'ils illustrent ce que la seule confiance
déclarée ne montre pas. Une égalisation de contraste écrêtant 1 % de
l'histogramme effaçait le texte des pages peu encrées, une page de titre se
réduisant à un unique caractère. Un filtrage des mots de faible confiance,
destiné à écarter le charabia des logos, supprimait en réalité des mots réels —
Tesseract note bas les mots portant une apostrophe typographique, si bien que
« d'application », « d'OPC » et « l'UMOA » disparaissaient silencieusement : ce
filtrage a été retiré, car perdre un mot sans trace est bien pire qu'afficher un
logo mal lu. Enfin le recollage des césures supprimait le trait d'union des
composés légitimes, « négociateur-compensateur » devenant
« négociateurcompensateur » ; l'ambiguïté est désormais levée sur le corpus
lui-même, un trait d'union n'étant rétabli que si la forme composée y est
attestée ailleurs.

**Ce recueil n'a aucune valeur juridique.** Chaque page porte un avertissement
explicite, affiche l'indice de confiance du document, signale les pages à relire
en priorité et renvoie au PDF officiel, seule référence faisant foi.

## Ce qui manque au corpus

La rubrique « Autres actes » du site officiel est vide à ce jour. Plusieurs
textes cités dans la présentation du cadre légal n'y figurent donc pas : le
règlement relatif aux obligations sécurisées dans l'UEMOA, celui portant sur les
fonds communs de titrisation et les opérations de titrisation, celui relatif aux
titres islamiques et aux sociétés d'émission de SUKUK, ainsi que la décision
portant adoption de la loi uniforme relative aux infractions boursières. Ces
textes émanent du Conseil des Ministres de l'UEMOA et devront être recherchés
auprès des sources de l'Union pour compléter le recueil.

## Deux voies d'alimentation

**La veille automatique.** Le workflow `.github/workflows/veille.yml` s'exécute
le premier jour de chaque mois. Il interroge l'API de l'AMF-UMOA, compare la
liste obtenue au contenu de `texte/`, télécharge les documents absents, en fait
la reconnaissance, reconstruit le site et le republie — sans aucune
intervention. Chaque passage laisse son compte rendu dans `journal/`, qui
indique les textes trouvés, les échecs de téléchargement s'il y en a, et la
qualité de reconnaissance obtenue document par document.

Ce workflow reconstruit et publie lui-même le site au lieu de laisser
`deploy.yml` s'en charger. La raison est une protection de GitHub : un envoi
effectué par une action avec le jeton par défaut ne déclenche volontairement
aucun autre workflow, afin d'éviter les boucles infinies. Le déploiement doit
donc avoir lieu dans le même passage.

**Les apports manuels.** Une part du corpus n'est pas publiée par l'Autorité :
sa rubrique « Autres actes » est vide, alors que sa présentation du cadre légal
renvoie à des règlements du Conseil des Ministres de l'UEMOA — titrisation,
obligations sécurisées, titres islamiques — et à la loi uniforme relative aux
infractions boursières. Ces textes ne peuvent entrer dans le recueil que par
une voie parallèle.

Déposer un PDF dans `apports/` suffit : le même workflow le prend en charge au
prochain envoi. Le nom du fichier fait office de titre et permet d'en déduire
le type et la référence, de sorte qu'un fichier correctement nommé produit une
fiche correcte sans travail supplémentaire. `apports/README.md` détaille la
convention, et `apports/metadonnees.json` permet de compléter après coup une
date, un résumé ou l'adresse de la source. Ces documents forment la rubrique
« Autres actes » du recueil.

## Publication

Le workflow `.github/workflows/deploy.yml` construit et publie le site sur
GitHub Pages à chaque modification du texte, des corrections ou du pipeline. Il
faut au préalable activer Pages sur le dépôt, avec GitHub Actions comme source.
Si le site est servi depuis un domaine personnalisé, définir la variable de dépôt
`BASE_URL` en conséquence : elle conditionne les URLs canoniques et le sitemap.

## Mise à jour du corpus

L'AMF-UMOA publie régulièrement de nouvelles instructions et circulaires. Pour
les intégrer, relancer le script de téléchargement — il ne récupère que les
nouveautés —, passer l'OCR sur les seuls fichiers ajoutés, puis pousser. Le
pipeline ignore les documents dont la sortie JSON existe déjà, ce qui rend la
mise à jour incrémentale peu coûteuse.

## Sources et statut

L'intégralité des documents provient du site de l'Autorité des Marchés
Financiers de l'Union Monétaire Ouest Africaine, [amf-umoa.org](https://www.amf-umoa.org/).
Les textes de loi et actes réglementaires sont des documents publics ; ce
recueil en facilite l'accès sans en modifier la substance et renvoie
systématiquement à la source officielle.

Ce site est une initiative indépendante. Il n'émane pas de l'AMF-UMOA et ne
prétend à aucun caractère officiel.
