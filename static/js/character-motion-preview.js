/* Bundled geometric placeholder with an optional local comparison renderer. */
(function () {
  let rendererModule;
  class CharacterMotionPreview {
    constructor(host, phase = "library") {
      this.host = host;
      this.phase = phase;
      this.disposed = false;
      this.abort = new AbortController();
      const figure = document.createElement("div");
      figure.className = "character-preview-figure";
      figure.setAttribute("aria-hidden", "true");
      // Independently drawn geometric mannequin; no third-party model or image.
      figure.innerHTML =
        '<svg viewBox="0 0 180 460" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="90" cy="39" rx="24" ry="31"/><path d="M78 68v15l-30 16-18 73-13 87 16 4 20-82 14-42-6 95 10 42-8 155 20 1 10-154 7 154 20-1-5-155 10-42-7-95 14 42 20 82 16-4-13-87-18-73-30-16V68M67 139l46 0M62 194h56M71 276l19-21 15 21M90 86v167M48 99l42 31 42-31M68 167h44M70 223h42M72 320h12M98 320h13M68 377h14M101 377h13M76 12v54M90 8v62M104 12v54M67 29h46M66 44h48M72 59h36"/><path d="M64 431l-5 17h28l-4-16M100 432l-3 16h28l-5-17"/></svg>';
      host.append(figure);
      host.classList.add("has-static-preview");
      this.figure = figure;
      if (!CharacterMotionPreview.referenceAssets) return;
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
      rendererModule ||= import(
        "./character-generation-renderer.js?v=20261029.1"
      );
      rendererModule
        .then((module) => {
          if (this.disposed) return;
          return module.createCharacterGenerationRenderer(canvas, {
            theme: dark() ? "dark" : "light",
            reduceMotion: matchMedia("(prefers-reduced-motion: reduce)")
              .matches,
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
    }
  }
  window.CharacterMotionPreview = CharacterMotionPreview;
})();
