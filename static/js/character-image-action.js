/* Existing owned task journal client, shared by character edits and typed assets.
 * Closing/polling never submits again; results require explicit adoption. */
(function () {
  const el = (tag, cls, text) =>
    Object.assign(document.createElement(tag), {
      className: cls || "",
      ...(text === undefined ? {} : { textContent: text }),
    });
  class CharacterImageAction {
    constructor(studio) {
      this.studio = studio;
      this.root = el("section", "character-image-action");
      this.root.hidden = true;
      this.root.setAttribute("aria-label", "角色图片生成");
      studio.dialog.append(this.root);
      studio.dialog.addEventListener("close", () => this.close());
      studio.dialog.addEventListener("keydown", (e) => {
        if (!this.root.hidden && e.key === "Escape") {
          e.preventDefault();
          this.close();
        }
      });
    }
    async open(row, kind, onAdopt) {
      this.batch?.stop();
      this.batch = null;
      this.row = structuredClone(row);
      this.kind = kind;
      this.onAdopt = onAdopt;
      this.task = new CharacterCreationTask(
        (...a) => this.studio.request(...a),
        sessionStorage,
        "character-image-v1:" + (row.id || row._edit_nonce) + ":" + kind,
      );
      this.task.setOwner(this.studio.creation.task.owner);
      if (kind === "asset-set") this.batch = new CharacterAssetBatch(this);
      this.root.hidden = false;
      this.studio.editor.inert = true;
      this.render();
      await this.run(async () => {
        const config = await this.studio.request("/api/config");
        this.providers = (config.api_providers || []).filter(
          (p) => p.enabled !== false && p.image_models?.length,
        );
        this.providerId = this.providers.some((p) => p.id === this.providerId)
          ? this.providerId
          : this.providers.find((p) => p.primary)?.id ||
            this.providers.find((p) => p.id !== "modelscope")?.id ||
            this.providers[0]?.id;
        this.selectProvider();
      });
    }
    close() {
      if (this.working) return;
      clearTimeout(this.timer);
      this.batch?.stop();
      this.root.hidden = true;
      this.studio.editor.inert = false;
    }
    selectProvider() {
      const p = this.providers?.find((p) => p.id === this.providerId);
      this.model = p?.image_models?.includes(this.model)
        ? this.model
        : window.CanvasModelPicker?.preferredModel(
            "image",
            p?.id,
            p?.image_models || [],
          ) ||
          p?.image_models?.[0] ||
          "";
    }
    async run(fn) {
      if (this.working) return;
      this.working = true;
      this.render();
      try {
        await fn();
        this.error = "";
      } catch (e) {
        this.error = e.message;
      } finally {
        this.working = false;
        if (this.root.hidden) this.studio.editor.inert = false;
        this.render();
      }
    }
    render() {
      clearTimeout(this.timer);
      this.root.replaceChildren();
      const shell = el("div", "character-image-action-panel");
      const kindLabel =
        this.kind === "edit"
          ? "角色造型调整"
          : this.kind === "asset-set"
            ? "角色资产生成"
            : CharacterDesign.assets.find((a) => a[0] === this.kind)?.[1] ||
              "角色图片";
      shell.append(el("h2", "", kindLabel));
      const close = el("button", "character-image-action-close", "×");
      close.type = "button";
      close.setAttribute("aria-label", "关闭角色图片生成");
      close.disabled = !!this.working;
      close.onclick = () => this.close();
      shell.append(close);
      const state = this.task?.state;
      if (this.batch) {
        this.batch.render(shell);
      } else if (state?.stage === "result") {
        if (
          state.context &&
          (state.context.reference !==
            CharacterDesign.slots(this.row).full_body ||
            state.context.revision !== (this.row.revision || 0))
        )
          shell.append(
            el(
              "p",
              "character-warning",
              "这是此前角色版本的原任务结果。请与当前角色核对，再决定是否采用。",
            ),
          );
        const img = el("img");
        img.src = state.images[0];
        img.alt = "生成结果预览";
        shell.append(img);
        const adopt = el("button", "character-primary", "采用结果");
        adopt.disabled = !!this.working;
        adopt.onclick = () =>
          this.run(async () => {
            await this.onAdopt(state.images[0], state.context);
            state.stage = "saved";
            this.task.store();
            this.root.hidden = true;
          });
        shell.append(adopt, el("p", "", "采用后仍需保存角色；原图片保留。"));
      } else if (
        state &&
        !["saved", "failed", "cancelled"].includes(state.stage)
      ) {
        shell.append(
          el(
            "p",
            "",
            {
              queued: "已受理，等待生成",
              running: "正在生成",
              submitting: "正在受理",
              unknown: "受理结果待核对",
            }[state.stage] || state.stage,
          ),
        );
        if (state.taskId)
          shell.append(el("p", "character-task-id", state.taskId));
        if (state.error)
          shell.append(el("p", "character-warning", state.error));
        if (state.taskId) {
          const refresh = el("button", "", "刷新原任务");
          refresh.disabled = !!this.working;
          refresh.onclick = () => this.run(() => this.task.refresh());
          shell.append(refresh);
          if (
            ["queued", "running"].includes(state.stage) &&
            !this.working &&
            !this.root.hidden &&
            this.studio.dialog.open
          )
            this.timer = setTimeout(
              () => this.run(() => this.task.refresh()),
              2500,
            );
        } else {
          const taskId = el("input");
          taskId.placeholder = "日志中本人原任务编号";
          taskId.setAttribute("aria-label", "角色原任务编号");
          const attach = el("button", "", "关联原任务");
          attach.disabled = !!this.working;
          attach.onclick = () =>
            this.run(async () => {
              await this.task.attach(taskId.value.trim());
              await this.task.refresh();
            });
          shell.append(taskId, attach);
        }
        shell.append(
          el("p", "", "关闭后可从同一角色、同一入口恢复，不会自动重提。"),
        );
        if (state.stage === "unknown") {
          shell.append(
            el(
              "p",
              "",
              state.canQuery
                ? "可在日志中续查供应商原任务。"
                : "供应商未返回可查询编号；刷新只能读取本地记录，不能确定供应商是否扣费。",
            ),
          );
          const acknowledged = el("input");
          acknowledged.type = "checkbox";
          const label = el("label", "character-task-ack");
          label.append(
            acknowledged,
            el("span", "", "了解原请求可能已受理或扣费，仍确认另建付费任务"),
          );
          const fresh = el("button", "", "保留原任务，准备新任务");
          fresh.disabled = true;
          acknowledged.onchange = () => {
            fresh.disabled = !acknowledged.checked || this.working;
          };
          fresh.onclick = () =>
            this.run(async () =>
              this.task.archiveUnknown(acknowledged.checked),
            );
          shell.append(label, fresh);
        }
      } else {
        const provider = el("select");
        provider.setAttribute("aria-label", "造型生成平台");
        for (const p of this.providers || [])
          provider.add(new Option(p.name || p.id, p.id));
        provider.value = this.providerId || "";
        provider.onchange = () => {
          this.providerId = provider.value;
          this.selectProvider();
          this.render();
        };
        const model = el("select");
        model.setAttribute("aria-label", "造型生成模型");
        const selected = this.providers?.find((p) => p.id === this.providerId);
        for (const m of selected?.image_models || [])
          model.add(new Option(m, m));
        model.value = this.model || "";
        model.onchange = () => {
          this.model = model.value;
          this.render();
        };
        const source = el("p", "character-generator-source");
        window.CallSourceHint?.update(source, selected);
        const prompt = el("textarea");
        prompt.value = CharacterDesign.prompt(this.kind, this.row?.design);
        prompt.readOnly = true;
        prompt.setAttribute("aria-label", "本次角色生成要求");
        shell.append(
          provider,
          model,
          source,
          prompt,
          el(
            "p",
            "",
            "使用当前角色图片作为参考，仅提交1张。费用按所选平台计费，生成后可预览并决定是否采用。",
          ),
        );
        if (state?.error)
          shell.append(el("p", "character-warning", state.error));
        const capability =
          window.CanvasModelPicker?.profileFor(selected, this.model) || {};
        if (capability.max_references === 0)
          shell.append(
            el(
              "p",
              "character-warning",
              "所选模型不支持参考图，请选择图片编辑模型。",
            ),
          );
        const submit = el("button", "character-primary", "确认生成");
        submit.disabled =
          !!this.working || !this.model || capability.max_references === 0;
        submit.onclick = () =>
          this.run(async () => {
            const profile =
              window.CanvasModelPicker?.profileFor(selected, this.model) || {};
            if (profile.max_references === 0)
              throw new Error(
                "所选模型不支持参考图，请选择支持图片编辑的模型。",
              );
            const ref = CharacterDesign.slots(this.row).full_body;
            if (!ref) throw new Error("请先选择角色全身图。");
            const wide = this.kind === "turnaround",
              square = this.kind === "expression";
            const ratio = wide ? "16:9" : square ? "1:1" : "2:3";
            const payload = {
              provider_id: this.providerId,
              model: this.model,
              prompt: prompt.value,
              size: wide ? "1536x1024" : square ? "1024x1024" : "1024x1536",
              quality: "auto",
              reference_images: [{ url: ref, kind: "image" }],
            };
            if (profile.mode === "aspect-size")
              Object.assign(payload, {
                aspect_ratio: (profile.ratios || []).includes(ratio)
                  ? ratio
                  : profile.ratios?.[0] || ratio,
                resolution:
                  profile.fixed_resolution || profile.resolutions?.[0] || "1K",
              });
            await this.task.submit(payload, this.row.name + " · " + kindLabel, {
              revision: this.row.revision || 0,
              reference: ref,
              design: this.row.design || null,
            });
            await this.task.refresh();
          });
        shell.append(submit);
      }
      if (this.error) shell.append(el("p", "character-warning", this.error));
      shell.setAttribute("aria-busy", String(!!this.working));
      this.root.append(shell);
    }
    openBatch(row, onDone) {
      return this.open(row, "asset-set", onDone);
    }
    payload(kind) {
      const selected = this.providers?.find((p) => p.id === this.providerId);
      const profile =
        window.CanvasModelPicker?.profileFor(selected, this.model) || {};
      if (profile.max_references === 0)
        throw new Error("所选模型不支持参考图，请选择图片编辑模型。");
      const ref = CharacterDesign.slots(this.row).full_body;
      if (!ref) throw new Error("请先选择角色全身图。");
      const wide = kind === "turnaround",
        square = kind === "expression";
      const ratio = wide ? "16:9" : square ? "1:1" : "2:3";
      const payload = {
        provider_id: this.providerId,
        model: this.model,
        prompt: CharacterDesign.prompt(kind, this.row.design),
        size: wide ? "1536x1024" : square ? "1024x1024" : "1024x1536",
        quality: "auto",
        reference_images: [{ url: ref, kind: "image" }],
      };
      if (profile.mode === "aspect-size")
        Object.assign(payload, {
          aspect_ratio: (profile.ratios || []).includes(ratio)
            ? ratio
            : profile.ratios?.[0] || ratio,
          resolution:
            profile.fixed_resolution || profile.resolutions?.[0] || "1K",
        });
      return payload;
    }
  }
  window.CharacterImageAction = CharacterImageAction;
})();
