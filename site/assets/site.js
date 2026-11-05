// Shared by every page: the phone menu, reveal-on-scroll, and counters.
// Everything here is progressive: without this file the page is complete,
// just still. With reduced motion asked for, nothing moves; it only appears.
(function () {
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- phone menu -------------------------------------------------------
  var nav = document.querySelector('.nav');
  var toggle = nav && nav.querySelector('.nav-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.textContent = open ? 'Close' : 'Menu';
    });
    nav.querySelectorAll('.nav-links a').forEach(function (a) {
      a.addEventListener('click', function () {
        nav.classList.remove('nav-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.textContent = 'Menu';
      });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('nav-open')) toggle.click();
    });
  }

  // ---- once-in-view helper ---------------------------------------------
  function whenSeen(el, run, threshold) {
    if (reduced || !('IntersectionObserver' in window)) { run(el); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { run(el); io.disconnect(); }
      });
    }, { threshold: threshold || 0.2 });
    io.observe(el);
  }
  window.hankoWhenSeen = whenSeen;

  // ---- sections rise in -------------------------------------------------
  document.querySelectorAll('[data-reveal]').forEach(function (el) {
    whenSeen(el, function () { el.classList.add('is-in'); }, 0.12);
  });

  // ---- numbers count up to their real value -----------------------------
  function countUp(el) {
    var target = Number(el.getAttribute('data-count'));
    if (!isFinite(target)) return;
    if (reduced) { el.textContent = target.toLocaleString('en-US'); return; }
    var start = null, dur = 1100;
    function step(t) {
      if (start === null) start = t;
      var p = Math.min(1, (t - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toLocaleString('en-US');
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  window.hankoCount = function (root) {
    (root || document).querySelectorAll('[data-count]').forEach(function (el) {
      whenSeen(el, countUp, 0.4);
    });
  };
  window.hankoCount();

  // ---- light / dark -----------------------------------------------------
  // The page follows the system until the visitor picks; the pick is kept.
  var root = document.documentElement;
  var themeBtn = document.querySelector('[data-theme-toggle]');
  var dark = window.matchMedia('(prefers-color-scheme: dark)');
  function isDark() {
    var t = root.getAttribute('data-theme');
    return t ? t === 'dark' : dark.matches;
  }
  var SUN = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8" cy="8" r="3"/><path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9L13 13M13 3l-1.1 1.1M4.1 11.9L3 13"/></svg>';
  var MOON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M13.5 9.6A5.6 5.6 0 0 1 6.4 2.5a5.6 5.6 0 1 0 7.1 7.1z"/></svg>';
  var ja = root.lang === 'ja';
  function paintTheme() {
    if (!themeBtn) return;
    var d = isDark();
    themeBtn.innerHTML = d ? SUN : MOON;
    themeBtn.setAttribute('aria-label', ja ? (d ? 'ライトモードにする' : 'ダークモードにする') : (d ? 'Switch to light theme' : 'Switch to dark theme'));
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', d ? '#131210' : '#E3E2DD');
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var next = isDark() ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('hanko-theme', next); } catch (e) {}
      paintTheme();
    });
    if (dark.addEventListener) dark.addEventListener('change', paintTheme);
    paintTheme();
  }

  // ---- English / 日本語 (home and /try) ---------------------------------
  var langBtn = document.querySelector('[data-lang-toggle]');
  if (langBtn) {
    if (ja) { langBtn.textContent = 'English'; langBtn.setAttribute('lang', 'en'); }
    langBtn.addEventListener('click', function () {
      var next = ja ? 'en' : 'ja';
      try { localStorage.setItem('hanko-lang', next); } catch (e) {}
      var url = location.pathname + '?lang=' + next + location.hash;
      location.replace(url);
    });
  }
})();
