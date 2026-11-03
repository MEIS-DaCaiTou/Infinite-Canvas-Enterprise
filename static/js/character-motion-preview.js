/* The originally previewed Liblib model and renderer are bundled together. */
(function () {
  let rendererModule;
  function loadRenderer() {
    return rendererModule ||= import('../vendor/liblib-character-motion/renderer.js?v=20261029.1')
      .catch(error => { rendererModule = undefined; throw error; });
  }
  class CharacterMotionPreview {
    constructor(host, phase = "library", rendererLoader = loadRenderer) {
      this.host = host;
      this.phase = phase;
      this.disposed = false;
      this.abort = new AbortController();
      const figure = document.createElement("div");
      figure.className = "character-preview-figure";
      figure.setAttribute("aria-hidden", "true");
      const fallback = document.createElement('span');
      fallback.textContent = '正在加载人体预览…';
      figure.append(fallback);
      host.append(figure);
      host.classList.add("has-static-preview");
      this.figure = figure;
      this.fallback = fallback;
      const canvas = document.createElement("canvas");
      canvas.className = "character-motion-canvas";
      canvas.setAttribute("aria-hidden", "true");
      host.append(canvas);
      this.canvas = canvas;
      const dark = () =>
        document.documentElement.matches(".theme-dark,.studio-theme-dark");
      this.theme = () => this.renderer?.setTheme(dark() ? "dark" : "light");
      window.addEventListener("studio-theme-change", this.theme, {
        signal: this.abort.signal,
      });
      window.addEventListener("storage", this.theme, {
        signal: this.abort.signal,
      });
      this.observer = new MutationObserver(this.theme);
      this.observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class"],
      });
      host.addEventListener(
        "pointermove",
        (event) => {
          const r = host.getBoundingClientRect();
          this.renderer?.setPointer(
            ((event.clientX - r.left) / r.width) * 2 - 1,
            1 - ((event.clientY - r.top) / r.height) * 2,
            true,
          );
        },
        { signal: this.abort.signal },
      );
      host.addEventListener(
        "pointerleave",
        () => this.renderer?.setPointer(0, 0, false),
        { signal: this.abort.signal },
      );
      rendererLoader()
        .then((module) => {
          if (this.disposed) return;
          return module.createCharacterGenerationRenderer(canvas, {
            theme: dark() ? "dark" : "light",
            reduceMotion: matchMedia("(prefers-reduced-motion: reduce)")
              .matches,
            signal: this.abort.signal,
            onUnavailable: () => {
              host.classList.remove('has-motion-preview');
              fallback.textContent = '人体预览暂不可用';
            },
          });
        })
        .then((renderer) => {
          if (!renderer) return;
          if (this.disposed) {
            renderer.dispose();
            return;
          }
          this.renderer = renderer;
          renderer.setPhase(this.phase);
          this.theme();
          host.classList.add("has-motion-preview");
        })
        .catch((error) => {
          if (!this.disposed) {
            host.classList.add("motion-preview-unavailable");
            fallback.textContent = '人体预览暂不可用';
            host.dataset.previewError = String(error.message || error);
            host.setAttribute("title", "动态预览暂不可用，仍可创建角色资料。");
            console.warn("Character motion preview unavailable:", error);
          }
        });
    }
    setPhase(phase) {
      if (this.phase === phase) return;
      this.phase = phase;
      this.renderer?.setPhase(phase);
    }
    destroy() {
      if (this.disposed) return;
      this.disposed = true;
      this.abort.abort();
      this.observer?.disconnect();
      this.renderer?.dispose();
      this.canvas?.remove();
      this.figure.remove();
      this.host.classList.remove('has-static-preview', 'has-motion-preview', 'motion-preview-unavailable');
    }
  }
  window.CharacterMotionPreview = CharacterMotionPreview;
})();
