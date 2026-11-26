/* UniRecords - progressive enhancement only.
 * Every security decision is taken on the server; this script only improves
 * usability (confirmations, loading states, toasts, theme switch, mobile navigation).
 * It is served from 'self', so the strict CSP (script-src 'self') still applies.
 */
(function () {
  "use strict";
  // Confirmation for destructive actions and loading state on submit.
  document.addEventListener("submit", function (e) {
    var btn = e.submitter || e.target.querySelector("button[type=submit], button:not([type])");
    var message = (btn && btn.getAttribute("data-confirm")) || e.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) { e.preventDefault(); return; }
    if (btn && btn.classList.contains("btn")) {
      // Deferred so that the clicked button's name/value is still part of the submission.
      setTimeout(function () { btn.classList.add("is-loading"); btn.disabled = true; }, 0);
    }
  });

  // Show / hide password.
  document.querySelectorAll("[data-toggle-password]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-toggle-password"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  // Light / dark theme switch (see theme.js).
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    function label() {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      btn.setAttribute("title", dark ? "Light theme" : "Dark theme");
    }
    label();
    btn.addEventListener("click", function () { if (window.UniTheme) { window.UniTheme.toggle(); label(); } });
  });

  // Mobile navigation.
  var toggle = document.querySelector(".menu-toggle");
  if (toggle) toggle.addEventListener("click", function (e) {
    e.stopPropagation();
    document.body.classList.toggle("nav-open");
  });
  document.addEventListener("click", function (e) {
    if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  // Toasts disappear after a few seconds.
  document.querySelectorAll(".toast").forEach(function (t) {
    setTimeout(function () { t.classList.add("hide"); }, 4500);
    setTimeout(function () { t.remove(); }, 4900);
  });

})();
