/* =========================================================================
   app.js — minimal vanilla JS for things HTMX doesn't cover.
   No build step. Loaded after htmx.min.js.

   Responsibilities:
     - Theme toggle (persisted in localStorage, follows system by default)
     - Flash auto-dismiss
     - Toast helper (window.toast)
     - Modal open/close (data-modal-target / data-modal-close)
     - File dropzone helper (data-dropzone)
     - Password strength meter (data-pw-strength)
     - Copy-to-clipboard (data-copy)
     - Confirm dialog wrapper for HTMX/form submits (data-confirm)
     - Simple table sorter (table.sortable)
     - HTMX hooks: flash from HX-Trigger events
   ========================================================================= */

(function () {
  "use strict";

  /* ---------- Theme ----------------------------------------------------- */
  const THEME_KEY = "inno_theme";
  function applyTheme(t) { document.documentElement.setAttribute("data-theme", t); }
  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    // Default matches the boot script in base.html (light, the Claude /
    // Anthropic warm-ivory aesthetic). Dark is opt-in via the toggle.
    const initial = saved || "light";
    applyTheme(initial);
    document.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-theme-toggle]");
      if (!btn) return;
      const cur = document.documentElement.getAttribute("data-theme") || "light";
      const next = cur === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem(THEME_KEY, next);
      updateThemeLabels(next);
    });
    updateThemeLabels(initial);
  }
  function updateThemeLabels(t) {
    document.querySelectorAll("[data-theme-label]").forEach(function (el) {
      el.textContent = t === "dark" ? "Dark" : "Light";
    });
  }

  /* ---------- Flash auto-dismiss --------------------------------------- */
  function initFlashes() {
    document.querySelectorAll(".alert[data-auto-dismiss]").forEach(function (el) {
      const ms = parseInt(el.getAttribute("data-auto-dismiss"), 10) || 5000;
      setTimeout(function () { dismiss(el); }, ms);
    });
    document.addEventListener("click", function (e) {
      const close = e.target.closest(".alert .alert-close, .toast .alert-close");
      if (!close) return;
      dismiss(close.closest(".alert, .toast"));
    });
  }
  function dismiss(el) {
    if (!el) return;
    el.style.transition = "opacity 200ms ease, transform 200ms ease";
    el.style.opacity = "0";
    el.style.transform = "translateY(-4px)";
    setTimeout(function () { el.remove(); }, 220);
  }

  /* ---------- Toast helper --------------------------------------------- */
  function ensureToastRegion() {
    let region = document.querySelector(".toast-region");
    if (!region) {
      region = document.createElement("div");
      region.className = "toast-region";
      region.setAttribute("aria-live", "polite");
      region.setAttribute("aria-atomic", "true");
      document.body.appendChild(region);
    }
    return region;
  }
  function toast(message, kind, opts) {
    opts = opts || {};
    const region = ensureToastRegion();
    const el = document.createElement("div");
    el.className = "toast alert alert-" + (kind || "info");
    el.innerHTML =
      '<div class="alert-body"><div>' + escapeHtml(message) + "</div></div>" +
      '<button class="alert-close" aria-label="Dismiss">×</button>';
    region.appendChild(el);
    const ttl = typeof opts.ttl === "number" ? opts.ttl : 4500;
    if (ttl > 0) setTimeout(function () { dismiss(el); }, ttl);
  }
  window.toast = toast;

  /* ---------- Modal ----------------------------------------------------- */
  function initModals() {
    document.addEventListener("click", function (e) {
      const opener = e.target.closest("[data-modal-target]");
      if (opener) {
        e.preventDefault();
        const sel = opener.getAttribute("data-modal-target");
        const m = document.querySelector(sel);
        if (m) openModal(m);
        return;
      }
      const closer = e.target.closest("[data-modal-close], .modal-backdrop");
      if (closer) {
        const backdrop = closer.closest(".modal-backdrop");
        // Only close on a direct click on the backdrop itself, or on an explicit
        // [data-modal-close] element. `closer === backdrop` would be true for any
        // click inside the modal (e.g. opening a <select> dropdown), which would
        // dismiss the modal as soon as the user interacted with a form field.
        if (backdrop && (e.target === backdrop || closer.hasAttribute("data-modal-close"))) {
          closeModal(backdrop);
        }
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      const visible = document.querySelector(".modal-backdrop:not(.hidden)");
      if (visible) closeModal(visible);
    });
  }
  function openModal(el) {
    el.classList.remove("hidden");
    el.removeAttribute("hidden");
    const first = el.querySelector("input, button, [tabindex]");
    if (first) first.focus();
    document.body.style.overflow = "hidden";
  }
  function closeModal(el) {
    el.classList.add("hidden");
    el.setAttribute("hidden", "");
    document.body.style.overflow = "";
  }
  window.openModal = openModal;
  window.closeModal = closeModal;

  /* ---------- Dropzone -------------------------------------------------- */
  function initDropzones() {
    document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
      const input = zone.querySelector('input[type="file"]');
      if (!input) return;
      zone.addEventListener("click", function () { input.click(); });
      ["dragenter", "dragover"].forEach(function (ev) {
        zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add("hover"); });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove("hover"); });
      });
      zone.addEventListener("drop", function (e) {
        if (!e.dataTransfer || !e.dataTransfer.files) return;
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      input.addEventListener("change", function () {
        const list = zone.querySelector("[data-dropzone-files]");
        if (!list) return;
        const names = Array.from(input.files).map(function (f) { return f.name; });
        list.innerHTML = names.length
          ? names.map(function (n) { return '<span class="chip">' + escapeHtml(n) + "</span>"; }).join("")
          : "";
      });
    });
  }

  /* ---------- Password strength ---------------------------------------- */
  function initPwStrength() {
    document.querySelectorAll("[data-pw-strength-for]").forEach(function (meter) {
      const target = document.querySelector(meter.getAttribute("data-pw-strength-for"));
      if (!target) return;
      target.addEventListener("input", function () {
        meter.setAttribute("data-score", String(scorePassword(target.value)));
      });
    });
  }
  function scorePassword(pw) {
    if (!pw) return 0;
    let s = 0;
    if (pw.length >= 8) s++;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
    if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
    return Math.min(4, s);
  }

  /* ---------- Copy to clipboard --------------------------------------- */
  function initCopy() {
    document.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-copy]");
      if (!btn) return;
      const value = btn.getAttribute("data-copy");
      if (!value) return;
      navigator.clipboard.writeText(value).then(function () {
        toast("Copied to clipboard", "success", { ttl: 1800 });
      }).catch(function () {
        toast("Copy failed", "error");
      });
    });
  }

  /* ---------- Confirm wrapper ----------------------------------------- */
  function initConfirms() {
    document.addEventListener("click", function (e) {
      const el = e.target.closest("[data-confirm]");
      if (!el) return;
      const msg = el.getAttribute("data-confirm");
      if (!window.confirm(msg)) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
      }
    }, true);
  }

  /* ---------- Basic table sorter (table.sortable) --------------------- */
  function initSortableTables() {
    document.querySelectorAll("table.sortable").forEach(function (tbl) {
      tbl.querySelectorAll("th[data-sort]").forEach(function (th) {
        th.classList.add("sortable");
        th.addEventListener("click", function () { sortTable(tbl, th); });
      });
    });
  }
  function sortTable(tbl, th) {
    const idx = Array.from(th.parentNode.children).indexOf(th);
    const tbody = tbl.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.rows);
    const type = th.getAttribute("data-sort") || "string";
    const prev = th.getAttribute("data-sort-dir") || "";
    const dir = prev === "asc" ? "desc" : "asc";
    tbl.querySelectorAll("th[data-sort]").forEach(function (h) {
      h.removeAttribute("data-sort-dir");
      const ind = h.querySelector(".sort-indicator");
      if (ind) ind.textContent = "";
    });
    th.setAttribute("data-sort-dir", dir);
    let ind = th.querySelector(".sort-indicator");
    if (!ind) {
      ind = document.createElement("span");
      ind.className = "sort-indicator";
      th.appendChild(ind);
    }
    ind.textContent = dir === "asc" ? " ↑" : " ↓";
    rows.sort(function (a, b) {
      const av = (a.cells[idx] && a.cells[idx].getAttribute("data-value")) || (a.cells[idx] ? a.cells[idx].textContent.trim() : "");
      const bv = (b.cells[idx] && b.cells[idx].getAttribute("data-value")) || (b.cells[idx] ? b.cells[idx].textContent.trim() : "");
      let cmp;
      if (type === "number") {
        cmp = parseFloat(av || "0") - parseFloat(bv || "0");
      } else if (type === "date") {
        cmp = new Date(av).getTime() - new Date(bv).getTime();
      } else {
        cmp = av.localeCompare(bv);
      }
      return dir === "asc" ? cmp : -cmp;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  /* ---------- HTMX wiring --------------------------------------------- */
  function initHtmx() {
    if (!window.htmx) return;
    document.body.addEventListener("htmx:responseError", function (e) {
      toast("Request failed (" + (e.detail.xhr && e.detail.xhr.status) + ")", "error");
    });
    document.body.addEventListener("htmx:sendError", function () {
      toast("Network error", "error");
    });
    document.body.addEventListener("flash", function (e) {
      const d = e.detail || {};
      toast(d.message || "", d.kind || "info", { ttl: d.ttl });
    });
  }

  /* ---------- Helpers --------------------------------------------------- */
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  /* ---------- Init ----------------------------------------------------- */
  function init() {
    initTheme();
    initFlashes();
    initModals();
    initDropzones();
    initPwStrength();
    initCopy();
    initConfirms();
    initSortableTables();
    initHtmx();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
