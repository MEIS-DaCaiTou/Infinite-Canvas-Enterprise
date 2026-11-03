/* Three serial image tasks, one explicit approval; existing receipts remain truth. */
(function () {
  const kinds = ["portrait", "expression", "turnaround"];
  const label = (k) => CharacterDesign.assets.find((x) => x[0] === k)[1];
  class CharacterAssetBatch {
    constructor(action) {
      this.action = action;
      const row = action.row;
      this.existing = row.assets || {};
      this.tasks = Object.fromEntries(
        kinds.map((kind) => {
          const task = new CharacterCreationTask(
            (...a) => action.studio.request(...a),
            sessionStorage,
            "character-asset-set-v1:" +
              (row.id || row._edit_nonce) +
              ":" +
              encodeURIComponent(CharacterDesign.slots(row).full_body) +
              ":" +
              kind,
          );
          task.setOwner(action.studio.creation.task.owner);
          return [kind, task];
        }),
      );
    }
    stop() {
      clearTimeout(this.timer);
      this.running = false;
    }
    render(shell) {
      clearTimeout(this.timer);
      const a = this.action,
        el = (tag, text) =>
          Object.assign(document.createElement(tag), {
            textContent: text || "",
          });
      shell.append(
        el(
          "p",
          "自动补齐头像、表情九宫格和角色设定图；缺失项各提交1条付费任务，已有资产及已完成项不会重复生成，全部完成后保存角色。",
        ),
      );
      for (const kind of kinds) {
        const state = this.tasks[kind].state;
        const row = el("div");
        row.className = "character-batch-item";
        row.append(
          el("span", label(kind)),
          el(
            "span",
            !state
              ? this.existing[kind]
                ? "已有资产"
                : "待生成"
              : {
                  result: "已完成",
                  saved: "已完成",
                  queued: "等待中",
                  running: "生成中",
                  unknown: "待核对",
                  failed: "失败",
                }[state.stage] || state.stage,
          ),
        );
        if (state?.images?.[0] || this.existing[kind]) {
          const image = el("img");
          image.src = state?.images?.[0] || this.existing[kind];
          image.alt = label(kind);
          row.append(image);
        }
        if (state?.taskId) row.append(el("small", state.taskId));
        if (state?.source)
          row.append(
            el(
              "small",
              "实际调用：" +
                (state.source.scope === "department"
                  ? "部门专用"
                  : "公司共享") +
                " · " +
                (state.source.source_name || "未命名来源"),
            ),
          );
        if (state?.error) row.append(el("p", state.error));
        if (state?.stage === "unknown") {
          const box = el("input");
          box.type = "checkbox";
          const text = el("label");
          text.append(
            box,
            el("span", "了解原请求可能已受理或扣费，仍确认另建此项付费任务"),
          );
          const reset = el("button", "保留原记录，允许重新生成此项");
          reset.disabled = true;
          box.onchange = () => {
            reset.disabled = !box.checked || a.working;
          };
          reset.onclick = () =>
            a.run(async () => {
              this.tasks[kind].archiveUnknown(box.checked);
            });
          row.append(text, reset);
        }
        shell.append(row);
      }
      const provider = el("select");
      provider.setAttribute("aria-label", "资产套系生成平台");
      for (const p of a.providers || [])
        provider.add(new Option(p.name || p.id, p.id));
      provider.value = a.providerId || "";
      provider.onchange = () => {
        a.providerId = provider.value;
        a.selectProvider();
        a.render();
      };
      const model = el("select");
      model.setAttribute("aria-label", "资产套系生成模型");
      for (const m of a.providers?.find((p) => p.id === a.providerId)
        ?.image_models || [])
        model.add(new Option(m, m));
      model.value = a.model || "";
      model.onchange = () => {
        a.model = model.value;
      };
      provider.disabled = model.disabled = !!a.working || this.running;
      const source = el("p");
      window.CallSourceHint?.update(
        source,
        a.providers?.find((p) => p.id === a.providerId),
      );
      const submit = el(
        "button",
        this.running ? "继续查询原任务" : "生成缺失资产并保存",
      );
      submit.className = "character-primary";
      submit.disabled = !!a.working || !a.model;
      submit.onclick = () => {
        this.running = true;
        this.tick();
      };
      shell.append(provider, model, source, submit);
      if (this.running && !a.working && !a.root.hidden)
        this.timer = setTimeout(() => this.tick(), 2500);
    }
    async tick() {
      clearTimeout(this.timer);
      const a = this.action;
      if (a.working || a.root.hidden) return;
      await a.run(async () => {
        for (const kind of kinds) {
          const task = this.tasks[kind];
          if (this.existing[kind] && !task.state) continue;
          if (task.state?.stage === "saved") task.state.stage = "result";
          if (
            !task.state ||
            ["failed", "cancelled"].includes(task.state.stage)
          ) {
            await task.submit(
              a.payload(kind),
              a.row.name + " · " + label(kind),
              { reference: CharacterDesign.slots(a.row).full_body },
            );
          }
          if (task.state.stage !== "result") await task.refresh();
          if (task.state.stage !== "result") {
            if (["unknown", "failed", "cancelled"].includes(task.state.stage))
              this.running = false;
            return;
          }
          if (
            task.state.context?.reference !==
            CharacterDesign.slots(a.row).full_body
          ) {
            this.running = false;
            throw new Error(
              "原套系任务使用了其他版本的角色图。请先返回原角色版本核对结果，未自动保存。",
            );
          }
        }
        this.running = false;
        const assets = Object.fromEntries(
          kinds.map((k) => [
            k,
            this.tasks[k].state?.images?.[0] || this.existing[k],
          ]),
        );
        if ((await a.onAdopt(assets)) === false)
          throw new Error("角色保存未完成，已生成资产仍然保留，可再次保存。");
        for (const kind of kinds) {
          if (this.tasks[kind].state) {
            this.tasks[kind].state.stage = "saved";
            this.tasks[kind].store();
          }
        }
        a.root.hidden = true;
      });
    }
  }
  window.CharacterAssetBatch = CharacterAssetBatch;
})();
