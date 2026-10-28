/* Reference screen geometry comes from sh/s9 in the inspected public bundle.
 * All uploads, generation and media selection use this project's owned APIs. */
(function () {
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const picture = (url) => {
    const img = el("img");
    img.src = url;
    img.alt = "角色图片";
    return img;
  };
  class CharacterCreationView {
    constructor(studio) {
      this.studio = studio;
      this.root = el("section", "character-creation-screen");
      this.root.hidden = true;
      this.root.setAttribute("aria-label", "创建角色");
      studio.dialog.append(this.root);
      this.task = new CharacterCreationTask(
        (...args) => studio.request(...args),
        sessionStorage,
      );
      this.abort = new AbortController();
      studio.dialog.addEventListener("close", () => this.pause());
      studio.dialog.addEventListener("keydown", (event) => {
        if (!this.root.hidden && event.key === "Escape") {
          event.preventDefault();
          const menu = this.root.querySelector(
            ".character-generator-reference-menu:not([hidden])",
          );
          const settings = this.root.querySelector("details[open]");
          if (menu) {
            menu.hidden = true;
            this.root
              .querySelector('[aria-label="选择参考图"]')
              ?.setAttribute("aria-expanded", "false");
            return;
          }
          if (settings) {
            settings.open = false;
            return;
          }
          this.back();
        }
      });
      this.root.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(".character-generator-reference-control")) {
          const menu = this.root.querySelector(
            ".character-generator-reference-menu",
          );
          if (menu) menu.hidden = true;
          this.root
            .querySelector('[aria-label="选择参考图"]')
            ?.setAttribute("aria-expanded", "false");
        }
        if (!event.target.closest(".character-generator-settings")) {
          const settings = this.root.querySelector("details[open]");
          if (settings) settings.open = false;
        }
      });
    }
    setOwner(owner) {
      if (owner !== this.task.owner) {
        this.pause();
        this.reference = "";
        this.imported = null;
        this.prompt = "";
        this.resultName = "";
        this.assets = [];
      }
      this.task.setOwner(owner);
    }
    pause() {
      clearTimeout(this.timer);
      this.motion?.destroy();
      this.motion = null;
    }
    async run(action) {
      if (this.working) return;
      this.working = true;
      this.root.setAttribute("aria-busy", "true");
      for (const button of this.root.querySelectorAll(
        "button,input,textarea,select",
      ))
        button.disabled = true;
      try {
        await action();
      } catch (error) {
        this.studio.message(error.message, true);
      } finally {
        this.working = false;
        this.root.removeAttribute("aria-busy");
        // Re-render once; never re-enable a submit button without rechecking state.
        this.render();
      }
    }
    back(force = false) {
      if (this.working && !force) return;
      if (!force && this.mode === "assets") {
        this.mode = this.assetTarget === "reference" ? "generate" : "import";
        this.studio.message();
        this.render();
        return;
      }
      this.pause();
      this.root.hidden = true;
      this.studio.dialog.classList.remove("is-creating");
      this.studio.message();
      this.studio.renderCards();
    }
    async open(mode = "generate") {
      if (this.working) return;
      this.mode = mode;
      this.root.hidden = false;
      this.studio.setEditing(false);
      this.studio.gallery.pause();
      this.studio.dialog.classList.add("is-creating");
      this.studio.message();
      if (mode === "generate") {
        this.render();
        await this.run(async () => {
          this.config = await this.studio.request("/api/config");
          this.providers = (this.config.api_providers || []).filter(
            (p) => p.enabled !== false && p.image_models?.length,
          );
          this.providerId = this.providers.some((p) => p.id === this.providerId)
            ? this.providerId
            : this.providers.find((p) => p.primary)?.id ||
              this.providers.find((p) => p.id !== "modelscope")?.id ||
              this.providers[0]?.id ||
              "";
          this.selectProvider();
        });
      } else if (mode === "assets") {
        this.assetTarget = "import";
        this.assetSource = "canvas";
        this.assets = [];
        this.render();
        await this.loadAssets();
      } else {
        this.imported = null;
        this.render();
        this.fileInput.click();
      }
    }
    selectProvider() {
      const provider = this.providers?.find((p) => p.id === this.providerId);
      this.model = provider?.image_models.includes(this.model)
        ? this.model
        : window.CanvasModelPicker?.preferredModel(
            "image",
            provider?.id,
            provider?.image_models || [],
          ) ||
          provider?.image_models[0] ||
          "";
    }
    render() {
      clearTimeout(this.timer);
      // Receipt polling reuses the same WebGL context and model.
      const keepMotion =
        !this.root.hidden &&
        this.mode === "generate" &&
        this.task.state?.stage !== "result" &&
        this.motion;
      if (keepMotion) this.motion.host.remove();
      else this.pause();
      this.root.replaceChildren();
      if (this.root.hidden) return;
      const header = el("header", "character-generator-header");
      const back = el("button", "", "‹");
      back.type = "button";
      back.setAttribute(
        "aria-label",
        this.mode === "assets" ? "返回角色创建" : "返回角色库",
      );
      back.addEventListener("click", () => this.back());
      header.append(back);
      this.root.append(header);
      if (this.mode === "assets") this.renderAssets();
      else if (this.mode === "import") this.renderImport();
      else this.renderGenerator();
      window.lucide?.createIcons();
    }
    filePicker(label, callback) {
      const input = el("input");
      input.type = "file";
      input.hidden = true;
      input.accept = ".png,.jpg,.jpeg,.webp,.gif";
      input.setAttribute("aria-label", label);
      input.addEventListener("change", () => {
        const file = input.files[0];
        input.value = "";
        if (file)
          this.run(async () => callback(await this.upload(file), file.name));
      });
      this.root.append(input);
      return input;
    }
    async upload(file) {
      if (
        !/\.(png|jpe?g|webp|gif)$/i.test(file.name) ||
        file.size > 50 * 1024 * 1024
      )
        throw new Error("请选择不超过50MB的PNG/JPG/WebP/GIF图片");
      const form = new FormData();
      form.append("files", file);
      const result = await this.studio.request("/api/ai/upload", {
        method: "POST",
        body: form,
      });
      const url = result.files?.find((item) => item.kind === "image")?.url;
      if (!url) throw new Error("上传未返回可用图片，请重新选择");
      return url;
    }
    renderGenerator() {
      const state = this.task.state;
      const pending =
        state && !["saved", "failed", "cancelled"].includes(state.stage);
      const content = el("main", "character-generator-content");
      const status = el("div", "character-generator-status");
      status.append(
        el(
          "h2",
          "",
          state?.stage === "result"
            ? "你的新角色"
            : pending
              ? "正在创建角色"
              : "创建你的新角色",
        ),
      );
      if (pending && state.stage !== "result")
        status.append(
          el(
            "p",
            "",
            {
              queued: "任务排队中",
              running: "正在生成，请稍候",
              unknown: "原任务状态待核对",
              submitting: "正在核对受理状态",
            }[state.stage] || "请查询原任务",
          ),
        );
      content.append(status);
      this.root.append(content);
      if (state?.stage === "result") this.renderResult(content, state);
      else {
        const motion =
          this.motion?.host || el("div", "character-generator-motion");
        motion.dataset.characterGenerationMotion = "";
        motion.dataset.characterGenerationHitbox = "";
        content.append(motion);
        if (this.motion) this.motion.setPhase(pending ? "loading" : "pending");
        else
          this.motion = new CharacterMotionPreview(
            motion,
            pending ? "loading" : "pending",
          );
        if (!motion.querySelector(".character-generator-fallback"))
          motion.append(el("span", "character-generator-fallback", "角色预览"));
      }
      if (pending) {
        const footer = el(
          "footer",
          "character-generator-footer character-generation-progress",
        );
        const line = el(
          "p",
          "",
          state.error ||
            (state.taskId
              ? "任务 " + state.taskId
              : "请在日志 → 生成任务中核对原请求"),
        );
        footer.append(line);
        if (state.source?.source_name)
          footer.append(
            el(
              "p",
              "",
              `实际调用：${state.source.source_name} · ${state.source.scope === "department" ? "部门专用" : "公司共享"}`,
            ),
          );
        if (state.stage !== "result") {
          if (!state.taskId) {
            const input = el("input");
            input.placeholder = "粘贴原任务编号";
            input.setAttribute("aria-label", "原角色任务编号");
            const attach = el("button", "", "查询原任务");
            attach.type = "button";
            attach.onclick = () =>
              this.run(async () => {
                await this.task.attach(input.value.trim());
                await this.task.refresh();
              });
            footer.append(input, attach);
          } else {
            const refresh = el("button", "", "刷新原任务");
            refresh.type = "button";
            refresh.onclick = () => this.run(() => this.task.refresh());
            footer.append(refresh);
          }
          if (
            ["queued", "running"].includes(state.stage) &&
            state.taskId &&
            !this.root.hidden &&
            this.studio.dialog.open
          )
            this.timer = setTimeout(
              () => this.run(() => this.task.refresh()),
              2000,
            );
        }
        this.root.append(footer);
        return;
      }
      if (state?.error) status.append(el("p", "", state.error));
      const footer = el("footer", "character-generator-footer");
      const settings = el("details", "character-generator-settings");
      const summary = el(
        "summary",
        "",
        this.providerId ? this.model || "生成设置" : "选择生成平台",
      );
      settings.append(summary);
      const panel = el("div", "character-generation-settings-panel");
      const provider = el("select");
      provider.setAttribute("aria-label", "角色生成平台");
      for (const row of this.providers || [])
        provider.add(new Option(row.name || row.id, row.id));
      provider.value = this.providerId || "";
      provider.onchange = () => {
        this.providerId = provider.value;
        this.selectProvider();
        this.render();
      };
      const model = el("select");
      model.setAttribute("aria-label", "角色生成模型");
      const selected = this.providers?.find((p) => p.id === this.providerId);
      for (const name of selected?.image_models || [])
        model.add(new Option(name, name));
      model.value = this.model || "";
      model.onchange = () => {
        this.model = model.value;
        this.render();
      };
      const source = el("p", "character-generator-source");
      panel.append(
        provider,
        model,
        source,
        el(
          "p",
          "",
          "生成1张正面全身角色参考图，简洁背景；费用按所选平台计费。",
        ),
      );
      window.CallSourceHint?.update(source, selected);
      settings.append(panel);
      footer.append(settings);
      const form = el("form", "character-generator-prompt-wrap");
      const capsule = el("div", "character-generator-prompt");
      const refControl = el("div", "character-generator-reference-control");
      const refButton = el("button", "", "");
      refButton.type = "button";
      refButton.setAttribute("aria-label", "选择参考图");
      refButton.setAttribute("aria-expanded", "false");
      refButton.innerHTML = '<i data-lucide="image-plus"></i>';
      const menu = el("div", "character-generator-reference-menu");
      menu.hidden = true;
      menu.setAttribute("role", "menu");
      const upload = el("button", "", "从本地上传");
      upload.type = "button";
      upload.setAttribute("role", "menuitem");
      const assets = el("button", "", "从我的资产选择");
      assets.type = "button";
      assets.setAttribute("role", "menuitem");
      const file = this.filePicker("上传角色生成参考图", (url) => {
        this.reference = url;
      });
      upload.onclick = () => {
        menu.hidden = true;
        file.click();
      };
      assets.onclick = () => {
        this.assetTarget = "reference";
        this.mode = "assets";
        this.assetSource = "canvas";
        this.assets = [];
        this.render();
        this.loadAssets();
      };
      menu.append(upload, assets);
      refButton.onclick = () => {
        menu.hidden = !menu.hidden;
        refButton.setAttribute("aria-expanded", String(!menu.hidden));
      };
      refControl.append(refButton, menu);
      capsule.append(refControl);
      const body = el("div", "character-generator-prompt-body");
      if (this.reference) {
        const ref = el("div", "character-generator-reference");
        ref.append(picture(this.reference));
        const remove = el("button", "", "×");
        remove.type = "button";
        remove.setAttribute("aria-label", "移除生成参考图");
        remove.onclick = () => {
          this.reference = "";
          this.render();
        };
        ref.append(remove);
        body.append(ref);
      }
      const prompt = el("textarea");
      prompt.rows = 1;
      prompt.maxLength = 2000;
      prompt.placeholder = "描述你的角色特征";
      prompt.setAttribute("aria-label", "描述你的角色特征");
      prompt.value = this.prompt || "";
      const submit = el("button", "character-generator-submit", "生成");
      submit.type = "submit";
      submit.setAttribute("aria-label", "生成角色");
      const update = () => {
        this.prompt = prompt.value;
        capsule.classList.toggle(
          "is-expanded",
          Boolean(this.reference) ||
            prompt.value.includes("\n") ||
            prompt.value.length > 35,
        );
        submit.disabled =
          !prompt.value.trim() || !this.model || !this.task.canGenerate();
      };
      prompt.oninput = update;
      prompt.onkeydown = (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          if (!submit.disabled) form.requestSubmit();
        }
      };
      body.append(prompt);
      capsule.append(body, submit);
      form.append(capsule);
      footer.append(form);
      this.root.append(footer);
      update();
      form.onsubmit = (event) => {
        event.preventDefault();
        this.run(async () => {
          const profile =
            window.CanvasModelPicker?.profileFor(selected, this.model) || {};
          if (this.reference && profile.max_references === 0)
            throw new Error("该模型不支持参考图，请移除图片或选择其他模型");
          const ratio = (profile.ratios || []).includes("2:3")
            ? "2:3"
            : profile.ratios?.[0] || "2:3";
          const payload = {
            provider_id: this.providerId,
            model: this.model,
            prompt:
              "创建用于角色库的单人正面全身参考图，头部到脚部完整入镜，姿态自然，背景简洁，不添加文字或水印。有参考图时参考其人物特征。角色描述：\n" +
              this.prompt.trim(),
            size: "1024x1536",
            quality: "auto",
            reference_images: this.reference
              ? [{ url: this.reference, kind: "image" }]
              : [],
          };
          if (profile.mode === "aspect-size")
            Object.assign(payload, {
              aspect_ratio: ratio,
              resolution:
                profile.fixed_resolution || profile.resolutions?.[0] || "1K",
            });
          this.resultName = "";
          await this.task.submit(payload, this.prompt.trim());
          await this.task.refresh();
        });
      };
    }
    renderResult(content, state) {
      const panel = el("form", "character-generation-result");
      panel.append(picture(state.images[0]));
      const name = el("input");
      name.required = true;
      name.maxLength = 80;
      name.setAttribute("aria-label", "新角色名称");
      name.placeholder = "为角色命名";
      name.value = this.resultName || "新角色";
      name.oninput = () => {
        this.resultName = name.value;
      };
      const save = el("button", "character-primary", "保存到我的角色库");
      save.type = "submit";
      panel.append(name, save);
      panel.onsubmit = (event) => {
        event.preventDefault();
        this.run(async () => {
          const row = await this.task.save({
            name: name.value.trim(),
            description: state.prompt,
          });
          this.saved(row);
        });
      };
      content.append(panel);
    }
    saved(row) {
      this.studio.rows = [
        row,
        ...this.studio.rows.filter((item) => item.id !== row.id),
      ];
      this.studio.draft = structuredClone(row);
      this.studio.library = "personal";
      this.studio.gallery.source = "personal";
      this.studio.gallery.archived = false;
      this.studio.gallery.selectedId = row.id;
      this.imported = null;
      this.back(true);
      this.studio.message("角色已保存到我的角色库");
    }
    renderImport() {
      const form = el("form", "character-import-card");
      form.setAttribute("aria-label", "导入已有角色");
      form.append(el("h2", "", "导入已有角色"));
      const upload = el(
        "button",
        "character-import-image",
        this.imported ? "" : "选择角色图片",
      );
      upload.type = "button";
      if (this.imported) upload.append(picture(this.imported.url));
      this.fileInput = this.filePicker("上传已有角色", (url, name) => {
        this.imported = {
          url,
          name: name.replace(/\.[^.]+$/, "").slice(0, 80),
          description: "",
          createId: CanvasTaskQuery.requestId(),
        };
      });
      upload.onclick = () => this.fileInput.click();
      form.append(upload);
      const assets = el("button", "", "从我的资产选择");
      assets.type = "button";
      assets.onclick = () => {
        this.mode = "assets";
        this.assetTarget = "import";
        this.assetSource = "canvas";
        this.assets = [];
        this.render();
        this.loadAssets();
      };
      form.append(assets);
      const name = el("input");
      name.required = true;
      name.maxLength = 80;
      name.placeholder = "角色名称";
      name.setAttribute("aria-label", "导入角色名称");
      name.value = this.imported?.name || "";
      name.oninput = () => {
        if (this.imported) this.imported.name = name.value;
      };
      const desc = el("textarea");
      desc.maxLength = 2000;
      desc.placeholder = "描述角色特征（可选）";
      desc.setAttribute("aria-label", "导入角色描述");
      desc.value = this.imported?.description || "";
      desc.oninput = () => {
        if (this.imported) this.imported.description = desc.value;
      };
      const save = el("button", "character-primary", "导入到我的角色库");
      save.type = "submit";
      save.disabled = !this.imported;
      form.append(name, desc, save);
      this.root.append(form);
      form.onsubmit = (event) => {
        event.preventDefault();
        this.run(async () => {
          if (!this.imported) throw new Error("请先选择角色图片");
          const row = await this.studio.request(
            "/enterprise/api/me/characters",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                name: name.value.trim(),
                description: desc.value,
                images: [this.imported.url],
                create_request_id: this.imported.createId,
              }),
            },
          );
          this.saved(row);
        });
      };
    }
    async loadAssets() {
      this.assets = [];
      await this.run(async () => {
        const values = [];
        if (this.assetSource === "canvas") {
          for (const url of this.studio.adapter.selection().filter(Boolean))
            values.push({ url, name: "画布选中图片" });
          const data = await this.studio.request("/api/canvas-assets");
          for (const row of data.items || [])
            if (
              row.kind === "image" ||
              /\.(png|jpe?g|webp|gif)$/i.test(row.url || "")
            )
              values.push({
                url: row.url,
                name: row.name || row.canvas_name || "画布图片",
              });
        } else {
          const data = await this.studio.request("/api/history");
          for (const row of data)
            for (const image of row.images || []) {
              const url = typeof image === "string" ? image : image.url;
              if (url)
                values.push({
                  url,
                  name: row.prompt?.slice(0, 40) || "生成图片",
                });
            }
        }
        this.assets = [
          ...new Map(values.map((item) => [item.url, item])).values(),
        ];
      });
    }
    renderAssets() {
      const title = el(
        "h2",
        "character-assets-title",
        this.assetTarget === "reference"
          ? "选择角色参考图"
          : "从我的资产导入角色",
      );
      this.root.append(title);
      const tabs = el("div", "character-assets-tabs");
      for (const [value, label] of [
        ["canvas", "画布素材"],
        ["history", "生成历史"],
      ]) {
        const button = el("button", "", label);
        button.type = "button";
        button.setAttribute("aria-pressed", String(this.assetSource === value));
        button.onclick = () => {
          this.assetSource = value;
          this.loadAssets();
        };
        tabs.append(button);
      }
      this.root.append(tabs);
      const grid = el("div", "character-pick-assets");
      if (!this.assets?.length)
        grid.append(el("p", "", "暂无可用图片，可切换来源或从本地上传。"));
      for (const item of this.assets || []) {
        const button = el("button");
        button.type = "button";
        button.append(picture(item.url), el("span", "", item.name));
        button.onclick = () => {
          if (this.assetTarget === "reference") {
            this.reference = item.url;
            this.mode = "generate";
          } else {
            this.imported = {
              url: item.url,
              name: item.name.slice(0, 80),
              description: "",
              createId: CanvasTaskQuery.requestId(),
            };
            this.mode = "import";
          }
          this.render();
        };
        grid.append(button);
      }
      this.root.append(grid);
    }
  }
  window.CharacterCreationView = CharacterCreationView;
})();
