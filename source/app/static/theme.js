/* UniRecords - colour theme.
 * Loaded synchronously in <head> (not deferred) so the saved theme is applied
 * before the first paint, without a flash of the wrong colours. Served from
 * 'self', so the strict CSP (script-src 'self') is unchanged. Presentation only.
 * The theme follows the operating system until the user picks one with the
 * sun/moon button; the choice is kept in localStorage on this device.
 */
(function () {
  "use strict";
  var root = document.documentElement, media = window.matchMedia("(prefers-color-scheme: dark)");
  function saved() { try { return localStorage.getItem("theme"); } catch (e) { return null; } }
  function apply(theme) { root.setAttribute("data-theme", theme); }
  apply(saved() || (media.matches ? "dark" : "light"));
  // Follow the system setting while the user has not chosen a theme.
  media.addEventListener("change", function (e) { if (!saved()) apply(e.matches ? "dark" : "light"); });
  window.UniTheme = {
    toggle: function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem("theme", next); } catch (e) { /* private mode: theme lasts for this page only */ }
      return next;
    }
  };
})();
