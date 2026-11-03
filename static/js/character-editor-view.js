/* Three-column editor. Owns presentation/history only; Studio owns persistence. */
(function () {
  const el = (tag, cls, text) =>
    Object.assign(document.createElement(tag), {
      className: cls || "",
      ...(text === undefined ? {} : { textContent: text }),
    });
  const button = (label, fn, cls = "") => {
    const b = el("button", cls, label);
    b.type = "button";
    b.onclick = fn;
    return b;
  };
  class CharacterEditorView {
    constructor(studio, labels) {
      this.studio = studio;
      this.labels = labels;
      this.tab = "retouch";
      this.faceTab = "skin";
      this.mode = "half";
      this.past = [];
      this.future = [];
      this.voiceView = new CharacterVoiceView(this);
    }
    render() {
      const studio = this.studio,
        row = studio.draft;
      studio.editor.replaceChildren();
      if (!row) return;
      if (this.row !== row) {
        this.preview?.destroy();
        this.preview = null;
        this.bakedSignature = null;
        this.previewMessage = "";
        this.editToken = Symbol();
        this.row = row;
        this.original = structuredClone(row);
        this.past = [];
        this.future = [];
      }
      row.design ||= { version: 1, values: {}, notes: "" };
      const root = el("div", "character-workspace");
      const left = el("aside", "character-edit-left");
      const name = el("input", "character-edit-name");
      name.name = "name";
      name.maxLength = 80;
      name.value = row.name;
      name.setAttribute("aria-label", "角色名称");
      name.oninput = () =>
        this.change(() => {
          row.name = name.value;
        }, false);
      left.append(
        name,
        el(
          "p",
          "character-edit-subtitle",
          [
            this.labels.gender[row.gender],
            this.labels.age_group[row.age_group],
            this.labels.region[row.region],
          ]
            .filter((v) => v && v !== "未设置")
            .join(" · "),
        ),
      );
      const nav = el("nav", "character-edit-nav");
      nav.setAttribute("aria-label", "角色编辑分区");
      for (const [key, label, glyph] of [
        ["retouch", "脸部精修", "smile"],
        ["feature", "脸部 & 身体特征", "scan-face"],
        ["body", "身材塑形", "person-standing"],
        ["clothing", "服装造型", "shirt"],
        ["voice", "音色音调", "audio-lines"],
      ]) {
        const b = button("", () => {
          this.tab = key;
          if (["retouch", "feature"].includes(key)) this.mode = "half";
          if (["body", "clothing"].includes(key)) this.mode = "full";
          this.render();
        });
        const icon = el("i");
        icon.dataset.lucide = glyph;
        b.append(icon, el("span", "", label));
        b.setAttribute("aria-pressed", String(this.tab === key));
        nav.append(b);
      }
      left.append(nav);
      const profile = button(
          "",
          () => {
            this.tab = "profile";
            this.render();
          },
          "character-edit-profile-link",
        );
      profile.setAttribute("aria-label", "资料与参考图");
      profile.title = "资料与参考图";
      const profileIcon = el("i");
      profileIcon.dataset.lucide = "contact-round";
      profile.append(profileIcon);
      const history = el("div", "character-edit-history");
      const undo = button("↶", () => this.travel(this.past, this.future));
      undo.setAttribute("aria-label", "撤销");
      undo.disabled = !this.past.length;
      const redo = button("↷", () => this.travel(this.future, this.past));
      redo.setAttribute("aria-label", "恢复");
      redo.disabled = !this.future.length;
      for (const [control, glyph, title] of [[undo, "undo-2", "撤销"], [redo, "redo-2", "恢复"]]) {
        control.textContent = "";
        control.title = title;
        const icon = el("i");
        icon.dataset.lucide = glyph;
        control.append(icon);
      }
      const compare = button("按住对比", () => {});
      compare.setAttribute("aria-label", "按住对比");
      compare.title = "按住对比";
      compare.textContent = "";
      const compareIcon = el("i");
      compareIcon.dataset.lucide = "columns-2";
      compare.append(compareIcon);
      compare.disabled = !this.past.length;
      compare.onpointerdown = (e) => {
        compare.setPointerCapture(e.pointerId);
        this.previewOriginal(true);
      };
      compare.onpointerup = compare.onpointercancel = () =>
        this.previewOriginal(false);
      compare.onlostpointercapture = () => this.previewOriginal(false);
      compare.onkeydown = (e) => {
        if ([" ", "Enter"].includes(e.key)) {
          e.preventDefault();
          this.previewOriginal(true);
        }
      };
      compare.onkeyup = compare.onblur = () => this.previewOriginal(false);
      history.append(undo, redo, compare, profile);
      left.append(history);
      const stage = el("main", "character-edit-stage");
      stage.setAttribute("aria-label", "角色预览");
      const picture = el("div", "character-edit-picture");
      picture.classList.toggle("is-half", this.mode === "half");
      const transform = el("div", "character-edit-transform");
      this.pictureTransform = transform;
      const url = CharacterDesign.slots(row).full_body;
      if (url) {
        const img = el("img");
        img.src = url;
        img.alt = row.name + " · 当前角色";
        transform.append(img);
        const source = row.design.preview_source || url;
        const body =
          this.tab === "body" ||
          Object.keys(
            CharacterRetouchPreview.parameters(row.design.values),
          ).some((key) => key.startsWith("body_shape_"));
        if (
          !this.preview ||
          this.preview.source !== source ||
          (body && !this.preview.body)
        ) {
          this.preview?.destroy();
          this.preview = new CharacterRetouchPreview(source, body, (text) => {
            this.previewMessage = text;
            if (this.previewStatus) this.previewStatus.textContent = text;
            this.updateFraming();
          });
        }
        transform.append(this.preview.canvas);
        this.preview.viewMode = this.mode === "half" ? "face" : "body";
        this.preview.update(row.design.values);
      } else transform.append(el("p", "", "请先上传或选择角色图片"));
      picture.append(transform);
      this.updateFraming();
      stage.classList.toggle("is-half", this.mode === "half");
      const mask = el("div", "character-preview-mask");
      mask.setAttribute("aria-hidden", "true");
      mask.append(el("div", "character-preview-mask-blur"));
      const views = el("div", "character-edit-views");
      for (const [key, text] of [
        ["half", "半身"],
        ["full", "全身"],
      ]) {
        const b = button("", () => {
          this.mode = key;
          this.render();
        });
        b.setAttribute("aria-label", text);
        b.title = text;
        const icon = el("i");
        icon.dataset.lucide = key === "half" ? "user-round" : "person-standing";
        b.append(icon);
        b.setAttribute("aria-pressed", String(this.mode === key));
        views.append(b);
      }
      stage.append(picture, mask, views);
      this.previewStatus = el(
        "p",
        "character-preview-status",
        this.previewMessage,
      );
      stage.append(this.previewStatus);
      if (this.preview?.failed)
        stage.append(
          button(
            "重新加载即时预览",
            () => {
              this.preview.destroy();
              this.preview = null;
              this.render();
            },
            "character-edit-preview-retry",
          ),
        );
      const right = el("aside", "character-edit-right");
      right.setAttribute("aria-label", "造型调整");
      this.controls(right, row);
      root.append(left, stage, right);
      const footer = el("footer", "character-edit-footer");
      const discard = button("放弃编辑", () => {
        studio.draft = structuredClone(this.original);
        studio.dirty = false;
        studio.setEditing(false);
        studio.renderCards();
        studio.message();
      });
      const save = button(
        "保存",
        () => this.save(false),
        "character-edit-save",
      );
      const insert = button(
        "保存并添加到画布",
        async () => {
          await this.save(true);
        },
        "character-primary",
      );
      const assetsLabel = el("label", "character-auto-assets");
      const assetsCheck = el("input");
      assetsCheck.type = "checkbox";
      assetsCheck.checked = this.autoAssets !== false;
      assetsCheck.onchange = () => {
        this.autoAssets = assetsCheck.checked;
      };
      assetsLabel.append(assetsCheck, el("span", "", "保存时生成角色资产"));
      footer.append(assetsLabel, save, insert, discard);
      studio.editor.append(root, footer);
      window.lucide?.createIcons();
    }
    updateFraming() {
      if (!this.pictureTransform) return;
      const style = CharacterRetouchPreview.framing(this.mode, this.preview?.position);
      Object.assign(this.pictureTransform.style, style);
      if (this.framingStyle && this.framingMode !== this.mode &&
          this.pictureTransform.animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        this.pictureTransform.animate([this.framingStyle, style], {
          duration: this.mode === "half" ? 620 : 450,
          easing: "cubic-bezier(0.215, 0.61, 0.355, 1)",
        });
      }
      this.framingStyle = style;
      this.framingMode = this.mode;
    }
    change(fn, render = true) {
      this.past.push(structuredClone(this.studio.draft));
      if (this.past.length > 40) this.past.shift();
      this.future = [];
      fn();
      this.studio.dirty = true;
      if (render) this.render();
      else this.refreshHistory();
    }
    refreshHistory() {
      const buttons = this.studio.editor.querySelectorAll(
        ".character-edit-history button",
      );
      if (buttons.length) {
        buttons[0].disabled = buttons[2].disabled = !this.past.length;
        buttons[1].disabled = !this.future.length;
      }
    }
    travel(from, to) {
      if (!from.length) return;
      to.push(structuredClone(this.studio.draft));
      this.row = this.studio.draft = from.pop();
      this.studio.dirty = true;
      this.render();
    }
    previewOriginal(value) {
      const img = this.studio.editor.querySelector(
        ".character-edit-picture img",
      );
      if (img)
        img.src = CharacterDesign.slots(
          value ? this.original : this.studio.draft,
        ).full_body;
      if (this.preview)
        this.preview.canvas.style.visibility = value ? "hidden" : "";
    }
    choices(root, row, key, title, options) {
      root.append(el("h3", "", title));
      const wrap = el("div", "character-edit-choices");
      for (const text of options) {
        const b = button(text, () =>
          this.change(() => {
            row.design.values[key] =
              row.design.values[key] === text ? "" : text;
          }),
        );
        b.setAttribute("aria-pressed", String(row.design.values[key] === text));
        wrap.append(b);
      }
      root.append(wrap);
    }
    sliders(root, row, group) {
      for (const [key, label] of CharacterDesign.groups[group]) {
        const wrap = el("label", "character-edit-slider"),
          head = el("span", "", label),
          output = el("output", "", String(row.design.values[key] || 0)),
          input = el("input");
        input.type = "range";
        input.min = Math.min(
          key === "beauty" ? 0 : CharacterRetouchPreview.minimum(key),
          Number(row.design.values[key] || 0),
        );
        input.max = 100;
        input.step = 1;
        input.value = row.design.values[key] || 0;
        output.value = input.value;
        input.setAttribute("aria-label", label);
        input.oninput = () => {
          if (!input._before) input._before = structuredClone(row);
          output.value = input.value;
          row.design.values[key] = Number(input.value);
          this.studio.dirty = true;
          this.preview?.update(row.design.values);
          input.style.setProperty(
            "--range-progress",
            ((Number(input.value) - Number(input.min)) /
              (Number(input.max) - Number(input.min))) *
              100 +
              "%",
          );
        };
        input.onchange = () => {
          if (input._before) {
            this.past.push(input._before);
            input._before = null;
            this.future = [];
            this.refreshHistory();
          }
        };
        input.style.setProperty(
          "--range-progress",
          ((Number(input.value) - Number(input.min)) /
            (Number(input.max) - Number(input.min))) *
            100 +
            "%",
        );
        const caption = el("span", "", label);
        head.textContent = "";
        head.append(caption, output);
        if (
          !CharacterRetouchPreview.mapping[key] ||
          Number(row.design.values[key]) < CharacterRetouchPreview.minimum(key)
        ) {
          const hint = el("span", "character-control-info", "ⓘ");
          hint.title = CharacterRetouchPreview.mapping[key]
            ? "该历史负值通过生成生效；即时预览按0处理。调整到0或正值可恢复即时预览。"
            : "该调整不支持即时预览，需要生成后生效";
          hint.setAttribute("aria-label", hint.title);
          caption.append(hint);
        }
        wrap.append(head, input);
        root.append(wrap);
      }
    }
    generate(kind = "edit") {
      const row = this.studio.draft;
      const aiKeys = Object.keys(row.design.values).filter(
        (key) =>
          row.design.values[key] &&
          (!CharacterRetouchPreview.mapping[key] ||
            Number(row.design.values[key]) <
              CharacterRetouchPreview.minimum(key)),
      );
      if (
        kind === "edit" &&
        !aiKeys.length &&
        !row.design.notes &&
        Object.keys(CharacterRetouchPreview.parameters(row.design.values))
          .length
      ) {
        if (this.applying) return;
        this.applying = true;
        this.preparePreview()
          .then(() => {
            this.studio.dirty = true;
            this.render();
            this.studio.message("已应用即时调整，请保存角色。");
          })
          .catch((e) => this.studio.message(e.message, true))
          .finally(() => {
            this.applying = false;
          });
        return;
      }
      row._edit_nonce ||= crypto.randomUUID().replaceAll("-", "");
      this.studio.imageAction.open(row, kind, (url, context) => {
        this.change(() => {
          if (kind === "edit" && context?.design)
            row.design = structuredClone(context.design);
          row.assets = {
            ...row.assets,
            [kind === "edit" ? "full_body" : kind]: url,
          };
          if (kind === "edit" || kind === "full_body") row.cover_url = url;
          if (kind === "edit") {
            for (const category of ["portrait", "expression", "turnaround"])
              delete row.assets[category];
            row.design.preview_source = url;
            for (const key of Object.keys(CharacterRetouchPreview.mapping))
              row.design.values[key] = 0;
          }
        });
        this.studio.message("已采用生成结果，请保存角色。");
      });
    }
    async preparePreview() {
      if (this.preparing) return this.preparing;
      this.preparing = this.bakePreview();
      try {
        return await this.preparing;
      } finally {
        this.preparing = null;
      }
    }
    async bakePreview() {
      const row = this.studio.draft;
      if (
        !Object.keys(CharacterRetouchPreview.parameters(row.design.values))
          .length
      ) {
        // Returning every local effect to neutral must also restore the saved pixels.
        const source = row.design.preview_source;
        if (source && source !== CharacterDesign.slots(row).full_body) {
          row.assets = { full_body: source };
          row.cover_url = source;
          this.bakedSignature = null;
        }
        return;
      }
      const source =
        row.design.preview_source || CharacterDesign.slots(row).full_body;
      const signature = source + JSON.stringify(row.design.values);
      if (
        this.bakedSignature === signature ||
        (row.design.preview_source &&
          JSON.stringify(row.design.values) ===
            JSON.stringify(this.original.design?.values))
      )
        return;
      const token = this.editToken;
      const blob = await this.preview.export();
      if (
        token !== this.editToken ||
        row !== this.studio.draft ||
        signature !== source + JSON.stringify(row.design.values)
      )
        throw new Error("角色或调整值已变化，请重新保存当前预览。");
      const form = new FormData();
      form.append(
        "files",
        new File([blob], "character-retouch.png", { type: "image/png" }),
      );
      const result = await this.studio.request("/api/ai/upload", {
        method: "POST",
        body: form,
      });
      const url = result.files?.find((f) => f.kind === "image")?.url;
      if (!url) throw new Error("即时预览图片未保存，请保留当前编辑重试。");
      if (
        token !== this.editToken ||
        row !== this.studio.draft ||
        signature !== source + JSON.stringify(row.design.values)
      )
        throw new Error(
          "角色或调整值已变化，未用旧预览覆盖当前角色，请重新保存。",
        );
      row.design.preview_source = source;
      row.assets = { full_body: url };
      row.cover_url = url;
      this.bakedSignature = signature;
    }
    async save(insert) {
      if (this.saving) return;
      this.saving = true;
      try {
        await this.preparePreview();
        if (this.autoAssets !== false) {
          this.studio.imageAction.openBatch(
            this.studio.draft,
            async (assets) => {
              this.studio.draft.assets = {
                ...this.studio.draft.assets,
                ...assets,
              };
              const success = await this.studio.save();
              if (success && insert) await this.studio.insert();
              return success;
            },
          );
        } else if ((await this.studio.save()) && insert)
          await this.studio.insert();
      } catch (e) {
        this.studio.message(e.message, true);
      } finally {
        this.saving = false;
      }
    }
    controls(root, row) {
      this.voiceView.stop();
      if (this.tab === "profile") {
        this.studio.renderProfileForm(root);
        return;
      }
      if (this.tab === "voice") {
        this.voiceView.render(root, row);
        return;
      }
      const scroll = el("div", "character-edit-controls-scroll");
      if (this.tab === "retouch") {
        const tabs = el("nav", "character-edit-face-tabs");
        for (const [key, label] of [
          ["skin", "皮肤"],
          ["eyes", "眉眼"],
          ["nose", "鼻子"],
          ["lips", "嘴唇"],
          ["face", "脸部"],
          ["makeup", "妆造"],
        ]) {
          const b = button("", () => {
            this.faceTab = key;
            this.render();
          });
          b.setAttribute("aria-label", label);
          b.title = label;
          const icon = el("i");
          icon.dataset.lucide = {
            skin: "circle-dot",
            eyes: "eye",
            nose: "triangle",
            lips: "smile",
            face: "scan-face",
            makeup: "paintbrush",
          }[key];
          b.append(icon);
          if (this.faceTab === key) b.append(el("span", "", label));
          b.setAttribute("aria-pressed", String(this.faceTab === key));
          tabs.append(b);
        }
        scroll.append(tabs);
        if (this.faceTab === "makeup")
          this.choices(scroll, row, "makeup", "妆容", [
            "素颜",
            "裸妆",
            "桃花氛围妆",
            "日常淡妆",
            "冷艳妆",
            "甜美妆",
            "韩系妆",
          ]);
        else this.sliders(scroll, row, this.faceTab);
        if (this.faceTab === "skin") {
          const label = el("label", "character-edit-toggle", "祛斑祛痘 ⓘ");
          label.title = "该调整不支持即时预览，需要生成后生效";
          const toggle = el("input");
          toggle.type = "checkbox";
          toggle.checked = !!row.design.values.fleck;
          toggle.setAttribute("aria-label", "祛斑祛痘");
          toggle.onchange = () =>
            this.change(
              () => (row.design.values.fleck = toggle.checked ? 100 : 0),
            );
          label.append(toggle);
          scroll.append(label);
        }
      } else if (this.tab === "body") this.sliders(scroll, row, "body");
      else if (this.tab === "feature")
        this.choices(scroll, row, "feature", "纹身 & 疤痕", [
          "痣",
          "疤痕·深",
          "疤痕·浅",
          "全脸雀斑",
          "脸颊雀斑",
          "无纹身与疤痕",
        ]);
      else if (this.tab === "clothing") {
        this.choices(scroll, row, "style", "风格", [
          "现代",
          "古风",
          "民国",
          "仙侠",
          "科幻",
          "民族",
          "儿童",
        ]);
        this.choices(scroll, row, "hair", "发型", [
          "长直发",
          "大波浪",
          "波波头",
          "齐肩中短发",
          "高马尾",
          "低马尾",
          "双马尾",
          "丸子头",
          "半扎发",
          "编发",
          "空气刘海",
          "齐刘海",
        ]);
        this.choices(scroll, row, "hair_color", "发色", [
          "黑色",
          "棕色",
          "浅棕",
          "金色",
          "银白",
          "红色",
          "蓝色",
          "紫色",
        ]);
        this.choices(scroll, row, "makeup", "妆容", [
          "素颜",
          "裸妆",
          "桃花氛围妆",
          "日常淡妆",
          "冷艳妆",
          "甜美妆",
          "韩系妆",
        ]);
        const label = el("label", "", "服装描述"),
          outfit = el("textarea");
        outfit.maxLength = 200;
        outfit.value = row.design.values.outfit || "";
        outfit.setAttribute("aria-label", "服装描述");
        outfit.oninput = () =>
          this.change(() => {
            row.design.values.outfit = outfit.value;
          }, false);
        label.append(outfit);
        scroll.append(label);
      }
      const notes = el("textarea");
      notes.maxLength = 1000;
      notes.placeholder = "自定义调整要求";
      notes.setAttribute("aria-label", "自定义调整要求");
      notes.value = row.design.notes || "";
      notes.oninput = () =>
        this.change(() => {
          row.design.notes = notes.value;
        }, false);
      const extra = el("details", "character-edit-extra");
      extra.append(el("summary", "", "自定义调整要求"), notes);
      scroll.append(extra);
      const generate = button(
        "✦ 确认生成",
        () => this.generate(),
        "character-edit-generate",
      );
      generate.disabled = !CharacterDesign.slots(row).full_body;
      root.append(scroll, generate);
    }
  }
  window.CharacterEditorView = CharacterEditorView;
})();
