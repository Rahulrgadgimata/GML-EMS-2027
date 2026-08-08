/* =============================================================================
   GM League Season 4 — motion layer

   Progressive enhancement only. `has-js` is what arms the CSS that hides
   revealable elements, so with JavaScript off (or if this file fails to load)
   the page renders fully visible and static. Everything also stands down when
   the visitor asks for reduced motion.

   Because hiding content is only safe if something is guaranteed to un-hide it,
   there are three layers of protection:
     1. a readyState guard, so init runs even if the DOM finished parsing first
     2. a try/catch that reveals everything if init throws
     3. a watchdog that reveals everything if the observer never reports back
   ========================================================================== */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var observerReported = false;

  if (!reduceMotion) root.classList.add("has-js");

  function revealAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-reveal]"), function (el) {
      el.classList.add("is-visible");
    });
  }

  /* A deferred script can run either before or after DOMContentLoaded depending
     on cache state, so never assume the event is still coming. */
  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function init() {
    /* ---------------------------------------------------- header elevation */
    var header = document.querySelector(".site-header");
    if (header) {
      var onScroll = function () {
        header.classList.toggle("is-stuck", window.scrollY > 12);
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll();
    }

    if (reduceMotion) return;

    /* ------------------------------------------------- reveal on scroll --- */
    var revealables = document.querySelectorAll("[data-reveal]");

    if (!("IntersectionObserver" in window)) {
      revealAll();
      observerReported = true;
    } else {
      /* Stagger children of a [data-stagger] container so grids cascade in.
         Done before observing so the delay is set when the class lands. */
      Array.prototype.forEach.call(document.querySelectorAll("[data-stagger]"), function (group) {
        Array.prototype.forEach.call(group.children, function (child, index) {
          child.style.setProperty("--reveal-delay", Math.min(index * 65, 480) + "ms");
        });
      });

      var observer = new IntersectionObserver(
        function (entries) {
          observerReported = true;
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          });
        },
        { rootMargin: "0px 0px -6% 0px", threshold: 0.05 }
      );

      Array.prototype.forEach.call(revealables, function (el) {
        observer.observe(el);
      });
    }

    /* -------------------------------------------------- counting statistics */
    Array.prototype.forEach.call(document.querySelectorAll("[data-count-to]"), function (el) {
      if (!("IntersectionObserver" in window)) return;
      var counter = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            countUp(entry.target);
            counter.unobserve(entry.target);
          });
        },
        { threshold: 0.4 }
      );
      counter.observe(el);
    });

    /* --------------------------------------- smooth in-page anchor scrolling */
    Array.prototype.forEach.call(document.querySelectorAll('a[href*="#"]'), function (link) {
      link.addEventListener("click", function (event) {
        var hash = link.getAttribute("href").split("#")[1];
        if (!hash) return;
        var target = document.getElementById(hash);
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        history.replaceState(null, "", "#" + hash);
      });
    });

    /* ------------------------------------------- flash messages slide in --- */
    Array.prototype.forEach.call(document.querySelectorAll(".flash"), function (flash, index) {
      flash.style.setProperty("--reveal-delay", index * 90 + "ms");
      flash.classList.add("flash--enter");
    });
  }

  function countUp(el) {
    var target = parseInt(el.getAttribute("data-count-to"), 10);
    if (!target || target < 0) return;
    var duration = 900;
    var started = null;

    function frame(now) {
      if (started === null) started = now;
      var progress = Math.min((now - started) / duration, 1);
      // easeOutCubic keeps the last few numbers from feeling abrupt
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased).toLocaleString("en-IN");
      if (progress < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  ready(function () {
    try {
      init();
    } catch (error) {
      // Never let a motion bug leave the page blank.
      revealAll();
      if (window.console) console.error("league.js init failed:", error);
    }
  });

  /* Watchdog: an IntersectionObserver always calls back shortly after observe(),
     even for off-screen targets. If it never does, something is wrong with the
     environment — show everything rather than serve an invisible page. */
  window.setTimeout(function () {
    if (!observerReported && !reduceMotion) revealAll();
  }, 2000);
})();
