/* ==========================================================================
   Recherche plein texte côté client.

   L'index inversé est chargé une fois, puis interrogé en mémoire : aucune
   requête réseau par frappe, et le site reste entièrement statique.
   Les extraits de résultat sont construits en récupérant à la demande le texte
   brut des seuls documents affichés en tête, ce qui évite d'embarquer le corpus
   entier dans l'index.
   ========================================================================== */

(function () {
  'use strict';

  var TYPES = {
    base: 'Texte de base', instruction: 'Instruction', circulaire: 'Circulaire',
    decision: 'Décision', rapport: 'Rapport'
  };
  // Paramètres BM25 usuels : saturation de la fréquence et normalisation
  // partielle par la longueur.
  var K1 = 1.2, B = 0.6;

  // Le recueil sert d'abord à trouver la règle applicable. À pertinence
  // textuelle comparable, le texte normatif passe donc devant le rapport
  // annuel qui ne fait que mentionner le sujet.
  var POIDS_TYPE = {
    base: 1.35, instruction: 1.2, circulaire: 1.2, decision: 1.2, rapport: 0.75
  };

  var champ = document.getElementById('q');
  var etat = document.getElementById('etat');
  var liste = document.getElementById('resultats');
  var filtres = document.getElementById('filtres');
  var boutonVider = document.getElementById('vider');

  var index = null;
  var typeActif = '';
  var derniereRequete = '';
  var cacheTexte = {};

  /* --- Normalisation identique à celle de l'indexeur -------------------- */

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
    var d = document.createElement('span');
    d.textContent = t;
    return d.innerHTML;
  }

  /* --- Chargement de l'index ------------------------------------------- */

  fetch('../data/index-recherche.json')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      index = data;
      etat.textContent = index.docs.length +
        ' documents indexés. Saisissez un ou plusieurs mots-clés.';
      filtres.hidden = false;
      var initiale = new URLSearchParams(location.search).get('q');
      if (initiale) {
        champ.value = initiale;
        lancer();
      }
    })
    .catch(function (err) {
      etat.textContent = "L'index de recherche n'a pas pu être chargé (" +
        err.message + '). Vous pouvez parcourir le corpus par type ou par date.';
    });

  /* --- Recherche -------------------------------------------------------- */

  function chercher(requete) {
    var mots = decouper(requete);
    if (!mots.length) return [];

    var scores = Object.create(null);
    var trouves = Object.create(null);
    var utiles = 0;

    mots.forEach(function (mot) {
      // Correspondance exacte, sinon préfixe (utile pour les pluriels et
      // les formes fléchies : « agrément » / « agréments »).
      var termes = index.termes[mot] ? [[mot, index.termes[mot]]] : [];
      if (!termes.length && mot.length >= 4) {
        var cles = Object.keys(index.termes), n = 0;
        for (var i = 0; i < cles.length && n < 24; i++) {
          if (cles[i].indexOf(mot) === 0) {
            termes.push([cles[i], index.termes[cles[i]]]);
            n++;
          }
        }
      }
      if (!termes.length) return;
      utiles++;

      termes.forEach(function (paire) {
        // Pondération inverse recalculée localement : un terme présent partout
        // discrimine moins qu'un terme rare.
        var idf = Math.log(1 + index.docs.length / paire[1].length);
        paire[1].forEach(function (p) {
          var d = p[0], tf = p[1];
          // Saturation BM25 et normalisation par la longueur du document : au
          // delà de quelques occurrences, une de plus n'apporte presque rien,
          // et un texte long ne prend pas l'avantage par sa seule taille.
          var dl = index.docs[d][7] || 1;
          var norme = 1 - B + B * dl / (index.longueurMoyenne || dl);
          scores[d] = (scores[d] || 0) + idf * tf * (K1 + 1) / (tf + K1 * norme);
          trouves[d] = (trouves[d] || 0) + 1;
        });
      });
    });

    if (!utiles) return [];

    var sortie = [];
    Object.keys(scores).forEach(function (d) {
      var i = parseInt(d, 10);
      var doc = index.docs[i];
      if (typeActif && doc[2] !== typeActif) return;
      // Un document couvrant tous les mots demandés passe devant.
      var couverture = Math.min(trouves[d], utiles) / utiles;
      sortie.push({
        doc: doc,
        score: scores[d] * (0.35 + 0.65 * couverture)
             * (POIDS_TYPE[doc[2]] || 1)
             * (doc[4] ? 0.7 : 1)          // un texte abrogé passe derrière
      });
    });

    sortie.sort(function (a, b) { return b.score - a.score; });
    return sortie.slice(0, 60);
  }

  /* --- Extraits --------------------------------------------------------- */

  function extraire(texte, mots) {
    var plat = normaliser(texte);
    var pos = -1, motTrouve = '';
    for (var i = 0; i < mots.length; i++) {
      var p = plat.indexOf(mots[i]);
      if (p !== -1 && (pos === -1 || p < pos)) { pos = p; motTrouve = mots[i]; }
    }
    if (pos === -1) return null;

    var debut = Math.max(0, pos - 130);
    var fin = Math.min(texte.length, pos + motTrouve.length + 230);
    var bout = texte.slice(debut, fin).replace(/\s+/g, ' ').trim();
    if (debut > 0) bout = '… ' + bout;
    if (fin < texte.length) bout += ' …';

    var html = echapper(bout);
    // Surlignage insensible aux accents : on repère les positions sur la
    // version normalisée puis on découpe la chaîne originale.
    var normBout = normaliser(bout);
    var zones = [];
    mots.forEach(function (m) {
      var d = 0, k;
      while ((k = normBout.indexOf(m, d)) !== -1) {
        zones.push([k, k + m.length]);
        d = k + m.length;
      }
    });
    if (!zones.length) return html;
    zones.sort(function (a, b) { return a[0] - b[0]; });
    var fusion = [zones[0]];
    for (var z = 1; z < zones.length; z++) {
      var last = fusion[fusion.length - 1];
      if (zones[z][0] <= last[1]) last[1] = Math.max(last[1], zones[z][1]);
      else fusion.push(zones[z]);
    }
    var out = '', curseur = 0;
    fusion.forEach(function (zone) {
      out += echapper(bout.slice(curseur, zone[0]));
      out += '<mark>' + echapper(bout.slice(zone[0], zone[1])) + '</mark>';
      curseur = zone[1];
    });
    out += echapper(bout.slice(curseur));
    return out;
  }

  function enrichir(resultats, mots) {
    resultats.slice(0, 8).forEach(function (r) {
      var slug = r.doc[0];
      var cible = liste.querySelector('[data-extrait="' + slug + '"]');
      if (!cible) return;

      var appliquer = function (texte) {
        var bout = extraire(texte, mots);
        if (bout) cible.innerHTML = bout;
      };

      if (cacheTexte[slug]) { appliquer(cacheTexte[slug]); return; }
      fetch('../data/' + slug + '.txt')
        .then(function (rep) { return rep.ok ? rep.text() : null; })
        .then(function (texte) {
          if (!texte) return;
          cacheTexte[slug] = texte;
          if (derniereRequete === champ.value.trim()) appliquer(texte);
        })
        .catch(function () { /* l'extrait de repli reste affiché */ });
    });
  }

  /* --- Rendu ------------------------------------------------------------ */

  function afficher(resultats, requete) {
    var mots = decouper(requete);
    liste.innerHTML = '';

    if (!resultats.length) {
      etat.textContent = 'Aucun résultat pour « ' + requete + ' »' +
        (typeActif ? ' dans ce type de document.' : '.') +
        ' Essayez des termes plus généraux ou une autre orthographe.';
      return;
    }

    etat.textContent = resultats.length + (resultats.length === 60 ? '+' : '') +
      ' document' + (resultats.length > 1 ? 's' : '') + ' trouvé' +
      (resultats.length > 1 ? 's' : '') + ' pour « ' + requete + ' »';

    var frag = document.createDocumentFragment();
    resultats.forEach(function (r) {
      var d = r.doc;
      var li = document.createElement('li');
      var meta = [d[5], d[3]].filter(Boolean).join(' · ');
      li.innerHTML =
        '<span class="res-type">' + echapper(TYPES[d[2]] || d[2]) + '</span>' +
        (d[4] ? ' <span class="badge abroge">Abrogé</span>' : '') +
        '<h2><a href="../textes/' + encodeURIComponent(d[0]) + '/">' +
        echapper(d[1]) + '</a></h2>' +
        (meta ? '<p class="res-meta">' + echapper(meta) + '</p>' : '') +
        '<p class="res-extrait" data-extrait="' + echapper(d[0]) + '">' +
        echapper(d[6] || '') + '</p>';
      frag.appendChild(li);
    });
    liste.appendChild(frag);
    enrichir(resultats, mots);
  }

  function lancer() {
    if (!index) return;
    var requete = champ.value.trim();
    derniereRequete = requete;
    if (!requete) {
      liste.innerHTML = '';
      etat.textContent = index.docs.length +
        ' documents indexés. Saisissez un ou plusieurs mots-clés.';
      return;
    }
    afficher(chercher(requete), requete);
  }

  /* --- Événements ------------------------------------------------------- */

  var minuteur;
  champ.addEventListener('input', function () {
    clearTimeout(minuteur);
    minuteur = setTimeout(lancer, 130);
  });

  champ.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); clearTimeout(minuteur); lancer(); }
  });

  boutonVider.addEventListener('click', function () {
    champ.value = '';
    champ.focus();
    lancer();
  });

  filtres.addEventListener('click', function (ev) {
    var b = ev.target.closest('button[data-type]');
    if (!b) return;
    typeActif = b.getAttribute('data-type');
    Array.prototype.forEach.call(filtres.querySelectorAll('button'), function (x) {
      x.classList.toggle('actif', x === b);
    });
    lancer();
  });
})();
