/* Ouverture du PDF officiel.
 *
 * Le serveur de l'AMF-UMOA envoie les fichiers en application/octet-stream,
 * sans Content-Disposition : selon le navigateur, le PDF s'affiche alors en
 * octets bruts illisibles au lieu de s'ouvrir. Son API acceptant les requêtes
 * d'autres origines, on télécharge ici le fichier nous-mêmes puis on le
 * présente au navigateur sous son vrai type (application/pdf), dans un nouvel
 * onglet. En cas d'échec (réseau, CORS retiré, vieux navigateur), on retombe
 * sur le lien direct : jamais pire qu'avant.
 */
(function () {
  "use strict";
  var lien = document.querySelector("a.bouton[data-pdf-distant]");
  if (!lien || !window.fetch || !window.URL || !URL.createObjectURL) return;

  lien.addEventListener("click", function (ev) {
    ev.preventDefault();

    // L'onglet doit être ouvert pendant le clic, sinon les bloqueurs de
    // fenêtres surgissantes l'interdisent ; on le remplit une fois le
    // fichier reçu.
    var onglet = window.open("", "_blank");
    if (onglet) {
      try {
        onglet.document.write(
          "<title>PDF officiel…</title>" +
          "<p style=\"font-family:system-ui,sans-serif;color:#4a5766;" +
          "margin:2rem\">Téléchargement du PDF officiel…</p>");
      } catch (e) { /* sans gravité */ }
    }

    fetch(lien.href)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.blob();
      })
      .then(function (brut) {
        var pdf = new Blob([brut], { type: "application/pdf" });
        var adresse = URL.createObjectURL(pdf);
        if (onglet) { onglet.location = adresse; }
        else { window.location.href = adresse; }
        setTimeout(function () { URL.revokeObjectURL(adresse); }, 120000);
      })
      .catch(function () {
        // Repli : comportement d'origine, lien direct vers le serveur AMF.
        if (onglet) { onglet.location = lien.href; }
        else { window.location.href = lien.href; }
      });
  });
})();
