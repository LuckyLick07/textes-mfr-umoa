/* Filtrage de l'annuaire des acteurs agréés.
 *
 * Tout se fait dans la page : le tableau complet est déjà dans le HTML, ce qui
 * le laisse lisible, imprimable et indexable sans script. Le filtre ne fait
 * que masquer des lignes.
 */
(function () {
  'use strict';

  var table = document.getElementById('an-table');
  if (!table) return;

  var champ = document.getElementById('an-q');
  var selCat = document.getElementById('an-cat');
  var selPays = document.getElementById('an-pays');
  var caseActifs = document.getElementById('an-actifs');
  var etat = document.getElementById('an-etat');
  var lignes = Array.prototype.slice.call(table.tBodies[0].rows);

  function sansAccent(t) {
    return t.normalize ? t.normalize('NFD').replace(/[\u0300-\u036f]/g, '') : t;
  }

  function filtrer() {
    var q = sansAccent((champ.value || '').trim().toUpperCase());
    var mots = q ? q.split(/\s+/) : [];
    var cat = selCat.value;
    var pays = selPays.value;
    var masquerInactifs = caseActifs.checked;
    var visibles = 0;

    for (var i = 0; i < lignes.length; i++) {
      var l = lignes[i];
      var ok = true;
      if (cat && l.getAttribute('data-cat') !== cat) ok = false;
      if (ok && pays && l.getAttribute('data-pays') !== pays) ok = false;
      if (ok && masquerInactifs && l.getAttribute('data-actif') !== '1') ok = false;
      if (ok && mots.length) {
        var champRecherche = l.getAttribute('data-nom') || '';
        for (var m = 0; m < mots.length; m++) {
          if (champRecherche.indexOf(mots[m]) === -1) { ok = false; break; }
        }
      }
      l.hidden = !ok;
      if (ok) visibles++;
    }

    var total = lignes.length;
    if (visibles === total) {
      etat.textContent = total + ' acteurs affichés.';
    } else if (visibles === 0) {
      etat.textContent = 'Aucun acteur ne correspond à ces critères.';
    } else {
      etat.textContent = visibles + ' acteur' + (visibles > 1 ? 's' : '') +
        ' sur ' + total + '.';
    }
  }

  var minuteur;
  champ.addEventListener('input', function () {
    clearTimeout(minuteur);
    minuteur = setTimeout(filtrer, 110);
  });
  selCat.addEventListener('change', filtrer);
  selPays.addEventListener('change', filtrer);
  caseActifs.addEventListener('change', filtrer);

  /* Une ancre « #sgi » posée depuis une autre page présélectionne la
     catégorie correspondante. */
  var ancre = (location.hash || '').replace('#', '');
  if (ancre && selCat.querySelector('option[value="' + ancre + '"]')) {
    selCat.value = ancre;
  }

  filtrer();
})();
