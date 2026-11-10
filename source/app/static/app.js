/* UniRecords - progressive enhancement only.
 * Every security decision is taken on the server; this script only improves
 * usability (page transitions, confirmations, loading states, toasts).
 * It is served from 'self', so the strict CSP (script-src 'self') still applies.
 */
(function () {
  "use strict";
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Smooth page transition when following an internal link.
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target || a.hasAttribute("download") || a.origin !== location.origin || a.hash) return;
    if (reduceMotion) return;
    e.preventDefault();
    document.body.classList.add("leaving");
    setTimeout(function () { location.href = a.href; }, 150);
  });
  window.addEventListener("pageshow", function () { document.body.classList.remove("leaving"); });

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

  // Count-up animation for dashboard figures.
  document.querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseFloat(el.getAttribute("data-count"));
    var decimals = parseInt(el.getAttribute("data-decimals") || "0", 10);
    if (isNaN(target) || reduceMotion) return;
    var start = performance.now(), duration = 700;
    function step(now) {
      var p = Math.min(1, (now - start) / duration), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * eased).toFixed(decimals);
      if (p < 1) requestAnimationFrame(step);
    }
    el.textContent = (0).toFixed(decimals);
    requestAnimationFrame(step);
  });
})();
