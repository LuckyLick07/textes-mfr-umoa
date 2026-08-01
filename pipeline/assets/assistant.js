/* ==========================================================================
   Assistant documentaire conversationnel.

   Une fenêtre de dialogue où le visiteur pose sa question en français et
   reçoit pour réponse les dispositions pertinentes du recueil, citées
   textuellement et reliées au document. Tout se passe dans le navigateur :
   l'index inversé de la recherche est réutilisé pour présélectionner les
   documents, leur texte brut est récupéré à la demande, découpé par article,
   et les meilleurs passages sont cités tels quels. Aucun serveur, aucun
   modèle génératif : l'assistant ne peut pas inventer, il ne sait que citer.

   Le fichier est autonome — styles compris — et se charge depuis le gabarit
   commun. Il ne dépend que de data/index-recherche.json et des data/<slug>.txt
   produits par build_site.py.
   ========================================================================== */

(function () {
  'use strict';

  /* --- Racine du site ---------------------------------------------------- */
  // Déduite de l'adresse du script lui-même : fonctionne à toute profondeur
  // d'URL, en local comme sur GitHub Pages.
  var script = document.currentScript;
  var RACINE = script && script.src
    ? script.src.replace(/assets\/assistant\.js.*$/, '')
    : './';

  var TYPES = {
    base: 'Texte de base', instruction: 'Instruction', circulaire: 'Circulaire',
    decision: 'Décision', autre: 'Autre acte', rapport: 'Rapport'
  };

  // Paramètres BM25, identiques à ceux de la page de recherche.
  var K1 = 1.2, B = 0.6;
  var POIDS_TYPE = {
    base: 1.35, instruction: 1.2, circulaire: 1.2, decision: 1.2,
    autre: 1.2, rapport: 0.75
  };

  // Mots vides de l'indexeur : ils ne figurent pas dans l'index et ne
  // comptent pas dans la couverture d'une question.
  var MOTS_VIDES = {};
  ('au aux avec ce ces dans de des du elle en et eux il ils je la le les leur' +
   ' lui ma mais me meme mes moi mon ne nos notre nous on ou par pas pour qu' +
   ' que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d' +
   ' j l a m n s t y ete etee etees etes etant suis es est sommes sont serai' +
   ' seras sera serons serez seront serais serait serions seriez seraient' +
   ' etais etait etions etiez etaient fus fut fumes futes furent sois soit' +
   ' soyons soyez soient fusse fusses eussions eussiez eussent ayant eu eue' +
   ' eues ai as avons avez ont aurai auras aura aurons aurez auront aurais' +
   ' aurait aurions auriez auraient avais avait avions aviez avaient eus eut' +
   ' eumes eutes eurent aie aies ait ayons ayez aient eusse eusses plus tres' +
   ' etre avoir cette cet celui celle ceux dont donc alors ainsi comme' +
   ' lorsque apres avant entre sous vers chez sans selon dit dite dits dites'
  ).split(' ').forEach(function (m) { if (m) MOTS_VIDES[m] = 1; });

  // Tournures de question sans valeur discriminante. Elles ne sont écartées
  // que s'il reste au moins un terme porteur de sens.
  var MOTS_QUESTION = {};
  ('quel quels quelle quelles lequel laquelle lesquels lesquelles quoi quand' +
   ' comment pourquoi combien peut peuvent doit doivent faut puis peux dois' +
   ' dire disent dis prevoit prevoient prevu prevue prevus prevues dispose' +
   ' disposent stipule stipulent enonce enoncent regit regissent definit' +
   ' definissent signifie concernant concerne concernent existe' +
   ' texte textes document documents recueil corpus site liste' +
   ' svp stp merci bonjour bonsoir salut'
  ).split(' ').forEach(function (m) { if (m) MOTS_QUESTION[m] = 1; });

  /* --- Normalisation, identique à celle de l'indexeur -------------------- */

  var APOSTROPHES = /[‘’ʼ]/g;
  var DIACRITIQUES = /[̀-ͯ]/g;

  function normaliser(t) {
    return t.replace(APOSTROPHES, "'")
      .normalize('NFD').replace(DIACRITIQUES, '')
      .toLowerCase();
  }

  function decouper(t) {
    return normaliser(t).split(/[^a-z0-9]+/).filter(function (j) {
      return j.length >= 2;
    });
  }

  function echapper(t) {
    return String(t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
               '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* --- État -------------------------------------------------------------- */

  var index = null;          // index-recherche.json, chargé à la première ouverture
  var chargement = null;     // promesse de chargement en cours
  var cacheDoc = {};         // slug -> { texte, segments }
  var contexte = { mots: [], docs: [] };   // fil de la conversation
  var CLE_MEMOIRE = 'mfr-assistant-fil';

  /* ======================================================================
     Interface
     ====================================================================== */

  var STYLES = '\
.asst-bouton{position:fixed;right:18px;bottom:18px;z-index:60;display:inline-flex;\
align-items:center;gap:.5rem;padding:.62rem 1rem;border:1px solid var(--trait-fort);\
border-radius:999px;background:var(--accent);color:#fff;font:600 .92rem/1 var(--sans);\
cursor:pointer;box-shadow:var(--ombre)}\
.asst-bouton:hover{background:var(--accent-vif)}\
.asst-bouton svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.8}\
.asst-panneau[hidden]{display:none}\
.asst-panneau{position:fixed;right:16px;bottom:16px;z-index:61;display:flex;\
flex-direction:column;width:min(410px,calc(100vw - 24px));\
height:min(600px,calc(100vh - 90px));background:var(--papier);\
border:1px solid var(--trait-fort);border-radius:12px;box-shadow:0 6px 32px rgba(22,32,44,.18);\
overflow:hidden;font-family:var(--sans)}\
.asst-tete{display:flex;align-items:center;gap:.6rem;padding:.7rem .9rem;\
border-bottom:1px solid var(--trait);background:var(--papier-creme)}\
.asst-tete h2{margin:0;font-size:.98rem;color:var(--encre)}\
.asst-tete p{margin:0;font-size:.74rem;color:var(--encre-tenue)}\
.asst-fermer{margin-left:auto;border:0;background:none;color:var(--encre-douce);\
font-size:1.5rem;line-height:1;cursor:pointer;padding:.2rem .45rem;border-radius:6px}\
.asst-fermer:hover{background:var(--papier-gris);color:var(--encre)}\
.asst-fil{flex:1;overflow-y:auto;padding:.9rem;display:flex;flex-direction:column;\
gap:.65rem;background:var(--papier)}\
.asst-msg{max-width:92%;padding:.55rem .8rem;border-radius:10px;font-size:.9rem;\
line-height:1.5;color:var(--encre);overflow-wrap:break-word}\
.asst-msg.u{align-self:flex-end;background:var(--accent-clair);\
border:1px solid var(--trait)}\
.asst-msg.a{align-self:flex-start;background:var(--papier-creme);\
border:1px solid var(--trait);max-width:97%}\
.asst-msg p{margin:.35rem 0}\
.asst-msg p:first-child{margin-top:0}\
.asst-msg p:last-child{margin-bottom:0}\
.asst-msg mark{background:var(--ambre-fond);color:inherit;padding:0 .08em}\
.asst-carte{margin:.55rem 0;border:1px solid var(--trait);border-radius:8px;\
background:var(--papier);overflow:hidden}\
.asst-carte-tete{padding:.45rem .65rem;border-bottom:1px solid var(--trait);\
background:var(--papier-gris);font-size:.8rem}\
.asst-carte-tete a{font-weight:600;color:var(--accent);text-decoration:none}\
.asst-carte-tete a:hover{text-decoration:underline}\
.asst-carte-tete .asst-annee{color:var(--encre-tenue)}\
.asst-badge{display:inline-block;margin-left:.35rem;padding:.05rem .45rem;\
border-radius:999px;font-size:.68rem;font-weight:600;background:var(--rouge-fond);\
color:var(--rouge-encre)}\
.asst-article{padding:.4rem .65rem 0;font-size:.8rem;font-weight:600;\
color:var(--encre-douce)}\
.asst-carte blockquote{margin:.35rem .65rem .55rem;padding:0 0 0 .6rem;\
border-left:3px solid var(--accent);font-family:var(--serif);font-size:.88rem;\
color:var(--encre);line-height:1.55}\
.asst-carte-pied{padding:0 .65rem .5rem;font-size:.78rem}\
.asst-note{font-size:.74rem;color:var(--encre-tenue);margin-top:.5rem}\
.asst-suggestions[hidden]{display:none}\
.asst-suggestions{display:flex;flex-wrap:wrap;gap:.4rem;padding:0 .9rem .5rem}\
.asst-suggestions button{border:1px solid var(--trait-fort);border-radius:999px;\
background:var(--papier);color:var(--accent);font-size:.78rem;padding:.3rem .7rem;\
cursor:pointer;text-align:left}\
.asst-suggestions button:hover{background:var(--accent-clair)}\
.asst-saisie{display:flex;gap:.5rem;padding:.65rem .9rem;\
border-top:1px solid var(--trait);background:var(--papier-creme)}\
.asst-saisie input{flex:1;min-width:0;padding:.55rem .75rem;font-size:16px;\
border:1px solid var(--trait-fort);border-radius:8px;background:var(--papier);\
color:var(--encre)}\
.asst-saisie input:focus{outline:2px solid var(--accent-vif);outline-offset:1px}\
.asst-saisie button{border:0;border-radius:8px;background:var(--accent);color:#fff;\
font-weight:600;font-size:.88rem;padding:.55rem .9rem;cursor:pointer}\
.asst-saisie button:hover{background:var(--accent-vif)}\
.asst-confidentialite{margin:0;padding:.35rem .9rem .55rem;font-size:.68rem;\
color:var(--encre-tenue);background:var(--papier-creme)}\
.asst-attente span{display:inline-block;width:6px;height:6px;margin-right:4px;\
border-radius:50%;background:var(--encre-tenue);animation:asst-pulse 1s infinite}\
.asst-attente span:nth-child(2){animation-delay:.18s}\
.asst-attente span:nth-child(3){animation-delay:.36s}\
@keyframes asst-pulse{0%,80%,100%{opacity:.25}40%{opacity:1}}\
@media (max-width:540px){.asst-panneau{right:0;bottom:0;width:100vw;\
height:min(78vh,620px);border-radius:12px 12px 0 0;border-left:0;border-right:0}\
.asst-bouton{right:14px;bottom:14px}}\
@media (prefers-reduced-motion:reduce){.asst-attente span{animation:none}}\
@media (prefers-color-scheme:dark){.asst-bouton{color:#0d1218}\
.asst-saisie button{color:#0d1218}\
.asst-msg mark{background:#5c4a12;color:#f7ecc4}}\
@media print{.asst-bouton,.asst-panneau{display:none!important}}';

  var SUGGESTIONS = [
    'Quelles sont les conditions d’agrément des SGI ?',
    'Que dit l’article 37 du Règlement Général ?',
    'Quelles sanctions prévoit l’instruction n° 81 de 2025 ?'
  ];

  var panneau = null, fil = null, saisie = null, bouton = null;
  var suggestionsBloc = null;

  function construireInterface() {
    var style = document.createElement('style');
    style.textContent = STYLES;
    document.head.appendChild(style);

    bouton = document.createElement('button');
    bouton.type = 'button';
    bouton.className = 'asst-bouton';
    bouton.setAttribute('aria-label', 'Ouvrir l’assistant documentaire');
    bouton.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.38 ' +
      '8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9' +
      '-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9' +
      'h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg><span>Assistant</span>';
    bouton.addEventListener('click', function () {
      panneau.hidden ? ouvrir() : fermer();
    });
    document.body.appendChild(bouton);

    panneau = document.createElement('section');
    panneau.className = 'asst-panneau';
    panneau.hidden = true;
    panneau.setAttribute('role', 'dialog');
    panneau.setAttribute('aria-label', 'Assistant documentaire');
    panneau.innerHTML =
      '<header class="asst-tete">' +
      '<div><h2>Assistant documentaire</h2>' +
      '<p>Répond en citant les textes du recueil</p></div>' +
      '<button type="button" class="asst-fermer" aria-label="Fermer">×</button>' +
      '</header>' +
      '<div class="asst-fil" role="log" aria-live="polite"></div>' +
      '<div class="asst-suggestions" hidden></div>' +
      '<form class="asst-saisie">' +
      '<label class="visuellement-masque" for="asst-q">Votre question</label>' +
      '<input id="asst-q" type="text" autocomplete="off" ' +
      'placeholder="Posez votre question…">' +
      '<button type="submit">Envoyer</button></form>' +
      '<p class="asst-confidentialite">Assistant sans serveur : vos questions ' +
      'ne quittent pas votre navigateur. Réponses sans valeur juridique.</p>';
    document.body.appendChild(panneau);

    fil = panneau.querySelector('.asst-fil');
    saisie = panneau.querySelector('input');
    suggestionsBloc = panneau.querySelector('.asst-suggestions');

    panneau.querySelector('.asst-fermer').addEventListener('click', fermer);
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !panneau.hidden) fermer();
    });

    panneau.querySelector('form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var q = saisie.value.trim();
      if (!q) return;
      saisie.value = '';
      poser(q);
    });

    SUGGESTIONS.forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = s;
      b.addEventListener('click', function () { poser(s); });
      suggestionsBloc.appendChild(b);
    });
  }

  function ouvrir() {
    panneau.hidden = false;
    bouton.setAttribute('aria-expanded', 'true');
    if (!fil.childNodes.length && !restaurer()) {
      ajouter('a',
        '<p>Bonjour. Posez votre question sur les textes du marché ' +
        'financier régional : je retrouve les dispositions pertinentes ' +
        'dans le recueil et je les cite telles quelles, avec le lien vers ' +
        'chaque texte.</p>' +
        '<p class="asst-note">Je ne sais que citer les documents publiés ' +
        'ici. Mes réponses n’ont aucune valeur juridique : seul ' +
        'le PDF original fait foi.</p>', true);
      suggestionsBloc.hidden = false;
    }
    charger();
    saisie.focus();
  }

  function fermer() {
    panneau.hidden = true;
    bouton.setAttribute('aria-expanded', 'false');
    bouton.focus();
  }

  function ajouter(role, html, sansMemoire) {
    var d = document.createElement('div');
    d.className = 'asst-msg ' + role;
    d.innerHTML = html;
    fil.appendChild(d);
    fil.scrollTop = fil.scrollHeight;
    if (!sansMemoire) memoriser(role, html);
    return d;
  }

  /* --- Mémoire de session : le fil survit à la navigation ---------------- */

  function memoriser(role, html) {
    try {
      var f = JSON.parse(sessionStorage.getItem(CLE_MEMOIRE) || '[]');
      f.push({ r: role, h: html });
      sessionStorage.setItem(CLE_MEMOIRE, JSON.stringify(f.slice(-14)));
    } catch (e) { /* stockage indisponible : le fil reste par page */ }
  }

  function restaurer() {
    try {
      var f = JSON.parse(sessionStorage.getItem(CLE_MEMOIRE) || '[]');
      if (!f.length) return false;
      f.forEach(function (m) { ajouter(m.r, m.h, true); });
      return true;
    } catch (e) { return false; }
  }

  /* ======================================================================
     Chargement des données
     ====================================================================== */

  function charger() {
    if (index || chargement) return chargement;
    chargement = fetch(RACINE + 'data/index-recherche.json')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) { index = d; return d; })
      .catch(function () {
        chargement = null;
        return null;
      });
    return chargement;
  }

  function texteDocument(slug) {
    if (cacheDoc[slug]) return Promise.resolve(cacheDoc[slug]);
    return fetch(RACINE + 'data/' + encodeURIComponent(slug) + '.txt')
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (t) {
        if (t === null) return null;
        var d = { texte: t, segments: segmenter(t) };
        cacheDoc[slug] = d;
        return d;
      })
      .catch(function () { return null; });
  }

  /* ======================================================================
     Découpage d'un document en passages
     ======================================================================
     Le texte brut sérialise les blocs du site : chaque titre, section ou
     article y figure sous la forme « Marque — Intitulé ». Les ancres sont
     recalculées exactement comme le fait le générateur : le lien d'un
     passage pointe donc l'article précis dans la page. */

  var RE_TITRE = /^(?:TITRE|CHAPITRE|SOUS-TITRE|LIVRE)\s(?:[IVXLC]+|PREMIER|\d+)$/;
  var RE_SECTION = /^Section\s(?:[IVXLC]+|\d+)$/;
  var RE_ARTICLE = /^Article\s(?:premier|\d+(?:\s(?:bis|ter|quater))?)$/;

  function ancreDe(marque, compteur) {
    var base = normaliser(marque).replace(/[^a-z0-9]+/g, '-')
      .replace(/-{2,}/g, '-').replace(/^-+|-+$/g, '') || 'section';
    compteur[base] = (compteur[base] || 0) + 1;
    return compteur[base] === 1 ? base : base + '-' + compteur[base];
  }

  function segmenter(texte) {
    // Passe l'en-tête « Titre / ==== / ligne vide ».
    var corps = texte;
    var coupe = corps.indexOf('\n\n');
    if (coupe !== -1 && /\n=+\s*$/.test(corps.slice(0, coupe))) {
      corps = corps.slice(coupe + 2);
    }

    var blocs = corps.split('\n\n');
    var segments = [];
    var compteur = {};
    var courant = null;

    function clore() {
      if (courant && (courant.corps.length || courant.chapeau)) {
        courant.texteEntier = (courant.chapeau ? courant.chapeau + '\n' : '') +
                              courant.corps.join('\n');
        segments.push(courant);
      }
      courant = null;
    }

    blocs.forEach(function (bloc) {
      var tiret = bloc.indexOf(' — ');
      var marque = tiret === -1 ? '' : bloc.slice(0, tiret);
      var estTete = tiret !== -1 &&
        (RE_ARTICLE.test(marque) || RE_TITRE.test(marque) ||
         RE_SECTION.test(marque));

      if (estTete) {
        clore();
        var intitule = bloc.slice(tiret + 3).trim();
        courant = {
          marque: marque,
          intitule: intitule,
          chapeau: intitule ? marque + ' — ' + intitule : marque,
          ancre: ancreDe(marque, compteur),
          article: RE_ARTICLE.test(marque),
          corps: []
        };
      } else {
        if (!courant) {
          courant = { marque: '', intitule: '', chapeau: '', ancre: '',
                      article: false, corps: [] };
        }
        courant.corps.push(bloc);
        // Un passage sans tête ne doit pas devenir interminable.
        if (!courant.marque &&
            courant.corps.join(' ').length > 900) clore();
      }
    });
    clore();

    return segments;
  }

  /* ======================================================================
     Recherche : documents puis passages
     ====================================================================== */

  function idf(mot) {
    var p = index.termes[mot];
    return p ? Math.log(1 + index.docs.length / p.length) : 2.5;
  }

  function motsPorteurs(tous) {
    var porteurs = tous.filter(function (m) {
      return !MOTS_VIDES[m] && !MOTS_QUESTION[m];
    });
    // Si la question n'est faite que de tournures, on garde tout de même
    // les mots non vides plutôt que de ne rien chercher.
    if (!porteurs.length) {
      porteurs = tous.filter(function (m) { return !MOTS_VIDES[m]; });
    }
    return porteurs;
  }

  function chercherDocuments(mots) {
    var scores = Object.create(null);
    var trouves = Object.create(null);
    var utiles = 0;

    mots.forEach(function (mot) {
      var entrees = index.termes[mot] ? [[mot, index.termes[mot]]] : [];
      if (!entrees.length && mot.length >= 4) {
        var cles = Object.keys(index.termes), n = 0;
        for (var i = 0; i < cles.length && n < 24; i++) {
          if (cles[i].indexOf(mot) === 0) {
            entrees.push([cles[i], index.termes[cles[i]]]);
            n++;
          }
        }
      }
      if (!entrees.length) return;
      utiles++;

      entrees.forEach(function (paire) {
        var poids = Math.log(1 + index.docs.length / paire[1].length);
        paire[1].forEach(function (p) {
          var d = p[0], tf = p[1];
          var dl = index.docs[d][7] || 1;
          var norme = 1 - B + B * dl / (index.longueurMoyenne || dl);
          scores[d] = (scores[d] || 0) +
            poids * tf * (K1 + 1) / (tf + K1 * norme);
          trouves[d] = (trouves[d] || 0) + 1;
        });
      });
    });

    var sortie = [];
    Object.keys(scores).forEach(function (d) {
      var i = parseInt(d, 10);
      var doc = index.docs[i];
      var couverture = utiles ? Math.min(trouves[d], utiles) / utiles : 0;
      sortie.push({
        i: i, doc: doc,
        score: scores[d] * (0.35 + 0.65 * couverture)
             * (POIDS_TYPE[doc[2]] || 1)
             * (doc[4] ? 0.7 : 1)
      });
    });
    sortie.sort(function (a, b) { return b.score - a.score; });
    return sortie;
  }

  function scorerSegment(seg, mots, requeteNorm) {
    if (!seg.jetons) {
      var js = decouper(seg.texteEntier);
      seg.jetons = {};
      js.forEach(function (j) {
        seg.jetons[j] = (seg.jetons[j] || 0) + 1;
      });
      seg.longueur = js.length || 1;
      seg.teteNorm = normaliser(seg.chapeau);
      seg.norm = normaliser(seg.texteEntier);
    }

    var score = 0, couverts = 0;
    mots.forEach(function (mot) {
      var tf = seg.jetons[mot] || 0;
      if (!tf && mot.length >= 4) {
        // Préfixe : « agrement » couvre « agrements », « agrementee »…
        for (var j in seg.jetons) {
          if (j.indexOf(mot) === 0) tf += seg.jetons[j] * 0.85;
        }
      }
      if (!tf) return;
      couverts++;
      var sat = tf * 2.4 / (tf + 1.4 * (0.6 + 0.4 * seg.longueur / 120));
      var s = idf(mot) * sat;
      // Le terme figure dans l'intitulé même de l'article : signal fort.
      if (seg.teteNorm && seg.teteNorm.indexOf(mot) !== -1) s *= 1.9;
      score += s;
    });

    if (!couverts) return { score: 0, couverture: 0 };
    var couverture = couverts / mots.length;
    score *= Math.pow(0.3 + 0.7 * couverture, 1.4);
    // La question entière figure telle quelle dans le passage.
    if (mots.length >= 2 && requeteNorm &&
        seg.norm.indexOf(requeteNorm) !== -1) score *= 1.4;
    if (seg.article) score *= 1.12;
    return { score: score, couverture: couverture };
  }

  /* --- Détection des références citées dans la question ------------------ */

  function chiffresDe(t) {
    return (t.match(/\d+/g) || []).map(function (x) {
      return parseInt(x, 10);
    });
  }

  function analyserReference(qNorm) {
    var ref = { type: null, numero: null, annee: null, article: null,
                articleRG: null, cibles: [] };

    var m = qNorm.match(/article\s+(premier|1er|\d{1,3})\s+(?:du\s+|dudit\s+)?reglement\s+general/);
    if (m) {
      ref.articleRG = m[1] === '1er' ? 'premier' : m[1];
    } else if ((m = qNorm.match(/article\s+(premier|1er|\d{1,3})/))) {
      ref.article = m[1] === '1er' ? 'premier' : m[1];
    }

    m = qNorm.match(/\b(instruction|circulaire|decision|rapport)s?\b/);
    if (m) ref.type = m[1];
    else if (/\breglement\s+general\b/.test(qNorm)) ref.type = 'rg';
    else if (/\b(convention|annexe|avenant)\b/.test(qNorm)) {
      ref.type = qNorm.match(/\b(convention|annexe|avenant)\b/)[1];
    }

    // « 1er » et « premier » produisent un 1 parasite dans les chiffres.
    var exclureUn = /\b1er\b|\bpremier\b/.test(qNorm);
    var nombres = chiffresDe(qNorm).filter(function (n) {
      return !(exclureUn && n === 1);
    });
    nombres.forEach(function (n) {
      if (n >= 1900 && n <= 2099) { if (!ref.annee) ref.annee = n; }
      else if (!ref.numero && (!ref.article || String(n) !== ref.article)) {
        ref.numero = n;
      }
    });

    if (!index) return ref;

    if (ref.type === 'rg') {
      index.docs.forEach(function (doc, i) {
        if (doc[0] === 'reglement-general') ref.cibles.push(i);
      });
    } else if (ref.type === 'convention' || ref.type === 'annexe' ||
               ref.type === 'avenant') {
      // Ancrage en tête d'intitulé : « Annexe à la Convention » ne doit pas
      // répondre à une question sur la Convention elle-même.
      index.docs.forEach(function (doc, i) {
        if (doc[2] === 'base' &&
            normaliser(doc[1]).indexOf(ref.type) === 0) ref.cibles.push(i);
      });
    } else if (ref.type && ref.numero !== null) {
      index.docs.forEach(function (doc, i) {
        if (doc[2] !== ref.type) return;
        var groupes = chiffresDe(doc[5] || '');
        if (groupes.indexOf(ref.numero) === -1) return;
        if (ref.annee && String(doc[3]) !== String(ref.annee) &&
            groupes.indexOf(ref.annee) === -1) return;
        ref.cibles.push(i);
      });
    } else if (ref.type === 'rapport' && ref.annee) {
      index.docs.forEach(function (doc, i) {
        if (doc[2] === 'rapport' &&
            String(doc[3]) === String(ref.annee)) ref.cibles.push(i);
      });
    }
    return ref;
  }

  /* ======================================================================
     Construction des réponses
     ====================================================================== */

  function libelleDoc(doc) {
    var nom = doc[5] ? TYPES[doc[2]] + ' ' + doc[5] : doc[1];
    return nom;
  }

  function lienDoc(doc, ancre) {
    return RACINE + 'textes/' + encodeURIComponent(doc[0]) + '/' +
      (ancre ? '#' + ancre : '');
  }

  function carteHTML(doc, seg, extrait) {
    var h = '<div class="asst-carte">';
    h += '<div class="asst-carte-tete"><a href="' +
      echapper(lienDoc(doc, seg && seg.ancre)) + '">' +
      echapper(libelleDoc(doc)) + '</a>' +
      (doc[3] ? ' <span class="asst-annee">· ' + echapper(doc[3]) +
        '</span>' : '') +
      (doc[4] ? '<span class="asst-badge">Abrogé</span>' : '') +
      '</div>';
    if (seg && seg.chapeau) {
      h += '<div class="asst-article">' + echapper(seg.chapeau.slice(0, 120)) +
        '</div>';
    }
    if (extrait) h += '<blockquote>' + extrait + '</blockquote>';
    h += '<div class="asst-carte-pied"><a href="' +
      echapper(lienDoc(doc, seg && seg.ancre)) + '">Lire dans le texte →' +
      '</a></div></div>';
    return h;
  }

  function extraitHTML(seg, mots) {
    var texte = seg.corps.join(' ').replace(/\s+/g, ' ').trim();
    if (!texte) texte = seg.chapeau;
    var norm = normaliser(texte);

    // Fenêtre centrée sur la première co-occurrence des termes.
    var pos = -1;
    for (var i = 0; i < mots.length; i++) {
      var p = norm.indexOf(mots[i]);
      if (p !== -1 && (pos === -1 || p < pos)) pos = p;
    }
    if (pos === -1) pos = 0;

    var debut = Math.max(0, pos - 110);
    // Un passage court se cite en entier, un début tout proche se garde.
    if (texte.length <= 520 || debut < 60) debut = 0;
    var fin = Math.min(texte.length, debut + 480);
    // Étendre aux limites de phrases quand c'est possible.
    if (debut > 0) {
      var av = texte.lastIndexOf('. ', pos);
      if (av !== -1 && pos - av < 220) debut = av + 2;
    }
    var ap = texte.indexOf('. ', fin - 30);
    if (ap !== -1 && ap - fin < 120) fin = ap + 1;

    // Ne jamais couper au milieu d'un mot.
    if (debut > 0 && texte[debut - 1] !== ' ' && texte[debut] !== ' ') {
      var apresMot = texte.indexOf(' ', debut);
      if (apresMot !== -1 && apresMot - debut < 25) debut = apresMot + 1;
    }
    if (fin < texte.length && texte[fin] !== ' ' && texte[fin - 1] !== ' ' &&
        texte[fin - 1] !== '.') {
      var avantMot = texte.lastIndexOf(' ', fin);
      if (avantMot > debut && fin - avantMot < 25) fin = avantMot;
    }

    var bout = texte.slice(debut, fin).trim();
    if (debut > 0) bout = '… ' + bout;
    if (fin < texte.length) bout += ' …';

    // Surlignage insensible aux accents.
    var normBout = normaliser(bout);
    var zones = [];
    mots.forEach(function (m) {
      if (m.length < 3) return;
      var d = 0, k;
      while ((k = normBout.indexOf(m, d)) !== -1) {
        zones.push([k, k + m.length]);
        d = k + m.length;
      }
    });
    if (!zones.length) return echapper(bout);
    zones.sort(function (a, b) { return a[0] - b[0]; });
    var fusion = [zones[0]];
    for (var z = 1; z < zones.length; z++) {
      var der = fusion[fusion.length - 1];
      if (zones[z][0] <= der[1]) der[1] = Math.max(der[1], zones[z][1]);
      else fusion.push(zones[z]);
    }
    var sortie = '', curseur = 0;
    fusion.forEach(function (zn) {
      sortie += echapper(bout.slice(curseur, zn[0]));
      sortie += '<mark>' + echapper(bout.slice(zn[0], zn[1])) + '</mark>';
      curseur = zn[1];
    });
    return sortie + echapper(bout.slice(curseur));
  }

  var NOTE_FIABILITE =
    '<p class="asst-note">Extraits obtenus par reconnaissance optique des ' +
    'documents scannés : seul le PDF original, accessible depuis ' +
    'chaque fiche, fait foi.</p>';

  function segmentParArticle(segments, numero) {
    var voulu = 'article ' + numero;
    for (var i = 0; i < segments.length; i++) {
      if (normaliser(segments[i].marque) === voulu) return segments[i];
    }
    return null;
  }

  function segmentDePresentation(segments) {
    // L'article « Objet », « Définitions » ou « Champ d'application » présente
    // le texte mieux que tout autre ; à défaut, le premier article.
    for (var i = 0; i < segments.length; i++) {
      if (segments[i].article &&
          /objet|champ d.application|definition/.test(
            normaliser(segments[i].intitule))) return segments[i];
    }
    for (var j = 0; j < segments.length; j++) {
      if (segments[j].article) return segments[j];
    }
    return segments[0] || null;
  }

  /* --- Conversation ------------------------------------------------------ */

  function poser(question) {
    suggestionsBloc.hidden = true;
    ajouter('u', echapper(question));
    var attente = ajouter('a',
      '<span class="asst-attente" aria-label="Recherche en cours">' +
      '<span></span><span></span><span></span></span>', true);

    repondre(question).then(function (html) {
      attente.remove();
      ajouter('a', html);
    }).catch(function () {
      attente.remove();
      ajouter('a', '<p>Une erreur est survenue pendant la recherche. ' +
        'Réessayez, ou utilisez la <a href="' +
        echapper(RACINE + 'recherche/') + '">recherche plein texte</a>.</p>');
    });
  }

  function repondre(question) {
    var qNorm = normaliser(question).replace(/\s+/g, ' ').trim();

    /* Petites conversations : on reste poli sans mobiliser le moteur. */
    if (/^(bonjour|bonsoir|salut|hello|coucou|bjr)\b[\s!.]*$/.test(qNorm)) {
      return Promise.resolve(
        '<p>Bonjour. Posez votre question sur les textes du recueil : ' +
        'agréments, opérations, obligations des acteurs, ' +
        'sanctions… Je répondrai en citant les dispositions ' +
        'pertinentes.</p>');
    }
    if (/^\s*(merci|merci beaucoup|merci bien|parfait|super)[\s!.]*$/.test(qNorm)) {
      return Promise.resolve(
        '<p>Avec plaisir. Je reste à votre disposition pour toute autre ' +
        'question sur les textes du recueil.</p>');
    }
    if (/^(au revoir|a bientot|bonne (journee|soiree|fin de journee))[\s!.]*$/.test(qNorm)) {
      return Promise.resolve('<p>Au revoir, et bonne lecture des textes.</p>');
    }
    if (/(qui es[\s-]tu|que sais[\s-]tu faire|comment (ca |sa )?(marche|fonctionne)|c.est quoi cet assistant|es[\s-]tu une (ia|intelligence))/.test(qNorm)) {
      return Promise.resolve(
        '<p>Je suis l’assistant de recherche du recueil. Je fonctionne ' +
        'entièrement dans votre navigateur, sans serveur ni modèle ' +
        'génératif : j’analyse votre question, je retrouve ' +
        'les dispositions pertinentes par recherche plein texte, puis je les ' +
        'cite telles quelles avec le lien vers chaque document. Je ne peux ' +
        'donc pas inventer de réponse — et quand je ne trouve ' +
        'pas, je le dis.</p>');
    }

    return charger().then(function (ix) {
      if (!ix) {
        return '<p>L’index de recherche n’a pas pu être ' +
          'chargé. Vérifiez votre connexion puis réessayez.</p>';
      }

      if (/combien (de )?(documents?|textes?)|taille du (recueil|corpus)|quels? types? de (documents?|textes?)/.test(qNorm)) {
        return reponseStatistiques();
      }

      var tous = decouper(qNorm);
      var mots = motsPorteurs(tous);
      var ref = analyserReference(qNorm);

      /* Suite de conversation : « et l'article 19 ? » hérite du contexte. */
      if (!ref.cibles.length && ref.article && !ref.type &&
          mots.length <= 2 && contexte.docs.length) {
        ref.cibles = contexte.docs.slice();
      }
      if (mots.length && mots.length < 2 && !ref.cibles.length &&
          !ref.article && contexte.mots.length) {
        contexte.mots.forEach(function (m) {
          if (mots.indexOf(m) === -1) mots.push(m);
        });
      }

      if (!mots.length && !ref.cibles.length) {
        return '<p>Précisez votre question d’un ou deux mots-clés ' +
          '— par exemple : « agrément des SGI », ' +
          '« appel public à l’épargne », ' +
          '« article 37 du Règlement Général ».</p>';
      }

      /* Référence explicite : la réponse est déterministe. */
      if (ref.articleRG || (ref.cibles.length && (ref.article || mots.length <= 4))) {
        return reponseReference(ref, mots, qNorm);
      }

      return reponseRecherche(mots, qNorm, ref);
    });
  }

  var PLURIELS = {
    base: 'textes de base', instruction: 'instructions',
    circulaire: 'circulaires', decision: 'décisions',
    autre: 'autres actes', rapport: 'rapports'
  };

  function reponseStatistiques() {
    var parType = {};
    index.docs.forEach(function (d) {
      parType[d[2]] = (parType[d[2]] || 0) + 1;
    });
    var morceaux = Object.keys(TYPES).filter(function (k) {
      return parType[k];
    }).map(function (k) {
      return parType[k] + ' ' + (parType[k] > 1
        ? PLURIELS[k] : TYPES[k].toLowerCase());
    });
    return '<p>Le recueil compte <strong>' + index.docs.length +
      ' documents</strong> : ' + echapper(morceaux.join(', ')) +
      '. La <a href="' + echapper(RACINE + 'recherche/') +
      '">recherche plein texte</a> porte sur leur contenu intégral, et la ' +
      '<a href="' + echapper(RACINE + 'chronologie/') +
      '">chronologie</a> les classe par année.</p>';
  }

  /* Réponse à une référence précise : « article 37 du RG »,
     « instruction 81 », « article 18 de l'instruction 81 de 2025 ». */
  function reponseReference(ref, mots, qNorm) {
    var cibles = [];
    if (ref.articleRG) {
      index.docs.forEach(function (doc, i) {
        if (doc[0] === 'reglement-general') cibles.push(i);
      });
    } else {
      cibles = ref.cibles.slice(0, 3);
    }
    if (!cibles.length) return reponseRecherche(mots, qNorm, ref);

    var numArticle = ref.articleRG || ref.article;

    // Les mots de la référence elle-même (« instruction », « 81 »,
    // « 2025 »…) désignent le document, pas le sujet : les garder
    // fausserait le choix du passage au profit des en-têtes.
    var motsSujet = mots.filter(function (m) {
      if (m === ref.type || m === 'article' || m === 'amf' ||
          m === 'umoa' || m === 'no' || m === 'annuel') return false;
      if (ref.type === 'rg' && (m === 'reglement' || m === 'general')) {
        return false;
      }
      if (/^\d+$/.test(m)) {
        var n = parseInt(m, 10);
        if (n === ref.numero || n === ref.annee ||
            m === String(numArticle)) return false;
      }
      return true;
    });

    return Promise.all(cibles.map(function (i) {
      return texteDocument(index.docs[i][0]);
    })).then(function (docs) {
      var cartes = [], liesTitres = [];
      var slugsCites = [];

      docs.forEach(function (d, k) {
        var doc = index.docs[cibles[k]];
        if (!d) { cartes.push(carteHTML(doc, null, '')); return; }

        var seg = null;
        if (numArticle) {
          seg = segmentParArticle(d.segments, numArticle);
          if (!seg && cibles.length === 1) {
            cartes.push('<p>Je ne trouve pas d’article ' +
              echapper(numArticle) + ' dans ' + echapper(libelleDoc(doc)) +
              '. Voici le début du texte :</p>' +
              carteHTML(doc, d.segments[0],
                extraitHTML(d.segments[0], motsSujet)));
            slugsCites.push(cibles[k]);
            return;
          }
        }
        if (!seg && motsSujet.length) {
          var meilleur = null, meilleurScore = 0;
          d.segments.forEach(function (s) {
            var r = scorerSegment(s, motsSujet, qNorm);
            if (r.score > meilleurScore) {
              meilleurScore = r.score; meilleur = s;
            }
          });
          seg = meilleur;
        }
        if (!seg) seg = segmentDePresentation(d.segments);
        if (!seg) { cartes.push(carteHTML(doc, null, '')); return; }
        cartes.push(carteHTML(doc, seg, extraitHTML(seg, motsSujet)));
        slugsCites.push(cibles[k]);
      });

      /* L'article demandé a-t-il été modifié par un autre texte du
         recueil ? Les décisions modificatives le portent dans leur titre. */
      if (ref.articleRG) {
        index.docs.forEach(function (doc) {
          if (normaliser(doc[1]).indexOf('article ' + ref.articleRG) !== -1 &&
              doc[0] !== 'reglement-general') {
            liesTitres.push('<a href="' + echapper(lienDoc(doc)) + '">' +
              echapper(doc[1]) + '</a>');
          }
        });
      }

      contexte.mots = (motsSujet.length ? motsSujet : mots).slice(0, 6);
      contexte.docs = slugsCites.slice(0, 3);

      var intro;
      if (numArticle) {
        intro = '<p>Voici ce que je trouve pour l’article ' +
          echapper(numArticle) + ' :</p>';
      } else if (motsSujet.length && cibles.length === 1) {
        intro = '<p>Voici ce que je trouve dans ce texte :</p>';
      } else {
        intro = cibles.length > 1
          ? '<p>Voici les documents demandés :</p>'
          : '<p>Voici le document demandé :</p>';
      }
      var suite = liesTitres.length
        ? '<p class="asst-note">À noter : cet article est ' +
          'concerné par ' + liesTitres.join(' et ') + '.</p>'
        : '';
      return intro + cartes.join('') + suite + NOTE_FIABILITE;
    });
  }

  /* Réponse générale : présélection de documents, puis meilleurs passages. */
  function reponseRecherche(mots, qNorm, ref) {
    var classement = chercherDocuments(mots);
    if (!classement.length) {
      contexte.mots = [];
      return Promise.resolve(
        '<p>Je ne trouve rien dans le recueil sur ce sujet. Le vocabulaire ' +
        'des textes est parfois différent du langage courant : ' +
        'essayez d’autres termes, ou parcourez les rubriques depuis ' +
        'l’<a href="' + echapper(RACINE) + '">accueil</a>.</p>');
    }

    var candidats = classement.slice(0, 6);
    // Une référence détectée mais non exclusive rejoint les candidats.
    (ref.cibles || []).slice(0, 2).forEach(function (i) {
      if (!candidats.some(function (c) { return c.i === i; })) {
        candidats.unshift({ i: i, doc: index.docs[i],
                            score: classement[0].score });
      }
    });
    candidats = candidats.slice(0, 7);
    var meilleurDoc = candidats[0].score || 1;

    return Promise.all(candidats.map(function (c) {
      return texteDocument(c.doc[0]);
    })).then(function (textes) {
      var passages = [];
      textes.forEach(function (d, k) {
        if (!d) return;
        var prior = 0.7 + 0.3 * (candidats[k].score / meilleurDoc);
        d.segments.forEach(function (seg) {
          var r = scorerSegment(seg, mots, qNorm);
          if (!r.score) return;
          passages.push({
            doc: candidats[k].doc, seg: seg,
            score: r.score * prior *
              (candidats[k].doc[2] === 'rapport' ? 0.85 : 1),
            couverture: r.couverture
          });
        });
      });

      passages.sort(function (a, b) { return b.score - a.score; });

      // Deux passages au plus par document, trois documents au plus.
      var retenus = [], parDoc = {};
      for (var i = 0; i < passages.length && retenus.length < 3; i++) {
        var p = passages[i];
        parDoc[p.doc[0]] = (parDoc[p.doc[0]] || 0) + 1;
        if (parDoc[p.doc[0]] > 2) continue;
        retenus.push(p);
      }

      var seuilCouverture = mots.length >= 3 ? 0.45 : 0.9;
      var fiable = retenus.length &&
        retenus[0].couverture >= seuilCouverture &&
        retenus[0].score >= 1.1;

      contexte.mots = mots.slice(0, 6);
      contexte.docs = retenus.map(function (r) {
        return index.docs.indexOf(r.doc);
      }).filter(function (x) { return x !== -1; }).slice(0, 3);

      if (!fiable) {
        var proches = candidats.slice(0, 4).map(function (c) {
          return '<li><a href="' + echapper(lienDoc(c.doc)) + '">' +
            echapper(c.doc[1]) + '</a>' +
            (c.doc[3] ? ' <span class="asst-annee">(' + echapper(c.doc[3]) +
              ')</span>' : '') + '</li>';
        });
        return '<p>Je n’ai pas trouvé de passage qui réponde ' +
          'nettement à votre question. Les documents les plus proches ' +
          'sont :</p><ul>' + proches.join('') + '</ul>' +
          '<p class="asst-note">La <a href="' +
          echapper(RACINE + 'recherche/?q=' + encodeURIComponent(
            mots.join(' '))) + '">recherche plein texte</a> permet ' +
          'd’explorer plus largement, ou reformulez avec d’autres ' +
          'termes.</p>';
      }

      var cartes = retenus.map(function (r) {
        return carteHTML(r.doc, r.seg, extraitHTML(r.seg, mots));
      });
      var intro = retenus.length > 1
        ? '<p>Voici les dispositions du recueil qui répondent le mieux ' +
          'à votre question :</p>'
        : '<p>Voici la disposition du recueil qui répond le mieux ' +
          'à votre question :</p>';
      var plus = '<p class="asst-note"><a href="' +
        echapper(RACINE + 'recherche/?q=' + encodeURIComponent(
          mots.join(' '))) +
        '">Voir tous les résultats dans la recherche plein texte</a></p>';
      return intro + cartes.join('') + plus + NOTE_FIABILITE;
    });
  }

  /* ======================================================================
     Lancement
     ====================================================================== */

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', construireInterface);
  } else {
    construireInterface();
  }
})();
