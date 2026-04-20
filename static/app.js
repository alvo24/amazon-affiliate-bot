/* ============================================================
   Affiliate Bot — UI motion
   - Scroll reveals (IntersectionObserver)
   - Animated stat counters
   - Cursor-follow glow on primary buttons
   - Respects prefers-reduced-motion
   ============================================================ */

(function () {
  "use strict";

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Scroll reveals ---------------------------------------------------
  const revealTargets = document.querySelectorAll(".reveal, .reveal-stagger > *");
  if (!prefersReduced && "IntersectionObserver" in window && revealTargets.length) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealTargets.forEach((el, i) => {
      // Stagger children inside reveal-stagger containers
      if (el.parentElement && el.parentElement.classList.contains("reveal-stagger")) {
        const delay = Math.min(60 * i, 420);
        el.style.setProperty("--reveal-delay", delay + "ms");
      }
      io.observe(el);
    });
  } else {
    revealTargets.forEach((el) => el.classList.add("in-view"));
  }

  // ---- Animated stat counters -------------------------------------------
  const counters = document.querySelectorAll("[data-count]");
  if (!prefersReduced && counters.length) {
    const animate = (el) => {
      const target = parseFloat(el.dataset.count);
      if (isNaN(target)) return;
      const decimals = (el.dataset.decimals && parseInt(el.dataset.decimals, 10)) || 0;
      const suffix = el.dataset.suffix || "";
      const duration = 1100;
      const start = performance.now();
      const tick = (now) => {
        const p = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const value = target * eased;
        el.textContent = value.toFixed(decimals) + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };
    const co = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animate(entry.target);
            co.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.5 }
    );
    counters.forEach((c) => co.observe(c));
  }

  // ---- Cursor-follow glow on primary buttons ----------------------------
  if (!prefersReduced) {
    document.querySelectorAll(".btn-primary, .btn-glow").forEach((btn) => {
      btn.addEventListener("mousemove", (e) => {
        const r = btn.getBoundingClientRect();
        btn.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%");
        btn.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%");
      });
    });
  }

  // ---- Tilt card on hover (hero preview) --------------------------------
  if (!prefersReduced) {
    document.querySelectorAll("[data-tilt]").forEach((card) => {
      card.addEventListener("mousemove", (e) => {
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        card.style.setProperty("--tilt-x", (py * -6).toFixed(2) + "deg");
        card.style.setProperty("--tilt-y", (px * 6).toFixed(2) + "deg");
      });
      card.addEventListener("mouseleave", () => {
        card.style.setProperty("--tilt-x", "0deg");
        card.style.setProperty("--tilt-y", "0deg");
      });
    });
  }
})();
