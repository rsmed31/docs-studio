/* Diagram animation: arm figures, play them when scrolled into view, Pause / Replay buttons,
 * and a live "docs were rebuilt" notice when the page is served by studio.py. */
(function () {
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var figs = Array.prototype.slice.call(document.querySelectorAll("[data-pv]"));

  function play(fig) {
    fig.classList.remove("pv-run");
    void fig.offsetWidth;
    fig.classList.add("pv-run");
    var svg = fig.querySelector("svg");
    if (svg && svg.unpauseAnimations) { try { svg.setCurrentTime(0); svg.unpauseAnimations(); } catch (e) {} }
  }

  figs.forEach(function (fig) {
    var anim = fig.getAttribute("data-anim") || "none";
    if (anim === "none" || reduce) return;
    var bar = fig.querySelector(".dg-export");
    if (!bar && fig.tagName === "FIGURE") {
      bar = document.createElement("div"); bar.className = "dg-export"; fig.insertBefore(bar, fig.firstChild);
    }
    if (bar) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "dg-anim";
      var oneShot = anim === "reveal" || anim === "draw";
      b.textContent = oneShot ? "Replay" : "Pause";
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        if (oneShot) { play(fig); return; }
        var paused = fig.classList.toggle("pv-paused");
        var svg = fig.querySelector("svg");
        if (svg && svg.pauseAnimations) { try { paused ? svg.pauseAnimations() : svg.unpauseAnimations(); } catch (er) {} }
        b.textContent = paused ? "Play" : "Pause";
      });
      bar.insertBefore(b, bar.firstChild);
      /* exports must show the finished picture, not a frame of the animation */
      bar.addEventListener("click", function (e) {
        var t = e.target.closest("button"); if (!t || t === b) return;
        fig.classList.add("pv-noanim"); setTimeout(function () { fig.classList.remove("pv-noanim"); }, 400);
      }, true);
    }
    if (anim === "reveal" || anim === "draw") {
      fig.classList.add("pv-armed");
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) { if (en.isIntersecting) { play(fig); io.unobserve(fig); } });
        }, { threshold: 0.15 });
        io.observe(fig);
      } else play(fig);
    }
  });

  /* pages are hidden until opened: IntersectionObserver fires when a page is shown, so nothing else to do */

  /* live reload notice (only when served by studio.py) */
  if (location.protocol === "http:" && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)) {
    var known = null;
    function poll() {
      fetch("/api/version", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
        if (!j) return;
        if (known === null) known = j.build;
        else if (j.build !== known) {
          known = j.build;
          var t = document.getElementById("toast");
          if (t) { t.innerHTML = 'Docs were rebuilt. <a href="" onclick="location.reload();return false">Reload</a>'; t.hidden = false; }
        }
      }).catch(function () {});
    }
    poll(); setInterval(poll, 8000);
  }
})();
