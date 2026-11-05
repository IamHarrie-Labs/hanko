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
})();
