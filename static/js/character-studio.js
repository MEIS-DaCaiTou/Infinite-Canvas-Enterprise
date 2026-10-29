/* Personal character UI. Canvas state is accessed only through the supplied adapter. */
(function () {
  const labels = {
    gender: {
      unspecified: "未设置",
      male: "男",
      female: "女",
      neutral: "中性",
      other: "其他",
    },
    age_group: {
      unspecified: "未设置",
      child: "儿童",
      teen: "少年",
      young: "青年",
      adult: "成年",
      middle: "中年",
      senior: "老年",
    },
    region: {
      unspecified: "未设置",
      east_asia: "东亚",
      europe: "欧美",
      middle_east: "中东",
      africa: "非洲",
      other: "其他",
      south_asia: "南亚",
      americas: "美洲",
    },
  };
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function image(url, name) {
    const img = element("img");
    img.src = url;
    img.alt = name;
    img.loading = "lazy";
    img.addEventListener("error", () => {
      img.hidden = true;
      img.parentElement.classList.add("image-unavailable");
    });
    return img;
  }
  class CharacterStudio {
    constructor(adapter) {
      this.adapter = adapter;
      this.rows = [];
      this.catalog = [];
      this.library = "personal";
      this.draft = null;
      this.dirty = false;
      this.busy = false;
      this.editing = false;
      this.dialog = element("dialog", "character-studio");
      this.dialog.setAttribute("aria-label", "角色造型室");
      this.dialog.innerHTML = `<button type="button" data-close aria-label="关闭角色造型室">×</button><div class="character-library-screen"></div><header class="character-editor-header" hidden><button type="button" data-back>‹ 返回角色库</button></header><p class="character-status" role="status" aria-live="polite" hidden></p><aside class="character-editor" aria-label="角色资料"></aside>`;
      document.body.append(this.dialog);
      this.editor = this.dialog.querySelector(".character-editor");
      this.status = this.dialog.querySelector(".character-status");
      this.gallery = new CharacterLibraryView(
        this.dialog.querySelector(".character-library-screen"),
        {
          onSelect: (row, source) => {
            if (!this.editing && !this.dirty) {
              this.library = source;
              this.focusRow(row);
            }
          },
          onCreate: (mode) => {
            if (!this.canSwitch()) return;
            this.creation.open(mode || "generate");
          },
          onEdit: () => {
            if (!this.draft || !this.canSwitch()) return;
            if (this.library === "official")
              this.draft = {
                ...structuredClone(this.draft),
                id: undefined,
                revision: undefined,
                name: this.draft.name + " · 副本",
              };
            this.setEditing(true);
            this.renderEditor();
          },
          onInsert: () => this.insert(),
          onArchive: (ids) => this.archiveSelected(ids),
        },
        labels,
      );
      this.grid = this.gallery.grid;
      this.creation = new CharacterCreationView(this);
      this.dialog
        .querySelector("[data-close]")
        .addEventListener("click", () => {
          if (!this.busy && !this.creation.working) this.dialog.close();
        });
      this.dialog.addEventListener("close", () => this.gallery.pause());
      this.dialog.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (
          this.busy ||
          this.editing ||
          !this.creation.root.hidden ||
          event.target.matches("input,select,textarea") ||
          event.ctrlKey ||
          event.metaKey ||
          event.altKey
        )
          return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          this.gallery.carousel?.moveBy(event.key === "ArrowLeft" ? -1 : 1);
        }
      });
      this.dialog.addEventListener("cancel", (event) => {
        if (this.busy || this.creation.working) event.preventDefault();
      });
      this.dialog.querySelector("[data-back]").addEventListener("click", () => {
        if (this.canSwitch()) {
          this.setEditing(false);
          this.renderCards();
        }
      });
      this.resize = () => {
        const scale = Math.min(
          1,
          (window.innerWidth - 32) / 1200,
          (window.innerHeight - 32) / 760,
        );
        this.dialog.style.setProperty(
          "--character-scale",
          Math.max(0.1, scale),
        );
      };
      window.addEventListener("resize", this.resize);
      this.resize();
      this.renderEditor();
    }
    options(select, key, filter = false) {
      if (filter)
        select.add(
          new Option(
            { gender: "性别", age_group: "年龄段", region: "文化区域" }[key],
            "",
          ),
        );
      for (const [value, label] of Object.entries(labels[key]))
        select.add(new Option(label, value));
    }
    message(text = "", error = false) {
      this.status.textContent = text;
      this.status.classList.toggle("is-error", error);
      this.status.hidden = !text;
    }
    setEditing(value) {
      this.editing = value;
      this.dialog.classList.toggle("is-editing", value);
      this.dialog.querySelector(".character-editor-header").hidden = !value;
      if (value) this.gallery.pause();
    }
    async request(url, options = {}) {
      const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
      });
      const value = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Object.assign(
          new Error(
            typeof value.detail === "string"
              ? value.detail
              : "操作失败，请稍后重试",
          ),
          { status: response.status },
        );
      return value;
    }
    async perform(action) {
      if (this.busy) return;
      this.busy = true;
      this.dialog.classList.add("is-busy");
      this.dialog.setAttribute("aria-busy", "true");
      for (const node of this.dialog.querySelectorAll(
        ".character-library-screen,.character-editor",
      ))
        node.inert = true;
      try {
        await action();
      } catch (error) {
        this.message(error.message, true);
      } finally {
        this.busy = false;
        this.dialog.classList.remove("is-busy");
        this.dialog.removeAttribute("aria-busy");
        for (const node of this.dialog.querySelectorAll("[inert]"))
          node.inert = false;
      }
    }
    async open() {
      if (!this.dialog.open) this.dialog.showModal();
      await this.load();
    }
    async load() {
      await this.perform(async () => {
        const result = await this.request("/enterprise/api/me/characters");
        this.creation.setOwner(result.owner_id);
        this.rows = result.characters;
        const catalog = await this.request(
          "/enterprise/api/me/characters/catalog",
        );
        this.catalog = catalog.characters;
        if (this.draft?.id && !this.dirty)
          this.draft = structuredClone(
            [...this.rows, ...this.catalog].find(
              (row) => row.id === this.draft.id,
            ) || null,
          );
        this.renderCards();
        if (!this.dirty) this.renderEditor();
        this.message();
        window.lucide?.createIcons();
        if (!this.creation.root.hidden) this.creation.render();
      });
    }
    canSwitch() {
      if (this.dirty) {
        this.message("当前编辑尚未保存，请先保存或放弃编辑。", true);
        return false;
      }
      return !this.busy;
    }
    newProfile() {
      if (!this.canSwitch()) return;
      this.draft = {
        name: "",
        description: "",
        gender: "unspecified",
        age_group: "unspecified",
        region: "unspecified",
        images: [],
        archived: false,
      };
      this.library = "personal";
      this.setEditing(true);
      this.renderEditor();
      this.message();
      this.editor.querySelector("[name=name]").focus();
    }
    focusRow(row) {
      if (!this.dirty) this.draft = row ? structuredClone(row) : null;
    }
    renderCards() {
      this.gallery.render(
        this.rows,
        this.catalog,
        this.editing ? undefined : this.draft?.id,
      );
    }
    renderEditor() {
      this.editor.replaceChildren();
      const row = this.draft;
      if (!row) {
        this.editor.append(
          element("p", "character-empty", "选择角色查看资料，或新建一个角色。"),
        );
        return;
      }
      const form = element("form");
      form.setAttribute("aria-label", "编辑角色资料");
      form.append(
        element(
          "h3",
          "",
          row.id ? (row.archived ? "已归档角色" : "角色资料") : "新建角色",
        ),
      );
      for (const [name, title, max] of [
        ["name", "角色名称", 80],
        ["description", "角色描述", 2000],
      ]) {
        const label = element("label", "", title),
          input = element(name === "description" ? "textarea" : "input");
        input.name = name;
        input.maxLength = max;
        input.value = row[name];
        input.required = name === "name";
        input.addEventListener("input", () => {
          row[name] = input.value;
          this.dirty = true;
        });
        label.append(input);
        form.append(label);
      }
      const attributes = element("div", "character-attributes");
      for (const [name, title] of [
        ["gender", "性别"],
        ["age_group", "年龄段"],
        ["region", "文化区域"],
      ]) {
        const label = element("label", "", title),
          select = element("select");
        select.name = name;
        this.options(select, name);
        select.value = row[name];
        select.addEventListener("change", () => {
          row[name] = select.value;
          this.dirty = true;
        });
        label.append(select);
        attributes.append(label);
      }
      form.append(
        attributes,
        element("label", "", "角色参考图（1—12张，首张作为封面）"),
      );
      const strip = element("div", "character-images");
      row.images.forEach((url, index) => {
        const box = element("div", "character-reference");
        box.append(image(url, `参考图 ${index + 1}`));
        const remove = element("button", "", "×");
        remove.type = "button";
        remove.setAttribute("aria-label", `移除参考图 ${index + 1}`);
        remove.addEventListener("click", () => {
          row.images.splice(index, 1);
          this.dirty = true;
          this.renderEditor();
        });
        box.append(remove);
        strip.append(box);
        const cover = element(
          "button",
          "character-set-cover",
          row.cover_url === url ? "封面" : "设为封面",
        );
        cover.type = "button";
        cover.addEventListener("click", () => {
          row.cover_url = url;
          this.dirty = true;
          this.renderEditor();
        });
        box.append(cover);
      });
      form.append(strip);
      if (row.unavailable_images)
        form.append(
          element(
            "p",
            "character-warning",
            `${row.unavailable_images} 张原参考图当前不可访问，请核对后重新选择。`,
          ),
        );
      const uploads = element("div", "character-actions");
      const upload = element("label", "character-upload", "＋ 上传图片"),
        input = element("input");
      input.type = "file";
      input.multiple = true;
      input.accept = ".png,.jpg,.jpeg,.webp,.gif";
      input.setAttribute("aria-label", "上传角色参考图");
      input.addEventListener("change", () => {
        const files = [...input.files];
        input.value = "";
        this.upload(files);
      });
      upload.append(input);
      uploads.append(upload);
      const selected = element("button", "", "从画布选中图片导入");
      selected.type = "button";
      selected.addEventListener("click", () => {
        const refs = this.adapter.selection().filter(Boolean);
        if (!refs.length) {
          this.message(
            "请先关闭此面板，在画布选择图片后重新打开；未保存编辑会保留。",
            true,
          );
          return;
        }
        this.appendImages(refs);
      });
      uploads.append(selected);
      form.append(uploads);
      const actions = element("div", "character-actions");
      const save = element(
        "button",
        "character-primary",
        row.archived ? "恢复角色" : "保存角色",
      );
      save.type = "submit";
      const insert = element("button", "", "添加到画布");
      insert.type = "button";
      insert.disabled = !row.id || row.archived || !row.images.length;
      insert.addEventListener("click", () => this.insert());
      const discard = element("button", "", "放弃编辑");
      discard.type = "button";
      discard.addEventListener("click", () => {
        this.draft = null;
        this.dirty = false;
        this.setEditing(false);
        this.renderEditor();
        this.renderCards();
        this.message();
      });
      actions.append(save, insert, discard);
      if (row.id && !row.archived) {
        const archive = element("button", "", "归档");
        archive.type = "button";
        archive.addEventListener("click", () => this.archive());
        actions.append(archive);
      }
      form.append(actions);
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        this.save();
      });
      this.editor.append(form);
    }
    appendImages(refs) {
      const images = [...new Set([...this.draft.images, ...refs])];
      if (images.length > 12) {
        this.message("每个角色最多12张参考图。", true);
        return;
      }
      this.draft.images = images;
      this.dirty = true;
      this.renderEditor();
      this.message();
    }
    async upload(files) {
      if (!files.length) return;
      if (
        this.draft.images.length + files.length > 12 ||
        files.some(
          (file) =>
            file.size > 50 * 1024 * 1024 ||
            !/\.(png|jpe?g|webp|gif)$/i.test(file.name),
        )
      ) {
        this.message(
          "请上传PNG/JPG/WebP/GIF图片，每张不超过50MB，合计最多12张。",
          true,
        );
        return;
      }
      await this.perform(async () => {
        for (let i = 0; i < files.length; i++) {
          this.message(`正在上传 ${i + 1}/${files.length}…`);
          const form = new FormData();
          form.append("files", files[i]);
          const result = await this.request("/api/ai/upload", {
            method: "POST",
            body: form,
          });
          this.appendImages(
            result.files
              .filter((file) => file.kind === "image")
              .map((file) => file.url),
          );
        }
        this.message("图片已上传，请保存角色资料。");
      });
    }
    payload(row = this.draft) {
      const data = Object.fromEntries(
        ["name", "description", "gender", "age_group", "region", "images"].map(
          (key) => [key, row[key]],
        ),
      );
      if (row.cover_url) data.cover_url = row.cover_url;
      if (row.id) data.expected_revision = row.revision;
      data.archived = false;
      return data;
    }
    async save() {
      await this.perform(async () => {
        const row = this.draft,
          data = this.payload(row);
        const saved = await this.request(
          "/enterprise/api/me/characters" + (row.id ? "/" + row.id : ""),
          {
            method: row.id ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          },
        );
        this.rows = [
          saved,
          ...this.rows.filter((item) => item.id !== saved.id),
        ];
        this.draft = structuredClone(saved);
        this.dirty = false;
        this.library = "personal";
        this.gallery.source = "personal";
        this.gallery.archived = false;
        this.gallery.selectedId = saved.id;
        this.setEditing(false);
        this.renderCards();
        this.renderEditor();
        this.message();
      });
    }
    async archive() {
      if (this.draft?.id) await this.archiveSelected([this.draft.id]);
    }
    async archiveSelected(ids) {
      if (!ids.length || !this.canSwitch()) return;
      await this.perform(async () => {
        try {
          for (const id of ids) {
            const row = this.rows.find((row) => row.id === id);
            if (!row) throw new Error("角色已变化，请重新打开后核对。");
            await this.request("/enterprise/api/me/characters/" + id, {
              method: "DELETE",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_revision: row.revision }),
            });
          }
          this.message(
            "角色已归档，可在“已归档角色”中恢复；原图和画布节点保留。",
          );
        } finally {
          this.rows = (
            await this.request("/enterprise/api/me/characters")
          ).characters;
          this.draft = null;
          this.dirty = false;
          this.gallery.picked.clear();
          this.setEditing(false);
          this.renderCards();
          this.renderEditor();
        }
      });
    }
    async insert() {
      if (this.dirty) {
        this.message("请先保存当前角色，再添加到画布。", true);
        return;
      }
      await this.perform(async () => {
        const rows = (
          await this.request(
            "/enterprise/api/me/characters" +
              (this.library === "official" ? "/catalog" : ""),
          )
        ).characters;
        const ids = [this.draft?.id];
        const chosen = ids.map((id) => rows.find((row) => row.id === id));
        if (
          chosen.some(
            (row) =>
              !row ||
              row.archived ||
              !row.images.length ||
              row.unavailable_images,
          )
        )
          throw new Error("角色或参考图不可用，请刷新后核对。");
        if (chosen.length === 1 && chosen[0].revision !== this.draft.revision)
          throw new Error("角色已在其他页面修改，请重新打开后核对。");
        for (const row of chosen) if (!(await this.adapter.insert(row))) return;
        this.dialog.close();
      });
    }
  }
  window.CharacterStudio = {
    mount(adapter) {
      const studio = new CharacterStudio(adapter);
      for (const button of document.querySelectorAll("[data-character-studio]"))
        button.addEventListener("click", () => studio.open());
      return studio;
    },
  };
})();
