/* Readable adaptation of the observed library controller in 209jfngjispvf.js.
 * Geometry, easing and gesture constants were recovered from the public bundle;
 * React/GSAP bindings are replaced by a scoped DOM lifecycle. No remote runtime.
 */
(function () {
  const tuning = Object.freeze({
    width: 246,
    height: 434,
    dragThreshold: 8,
    edgeResistance: 0.18,
    flingDurationMs: 180,
    flingVelocity: 0.18,
    settleDuration: 800,
    wheelSensitivity: 0.4,
    wheelSettleDelayMs: 140,
    wheelSmoothing: 180,
    entranceDuration: 680,
    entranceDelay: 100,
  });
  const clamp = (value, count) =>
    Math.min(Math.max(value, 0), Math.max(0, count - 1));
  const alpha = (distance) => 0.2 + (1 - Math.min(Math.abs(distance), 1)) * 0.8;
  const resist = (value, count) =>
    value < 0
      ? value * 0.18
      : value > count - 1
        ? count - 1 + (value - count + 1) * 0.18
        : value;
  const fling = (position, velocity, count) =>
    Math.round(
      clamp(
        clamp(position, count) +
          (Math.abs(velocity) >= 0.18 ? (-velocity * 180) / 246 : 0),
        count,
      ),
    );
  // Original cubic-bezier(.33,.68,0,1), including its Newton solver.
  function ease(value) {
    if (value <= 0 || value >= 1) return Math.max(0, Math.min(value, 1));
    let t = value;
    for (let n = 0; n < 8; n++) {
      const slope = (5.97 * t - 3.96) * t + 0.99;
      if (Math.abs(slope) < 1e-6) break;
      t -= (((1.99 * t - 1.98) * t + 0.99) * t - value) / slope;
    }
    t = Math.max(0, Math.min(t, 1));
    return ((0.04 * t - 1.08) * t + 2.04) * t;
  }
  if (typeof module !== "undefined" && module.exports)
    module.exports = { tuning, clamp, alpha, resist, fling, ease };
  if (typeof document === "undefined") return;
  class CharacterCarousel {
    constructor(viewport, track, { index = 0, onSelect }) {
      this.viewport = viewport;
      this.track = track;
      this.cards = [...track.children];
      this.onSelect = onSelect;
      this.active = clamp(index, this.cards.length);
      this.position = this.active;
      this.abort = new AbortController();
      this.reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      const bind = (name, fn, options = {}) =>
        viewport.addEventListener(name, fn, {
          signal: this.abort.signal,
          ...options,
        });
      bind("pointerdown", (e) => this.down(e));
      bind("pointermove", (e) => this.drag(e));
      for (const name of ["pointerup", "pointercancel", "lostpointercapture"])
        bind(name, (e) => this.up(e));
      bind(
        "click",
        (e) => {
          if (Date.now() < this.suppressClickUntil) {
            e.preventDefault();
            e.stopPropagation();
          }
        },
        { capture: true },
      );
      bind("dragstart", (e) => e.preventDefault());
      bind("wheel", (e) => this.wheel(e), { passive: false });
      bind("keydown", (e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          e.stopPropagation();
          this.moveBy(e.key === "ArrowLeft" ? -1 : 1);
        }
      });
      this.paint(this.position);
      this.select(this.active);
      if (!this.reduceMotion) {
        const entrance =
          viewport.clientWidth / 2 + 246 + 246 * this.active + 123;
        this.entrances = this.cards.map((card, i) =>
          card.animate(
            [{ translate: `${entrance}px 0` }, { translate: "0 0" }],
            {
              duration: 680,
              delay: i * 100,
              easing: "cubic-bezier(.33,.68,0,1)",
              fill: "backwards",
            },
          ),
        );
      }
    }
    paint(position) {
      this.position = position;
      this.track.style.transform = `translate3d(${-(246 * position + 123)}px,0,0)`;
      this.cards.forEach((card, i) => {
        card.style.opacity = alpha(i - position);
        card.style.zIndex = 100 - Math.round(10 * Math.abs(i - position));
      });
    }
    select(index) {
      this.active = index;
      this.viewport.dataset.atStart = String(index === 0);
      this.viewport.dataset.atEnd = String(index === this.cards.length - 1);
      this.cards.forEach((card, i) => {
        card.setAttribute("aria-current", String(i === index));
        card.setAttribute("aria-hidden", String(i !== index));
        card
          .querySelectorAll("button")
          .forEach((button) => (button.tabIndex = i === index ? 0 : -1));
      });
      this.onSelect(index);
    }
    cancelMotion() {
      cancelAnimationFrame(this.frame);
      this.frame = 0;
      this.entrances?.forEach((animation) => animation.cancel());
    }
    animateTo(target, duration = 800, linear = false) {
      this.cancelMotion();
      const start = this.position,
        at = performance.now();
      if (this.reduceMotion || Math.abs(start - target) < 0.001) {
        this.paint(target);
        return;
      }
      const step = (now) => {
        const t = Math.min(1, (now - at) / duration);
        this.paint(start + (target - start) * (linear ? t : ease(t)));
        if (t < 1) this.frame = requestAnimationFrame(step);
      };
      this.frame = requestAnimationFrame(step);
    }
    moveTo(index) {
      clearTimeout(this.wheelTimer);
      this.wheelTarget = null;
      const target = Math.round(clamp(index, this.cards.length));
      this.select(target);
      this.animateTo(target);
    }
    moveBy(amount) {
      this.moveTo(this.active + amount);
    }
    down(e) {
      if (e.button !== 0 || e.target.closest("button,a,input,select,textarea"))
        return;
      this.cancelMotion();
      clearTimeout(this.wheelTimer);
      this.wheelTarget = null;
      this.pointer = {
        id: e.pointerId,
        startX: e.clientX,
        start: this.position,
        lastX: e.clientX,
        at: performance.now(),
        velocity: 0,
        dragging: false,
        index: Number(
          e.target.closest("[data-carousel-index]")?.dataset.carouselIndex,
        ),
      };
      this.viewport.setPointerCapture(e.pointerId);
    }
    drag(e) {
      const p = this.pointer;
      if (!p || p.id !== e.pointerId) return;
      const scale =
        this.viewport.getBoundingClientRect().width / this.viewport.clientWidth;
      const dx = (e.clientX - p.startX) / scale;
      if (Math.abs(dx) > 8) {
        p.dragging = true;
        this.viewport.dataset.dragging = "true";
      }
      if (!p.dragging) return;
      const now = performance.now();
      p.velocity =
        0.72 * p.velocity +
        (0.28 * ((e.clientX - p.lastX) / scale)) / Math.max(8, now - p.at);
      p.lastX = e.clientX;
      p.at = now;
      this.paint(resist(p.start - dx / 246, this.cards.length));
    }
    up(e) {
      const p = this.pointer;
      if (!p || p.id !== e.pointerId) return;
      this.pointer = null;
      delete this.viewport.dataset.dragging;
      if (this.viewport.hasPointerCapture(e.pointerId))
        this.viewport.releasePointerCapture(e.pointerId);
      if (p.dragging) {
        const age = performance.now() - p.at,
          velocity =
            e.type === "pointerup" && age <= 120
              ? p.velocity * Math.max(0, 1 - age / 120)
              : 0;
        this.suppressClickUntil = Date.now() + 100;
        this.moveTo(fling(this.position, velocity, this.cards.length));
      } else this.moveTo(Number.isFinite(p.index) ? p.index : this.active);
    }
    wheel(e) {
      if (this.cards.length < 2) return;
      const delta =
        Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : -e.deltaY;
      if (!delta) return;
      e.preventDefault();
      const increment = Math.max(
        -1.5,
        Math.min(
          1.5,
          (delta *
            (e.deltaMode === 1
              ? 16
              : e.deltaMode === 2
                ? this.viewport.clientWidth
                : 1) *
            0.4) /
            172.2,
        ),
      );
      const from = this.wheelTarget ?? this.position,
        target = clamp(from + increment, this.cards.length);
      this.wheelTarget = target;
      this.wheelDirection =
        Math.sign(target - from) || this.wheelDirection || 0;
      this.animateTo(target, 180, true);
      clearTimeout(this.wheelTimer);
      this.wheelTimer = setTimeout(() => {
        const target =
          this.wheelDirection > 0
            ? Math.ceil(this.wheelTarget)
            : this.wheelDirection < 0
              ? Math.floor(this.wheelTarget)
              : Math.round(this.wheelTarget);
        this.moveTo(target);
      }, 140);
    }
    destroy() {
      this.abort.abort();
      this.cancelMotion();
      clearTimeout(this.wheelTimer);
      this.pointer = null;
    }
  }
  window.CharacterCarousel = CharacterCarousel;
})();
