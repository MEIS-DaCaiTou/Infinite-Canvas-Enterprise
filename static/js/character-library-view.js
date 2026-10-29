/* Library screen recovered from the rendered page and its public production bundle.
 * Only presentation/selection lives here. Account data and canvas actions stay in
 * CharacterStudio and its existing adapters; no Liblib API or analytics executes.
 */
(function () {
  const createId = "character-studio-create-slot";
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const icon = (name) => {
    const node = el("i");
    node.dataset.lucide = name;
    return node;
  };
  function button(label, name, cls = "") {
    const node = el("button", cls);
    node.type = "button";
    node.setAttribute("aria-label", label);
    if (name) node.append(icon(name));
    return node;
  }
  function picture(url, label) {
    const node = el("img");
    node.src = url;
    node.alt = label;
    node.draggable = false;
    node.decoding = "async";
    return node;
  }
  class CharacterLibraryView {
    constructor(root, callbacks, labels) {
      this.root = root;
      this.callbacks = callbacks;
      this.labels = labels;
      this.filters = {};
      this.source = "personal";
      this.mode = "carousel";
      this.selectedId = createId;
      this.picked = new Set();
      root.innerHTML = `<header class="character-header"><nav aria-label="角色库"><button type="button" data-library="personal" aria-pressed="true">我的角色库</button><span class="character-tab-divider"></span><button type="button" data-library="official" aria-pressed="false">官方角色库</button></nav></header>
                <div class="character-toolbar"><div class="character-filters"></div><div class="character-view-switch"><button type="button" data-multi aria-label="多选"><i data-lucide="list-checks"></i></button><div class="character-view-segment"><button type="button" data-view="carousel" aria-label="列表模式" aria-pressed="true"><i data-lucide="panels-top-left"></i></button><span></span><button type="button" data-view="grid" aria-label="宫格模式" aria-pressed="false"><i data-lucide="grid-2x2"></i></button></div></div></div>
                <div class="character-library-body"><section class="character-grid" aria-label="角色列表"></section></div><footer class="character-footer"><div class="character-create-wrapper"><button type="button" data-new aria-expanded="false"><i data-lucide="user-round-plus"></i><span>创建新角色</span></button><div class="character-create-menu" role="menu" hidden><button type="button" role="menuitem" data-create-profile><i data-lucide="user-round-plus"></i>生成新角色</button><button type="button" role="menuitem" data-import-profile aria-haspopup="menu" aria-expanded="false"><i data-lucide="image-up"></i>导入已有角色<i data-lucide="chevron-right"></i></button><div class="character-import-menu" role="menu" hidden><button type="button" role="menuitem" data-import-local>从本地导入</button><button type="button" role="menuitem" data-import-assets>从我的资产导入</button></div></div></div><div class="character-footer-actions"><button type="button" data-insert><i data-lucide="square-plus"></i>添加到画布</button><button type="button" data-edit class="character-primary"><i data-lucide="smile-plus"></i>编辑角色</button></div><button type="button" data-archive-view aria-label="已归档角色"><i data-lucide="archive"></i></button><div class="character-multi-footer" hidden><button type="button" data-select-all role="checkbox" aria-checked="false">全选</button><button type="button" data-archive-selected>归档角色</button></div></footer>`;
      this.grid = root.querySelector(".character-grid");
      this.body = root.querySelector(".character-library-body");
      this.footer = root.querySelector(".character-footer");
      const filters = root.querySelector(".character-filters");
      for (const [key, label] of [
        ["gender", "性别"],
        ["age_group", "年龄段"],
        ["region", "文化区域"],
      ]) {
        const details = el("details", "character-filter");
        details.dataset.filter = key;
        const summary = el("summary");
        summary.setAttribute("aria-label", label);
        summary.append(el("span", "", label), icon("chevron-down"));
        const menu = el("div", "character-filter-menu");
        for (const [value, text] of Object.entries(labels[key])) {
          if (
            value === "unspecified" ||
            (key === "gender" && value === "other") ||
            (key === "age_group" && value === "adult") ||
            (key === "region" && ["south_asia", "americas"].includes(value))
          )
            continue;
          const row = el("label"),
            check = el("input");
          check.type = "checkbox";
          check.value = value;
          check.setAttribute("aria-label", text);
          row.append(check, el("span", "", text), icon("check"));
          menu.append(row);
          check.addEventListener("change", () => {
            const values = [...menu.querySelectorAll("input:checked")].map(
              (input) => input.value,
            );
            this.filters[key] = values;
            summary.replaceChildren();
            if (values.length) {
              const clear = button("清除" + label, "x");
              clear.dataset.clearFilter = key;
              clear.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                menu
                  .querySelectorAll("input")
                  .forEach((input) => (input.checked = false));
                this.filters[key] = [];
                summary.replaceChildren(
                  el("span", "", label),
                  icon("chevron-down"),
                );
                details.classList.remove("has-selection");
                this.renderCards();
                window.lucide?.createIcons();
              });
              summary.append(
                clear,
                el(
                  "span",
                  "",
                  label +
                    " · " +
                    values.map((value) => labels[key][value]).join("、"),
                ),
              );
            } else summary.append(el("span", "", label), icon("chevron-down"));
            details.classList.toggle("has-selection", Boolean(values.length));
            this.renderCards();
            window.lucide?.createIcons();
          });
        }
        details.append(summary, menu);
        filters.append(details);
        details.addEventListener("toggle", () => {
          if (details.open)
            root.querySelectorAll(".character-filter").forEach((item) => {
              if (item !== details) item.open = false;
            });
        });
      }
      const searchButton = button(
          "搜索角色名称或描述",
          "search",
          "character-search-button",
        ),
        searchLabel = el("label", "character-search"),
        search = el("input");
      search.type = "search";
      search.placeholder = "搜索角色名称或描述";
      search.setAttribute("aria-label", "搜索角色");
      searchLabel.append(icon("search"), search);
      searchLabel.hidden = true;
      filters.append(searchButton, searchLabel);
      this.search = search;
      searchButton.addEventListener("click", () => {
        searchButton.hidden = true;
        searchLabel.hidden = false;
        search.focus();
      });
      search.addEventListener("blur", () => {
        if (!search.value) {
          searchButton.hidden = false;
          searchLabel.hidden = true;
        }
      });
      search.addEventListener("input", () => this.renderCards());
      root
        .querySelectorAll("[data-library]")
        .forEach((item) =>
          item.addEventListener("click", () =>
            this.goLibrary(item.dataset.library),
          ),
        );
      root.querySelectorAll("[data-view]").forEach((item) =>
        item.addEventListener("click", () => {
          this.mode = item.dataset.view;
          if (this.mode === "carousel") this.multiple = false;
          this.renderCards();
        }),
      );
      root.querySelector("[data-multi]").addEventListener("click", () => {
        this.multiple = !this.multiple;
        if (this.multiple) {
          this.previousMode = this.mode;
          this.mode = "grid";
          const selected = this.items.find((row) => row.id === this.selectedId);
          this.picked = new Set(
            selected?.source === "personal" ? [selected.id] : [],
          );
        } else {
          this.mode = this.previousMode || this.mode;
          this.picked.clear();
        }
        this.renderCards();
      });
      const menu = root.querySelector(".character-create-menu"),
        trigger = root.querySelector("[data-new]");
      trigger.addEventListener("click", () => {
        root.querySelector(".character-import-menu").hidden = true;
        root
          .querySelector("[data-import-profile]")
          .setAttribute("aria-expanded", "false");
        menu.hidden = !menu.hidden;
        trigger.setAttribute("aria-expanded", String(!menu.hidden));
      });
      root
        .querySelector("[data-create-profile]")
        .addEventListener("click", () => {
          menu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
          callbacks.onCreate();
        });
      root
        .querySelector("[data-import-profile]")
        .addEventListener("click", () => {
          const submenu = root.querySelector(".character-import-menu");
          submenu.hidden = false;
          root
            .querySelector("[data-import-profile]")
            .setAttribute("aria-expanded", String(!submenu.hidden));
        });
      const submenu = root.querySelector(".character-import-menu");
      const importTrigger = root.querySelector("[data-import-profile]");
      const showImport = () => {
        submenu.hidden = false;
        importTrigger.setAttribute("aria-expanded", "true");
      };
      importTrigger.addEventListener("pointerenter", showImport);
      importTrigger.addEventListener("focus", showImport);
      for (const [selector, mode] of [
        ["[data-import-local]", "import"],
        ["[data-import-assets]", "assets"],
      ])
        root.querySelector(selector).onclick = () => {
          menu.hidden = true;
          submenu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
          callbacks.onCreate(mode);
        };
      root.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(".character-create-wrapper")) {
          menu.hidden = true;
          submenu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
        }
      });
      root.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !menu.hidden) {
          event.preventDefault();
          event.stopPropagation();
          menu.hidden = true;
          submenu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
          trigger.focus();
        }
      });
      root
        .querySelector("[data-edit]")
        .addEventListener("click", () => callbacks.onEdit());
      root
        .querySelector("[data-insert]")
        .addEventListener("click", () => callbacks.onInsert());
      root
        .querySelector("[data-archive-view]")
        .addEventListener("click", () => {
          this.archived = !this.archived;
          this.multiple = false;
          this.selectedId = null;
          this.source = "personal";
          this.renderCards();
        });
      root.querySelector("[data-select-all]").addEventListener("click", () => {
        const ids = this.filtered
          .filter((row) => row.source === "personal")
          .map((row) => row.id);
        this.picked = ids.every((id) => this.picked.has(id))
          ? new Set()
          : new Set(ids);
        this.renderCards();
      });
      root
        .querySelector("[data-archive-selected]")
        .addEventListener("click", () => callbacks.onArchive([...this.picked]));
      root.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(".character-filter"))
          root
            .querySelectorAll("details")
            .forEach((details) => (details.open = false));
        if (!event.target.closest(".character-create-wrapper")) {
          menu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
        }
      });
      this.root.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          if (this.detail) {
            event.preventDefault();
            this.closeAssets();
          } else if (
            [...root.querySelectorAll("details")].some((node) => node.open) ||
            !menu.hidden
          ) {
            event.preventDefault();
            root
              .querySelectorAll("details")
              .forEach((node) => (node.open = false));
            menu.hidden = true;
            trigger.setAttribute("aria-expanded", "false");
          }
        }
      });
    }
    render(rows, catalog, selectedId) {
      this.items = [
        ...rows.map((row) => ({ ...row, source: "personal" })),
        ...catalog.map((row) => ({ ...row, source: "official" })),
      ];
      if (selectedId && selectedId !== this.lastExternalSelection) {
        this.selectedId = selectedId;
        this.lastExternalSelection = selectedId;
      }
      this.renderCards();
    }
    goLibrary(source) {
      if (this.multiple && source === "official") return;
      this.source = source;
      this.archived = false;
      if (this.mode === "grid") {
        const section = this.root.querySelector(
          "[data-library-section=" + source + "]",
        );
        if (section)
          this.grid.scrollTo({ top: section.offsetTop, behavior: "smooth" });
        this.syncTabs();
        return;
      }
      const index = this.displayed.findIndex((row) => row.source === source);
      if (index >= 0) this.carousel?.moveTo(index);
      else {
        this.selectedId = source === "personal" ? createId : null;
        this.renderCards();
      }
    }
    syncTabs() {
      this.root.querySelectorAll("[data-library]").forEach((node) => {
        node.setAttribute(
          "aria-pressed",
          String(node.dataset.library === this.source),
        );
        node.disabled = Boolean(
          this.multiple && node.dataset.library === "official",
        );
      });
    }
    choose(row) {
      this.selectedId = row.id;
      this.source = row.source;
      this.syncTabs();
      this.caption && (this.caption.textContent = row.name);
      this.grid.querySelectorAll(".character-card-select").forEach((button) => {
        const id = button.closest("[data-character-id]").dataset.characterId;
        button.setAttribute(
          "aria-pressed",
          String(this.multiple ? this.picked.has(id) : id === row.id),
        );
      });
      if (row.id === createId && !this.motion) {
        const host = this.grid.querySelector(".character-create-slot");
        if (host) this.motion = new CharacterMotionPreview(host);
      } else if (row.id !== createId) {
        this.motion?.destroy();
        this.motion = null;
      }
      this.callbacks.onSelect(row.id === createId ? null : row, row.source);
      this.syncFooter();
    }
    syncFooter() {
      const row = this.items.find((row) => row.id === this.selectedId),
        count = this.picked.size;
      this.root.classList.toggle("is-multiple", Boolean(this.multiple));
      this.footer.classList.toggle("is-create-slot", !row);
      this.root.querySelector("[data-edit]").disabled = !row;
      this.root.querySelector("[data-insert]").disabled =
        !row || row.archived || !row.images.length;
      this.root.querySelector(".character-footer-actions").hidden = Boolean(
        !row || this.multiple,
      );
      this.root.querySelector(".character-create-wrapper").hidden = Boolean(
        this.multiple,
      );
      this.root.querySelector("[data-archive-view]").hidden = Boolean(
        this.multiple,
      );
      this.root
        .querySelector("[data-archive-view]")
        .setAttribute("aria-pressed", String(Boolean(this.archived)));
      this.root.querySelector(".character-multi-footer").hidden =
        !this.multiple;
      const multi = this.root.querySelector("[data-multi]");
      multi.setAttribute("aria-label", this.multiple ? "退出多选" : "多选");
      multi.classList.toggle("is-active", Boolean(this.multiple));
      multi.replaceChildren(icon(this.multiple ? "x" : "list-checks"));
      if (this.multiple) multi.append(document.createTextNode("退出多选"));
      const ids = this.filtered
          .filter((row) => row.source === "personal")
          .map((row) => row.id),
        all = ids.length > 0 && ids.every((id) => this.picked.has(id));
      const selectAll = this.root.querySelector("[data-select-all]");
      selectAll.textContent = count ? "已选 " + count + " 个角色" : "全选";
      selectAll.setAttribute(
        "aria-checked",
        all ? "true" : count ? "mixed" : "false",
      );
      this.root.querySelector("[data-archive-selected]").disabled = !count;
      this.root
        .querySelectorAll("[data-view]")
        .forEach((node) =>
          node.setAttribute(
            "aria-pressed",
            String(node.dataset.view === this.mode),
          ),
        );
      window.lucide?.createIcons();
    }
    portrait(row, grid = false) {
      const article = el("article", "character-card");
      article.dataset.characterId = row.id;
      const cover = el("div", "character-cover");
      if (row.cover_url || row.images[0])
        cover.append(picture(row.cover_url || row.images[0], row.name));
      else cover.classList.add("image-unavailable");
      const choose = button(
        "查看角色：" + row.name,
        null,
        "character-card-select",
      );
      choose.setAttribute(
        "aria-pressed",
        String(
          this.multiple ? this.picked.has(row.id) : row.id === this.selectedId,
        ),
      );
      choose.disabled = Boolean(this.multiple && row.source === "official");
      choose.addEventListener("click", () => {
        if (this.multiple) {
          this.picked.has(row.id)
            ? this.picked.delete(row.id)
            : this.picked.add(row.id);
          this.renderCards();
        } else this.choose(row);
      });
      article.append(choose, cover);
      const assets = button("查看角色资产", "images", "character-view-assets");
      assets.append(el("span", "", "查看角色资产"));
      assets.addEventListener("click", () => this.showAssets(row));
      cover.append(assets);
      if (grid) {
        const label = el("div", "character-card-text", row.name);
        article.append(label);
      }
      if (this.multiple) {
        article.classList.add("is-multi-card");
        if (this.picked.has(row.id)) article.classList.add("is-picked");
        if (row.source === "official") article.classList.add("is-disabled");
      }
      return article;
    }
    renderCards() {
      this.closeAssets();
      this.motion?.destroy();
      this.motion = null;
      this.carousel?.destroy();
      this.carousel = null;
      this.grid.replaceChildren();
      const search = this.search.value.trim().toLowerCase();
      this.filtered = this.items.filter(
        (row) =>
          Boolean(row.archived) === Boolean(this.archived) &&
          (!this.archived || row.source === "personal") &&
          `${row.name} ${row.description}`.toLowerCase().includes(search) &&
          Object.entries(this.filters).every(
            ([key, values]) => !values.length || values.includes(row[key]),
          ),
      );
      this.picked = new Set(
        [...this.picked].filter((id) =>
          this.filtered.some(
            (row) => row.id === id && row.source === "personal",
          ),
        ),
      );
      this.grid.classList.toggle("is-grid", this.mode === "grid");
      this.syncTabs();
      if (this.mode === "grid") {
        for (const [source, title] of [
          ["personal", this.archived ? "已归档角色" : "我的角色库"],
          ["official", "官方角色库"],
        ]) {
          if (this.archived && source === "official") continue;
          const section = el("section", "character-grid-section");
          section.dataset.librarySection = source;
          section.append(el("h2", "", title));
          const cards = el("div", "character-grid-cards");
          this.filtered
            .filter((row) => row.source === source)
            .forEach((row) => cards.append(this.portrait(row, true)));
          if (!cards.children.length)
            cards.append(
              el(
                "p",
                "character-empty",
                source === "official" ? "暂无官方角色" : "暂无角色",
              ),
            );
          section.append(cards);
          this.grid.append(section);
        }
        const selected =
          this.filtered.find((row) => row.id === this.selectedId) ||
          this.filtered.find((row) => row.source === this.source);
        if (selected) this.choose(selected);
        else {
          this.selectedId = null;
          this.callbacks.onSelect(null, this.source);
        }
        this.syncFooter();
        return;
      }
      const hasFilter =
        search || Object.values(this.filters).some((values) => values.length);
      this.displayed =
        hasFilter || this.archived
          ? [...this.filtered]
          : [
              {
                id: createId,
                name: "创建新角色",
                source: "personal",
                images: [],
              },
              ...this.filtered,
            ];
      if (
        this.source === "official" &&
        !this.filtered.some((row) => row.source === "official")
      )
        this.displayed = [];
      if (!this.displayed.length) {
        this.selectedId = null;
        this.grid.append(
          el(
            "p",
            "character-empty",
            hasFilter
              ? "没有符合条件的角色"
              : this.archived
                ? "暂无已归档角色"
                : "暂无官方角色",
          ),
        );
        this.callbacks.onSelect(null, this.source);
        this.syncFooter();
        return;
      }
      const viewport = el("div", "character-carousel"),
        track = el("div", "character-carousel-track");
      viewport.tabIndex = 0;
      viewport.setAttribute("role", "group");
      viewport.setAttribute("aria-label", "角色展示台");
      viewport.append(track);
      this.displayed.forEach((row, index) => {
        const card =
          row.id === createId
            ? el("div", "character-card character-create-slot")
            : this.portrait(row);
        card.dataset.carouselIndex = index;
        card.setAttribute("role", "group");
        card.setAttribute("aria-label", row.name);
        if (row.id === createId) {
          const create = button(
            "创建新角色",
            "user-round-plus",
            "character-create-silhouette",
          );
          create.addEventListener("click", () => this.callbacks.onCreate());
          card.append(create);
        }
        // The carousel owns pointer selection; its portraits are not buttons.
        card.querySelector(".character-card-select")?.remove();
        track.append(card);
      });
      const range = el("input", "character-range");
      range.type = "range";
      range.min = 0;
      range.max = this.displayed.length - 1;
      range.step = 1;
      range.setAttribute("aria-label", "角色列表");
      const previous = button(
          "上一个角色",
          "chevron-left",
          "character-arrow character-previous",
        ),
        next = button(
          "下一个角色",
          "chevron-right",
          "character-arrow character-next",
        );
      previous.addEventListener("click", () => this.carousel.moveBy(-1));
      next.addEventListener("click", () => this.carousel.moveBy(1));
      range.addEventListener("input", () =>
        this.carousel.moveTo(Number(range.value)),
      );
      this.caption = el("div", "character-caption");
      this.grid.append(viewport, previous, next, this.caption, range);
      const index = Math.max(
        0,
        this.displayed.findIndex((row) => row.id === this.selectedId),
      );
      this.carousel = new CharacterCarousel(viewport, track, {
        index,
        onSelect: (index) => {
          range.value = index;
          range.setAttribute("aria-valuetext", this.displayed[index].name);
          previous.disabled = index === 0;
          next.disabled = index === this.displayed.length - 1;
          this.choose(this.displayed[index]);
        },
      });
      if (this.displayed.length < 2) {
        previous.hidden = next.hidden = range.hidden = true;
      }
      this.syncFooter();
    }
    showAssets(row) {
      this.closeAssets();
      this.detail = el("section", "character-assets-detail");
      this.detail.setAttribute("aria-label", row.name + " · 角色资产详情");
      this.detail.setAttribute("role", "region");
      this.root.classList.add("has-asset-detail");
      const dismiss = button("关闭角色资产", null, "character-assets-dismiss");
      dismiss.addEventListener("click", () => this.closeAssets());
      const cards = el("div", "character-assets-cards");
      row.images.forEach((url, index) => {
        const card = button(
          "预览参考图 " + (index + 1),
          null,
          "character-asset-image",
        );
        card.append(
          picture(url, row.asset_labels?.[index] || "参考图 " + (index + 1)),
        );
        card.addEventListener("click", () => {
          const preview = el("div", "character-asset-preview");
          const close = button("关闭图片预览", "x");
          preview.append(
            close,
            picture(url, row.asset_labels?.[index] || row.name),
          );
          close.addEventListener("click", () => preview.remove());
          this.detail.append(preview);
        });
        cards.append(card);
      });
      this.detail.append(
        dismiss,
        cards,
        el("div", "character-assets-name", row.name),
      );
      this.body.append(this.detail);
      this.choose(row);
      window.lucide?.createIcons();
    }
    closeAssets() {
      this.detail?.remove();
      this.detail = null;
      this.root.classList.remove("has-asset-detail");
    }
    pause() {
      this.carousel?.cancelMotion();
      this.motion?.destroy();
      this.motion = null;
      this.closeAssets();
    }
  }
  window.CharacterLibraryView = CharacterLibraryView;
})();
