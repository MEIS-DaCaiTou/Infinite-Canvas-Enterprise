/* Voice presentation uses the existing owned receipt client and configured keys. */
(function () {
  const voices = [
    ["alloy", "自然均衡"],
    ["echo", "清晰沉稳"],
    ["fable", "叙事表现"],
    ["onyx", "深沉厚实"],
    ["nova", "明亮亲切"],
    ["shimmer", "柔和轻盈"],
  ];
  const el = (tag, text) =>
    Object.assign(document.createElement(tag), { textContent: text || "" });
  class CharacterVoiceView {
    constructor(editor) {
      this.editor = editor;
      this.studio = editor.studio;
    }
    render(root, row) {
      this.root = root;
      this.row = row;
      row.voice ||= {
        provider_id: "",
        model: "tts-1",
        voice: "alloy",
        speed: 1,
        input: "你好，很高兴认识你。",
        instructions: "",
      };
      const voice = row.voice,
        scope = row.id || row._edit_nonce;
      if (this.scope !== scope || !this.task) {
        this.scope = scope;
        this.task = new CharacterCreationTask(
          (...a) => this.studio.request(...a),
          sessionStorage,
          "character-voice-v1:" + scope,
          "audio",
        );
        this.task.setOwner(this.studio.creation.task.owner);
      }
      this.task.setOwner(this.studio.creation.task.owner);
      if (!this.providers) {
        this.providers = [];
        this.studio
          .request("/api/config")
          .then((c) => {
            this.providers = (c.api_providers || []).filter(
              (p) =>
                p.enabled !== false &&
                p.protocol === "openai" &&
                p.id !== "modelscope",
            );
            if (this.editor.tab === "voice") this.editor.render();
          })
          .catch((e) => this.studio.message(e.message, true));
      }
      root.append(el("h3", "音色音调"));
      const scroll = el("div");
      scroll.className = "character-edit-controls-scroll";
      const select = el("select");
      select.setAttribute("aria-label", "语音生成平台");
      for (const p of this.providers)
        select.add(new Option(p.name || p.id, p.id));
      voice.provider_id ||=
        this.providers.find((p) => p.primary)?.id ||
        this.providers.find((p) => {
          try {
            return new URL(p.base_url).hostname === "ai.t8star.org";
          } catch {
            return false;
          }
        })?.id ||
        this.providers[0]?.id ||
        "";
      select.value = voice.provider_id;
      select.onchange = () =>
        this.editor.change(() => (voice.provider_id = select.value));
      const model = el("select");
      model.setAttribute("aria-label", "语音生成模型");
      for (const m of ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"])
        model.add(new Option(m, m));
      model.value = voice.model;
      model.onchange = () =>
        this.editor.change(() => (voice.model = model.value));
      scroll.append(select, model);
      const sourceHint = el("p");
      sourceHint.className = "character-edit-hint";
      window.CallSourceHint?.update(
        sourceHint,
        this.providers.find((p) => p.id === voice.provider_id),
      );
      scroll.append(sourceHint);
      for (const [key, label] of voices) {
        const button = el("button", label + " · " + key);
        button.className = "character-voice-choice";
        button.setAttribute("aria-pressed", String(voice.voice === key));
        button.onclick = () => this.editor.change(() => (voice.voice = key));
        scroll.append(button);
      }
      const speed = el("input");
      speed.type = "range";
      speed.min = 0.25;
      speed.max = 4;
      speed.step = 0.05;
      speed.value = voice.speed;
      speed.setAttribute("aria-label", "语音速度");
      const speedLabel = el("label", "语速 " + voice.speed + "×");
      speedLabel.className = "character-edit-slider";
      speed.style.setProperty(
        "--range-progress",
        ((Number(voice.speed) - 0.25) / 3.75) * 100 + "%",
      );
      speed.onchange = () =>
        this.editor.change(() => (voice.speed = Number(speed.value)));
      speedLabel.append(speed);
      scroll.append(speedLabel);
      for (const [key, label, max] of [
        ["input", "试听文本", 2000],
        ["instructions", "音色描述（gpt-4o-mini-tts）", 1000],
      ]) {
        const field = el("textarea");
        field.setAttribute("aria-label", label);
        field.placeholder = label;
        field.maxLength = max;
        field.value = voice[key] || "";
        field.oninput = () => {
          voice[key] = field.value;
          this.studio.dirty = true;
        };
        scroll.append(field);
      }
      const hint = el(
        "p",
        "试听生成将提交1条付费语音任务，使用所选平台的当前授权密钥。生成语音为AI合成。",
      );
      hint.className = "character-edit-hint";
      scroll.append(hint);
      const state = this.task.state;
      if (state?.images?.[0] && state.stage === "result") {
        const audio = el("audio");
        audio.controls = true;
        audio.src = state.images[0];
        audio.setAttribute("aria-label", "生成音色试听");
        scroll.append(audio);
        const adopt = el("button", "采用此音色");
        adopt.onclick = () => {
          this.editor.change(() => {
            row.voice = { ...state.context, url: state.images[0] };
          });
          state.stage = "saved";
          this.task.store();
        };
        scroll.append(adopt);
      } else if (voice.url) {
        const audio = el("audio");
        audio.controls = true;
        audio.src = voice.url;
        audio.setAttribute("aria-label", "当前角色音色");
        scroll.append(audio);
      }
      if (state?.source)
        scroll.append(
          el(
            "small",
            "本次实际调用：" +
              (state.source.scope === "department" ? "部门专用" : "公司共享") +
              " · " +
              (state.source.source_name || "未命名来源"),
          ),
        );
      if (state?.error) {
        const p = el("p", state.error);
        p.className = "character-warning";
        scroll.append(p);
      }
      if (state?.taskId) scroll.append(el("small", state.taskId));
      const action = el(
        "button",
        this.task.canGenerate()
          ? "生成试听"
          : state?.stage === "result"
            ? "请先采用试听结果"
            : "查询原语音任务",
      );
      action.className = "character-edit-generate";
      action.disabled =
        !!this.working || !voice.provider_id || state?.stage === "result";
      action.onclick = async () => {
        if (this.working) return;
        const task = this.task;
        const current = () =>
          this.task === task &&
          this.studio.draft === row &&
          this.editor.tab === "voice" &&
          this.studio.editing &&
          this.studio.dialog.open;
        this.working = true;
        this.editor.render();
        try {
          if (task.canGenerate())
            await task.submit(
              { ...voice, url: undefined },
              row.name + " · 音色",
              structuredClone(voice),
            );
          await task.refresh();
        } catch (e) {
          if (current()) this.studio.message(e.message, true);
        } finally {
          this.working = false;
          if (current()) this.editor.render();
        }
      };
      if (state?.stage === "unknown") {
        const label = el("label");
        const box = el("input");
        box.type = "checkbox";
        label.append(
          box,
          el("span", "了解原语音请求可能已受理或扣费，仍确认另建付费任务"),
        );
        const reset = el("button", "保留原记录，准备新语音任务");
        reset.disabled = true;
        box.onchange = () => (reset.disabled = !box.checked);
        reset.onclick = () => {
          this.task.archiveUnknown(box.checked);
          this.editor.render();
        };
        scroll.append(label, reset);
      }
      root.append(scroll, action);
      clearTimeout(this.timer);
      if (["queued", "running"].includes(state?.stage) && !this.working) {
        const task = this.task;
        this.timer = setTimeout(async () => {
          if (
            this.editor.tab === "voice" &&
            this.studio.dialog.open &&
            this.studio.editing &&
            this.task === task
          ) {
            await task.refresh().catch(() => {});
            if (
              this.task === task &&
              this.studio.draft === row &&
              this.studio.editing &&
              this.editor.tab === "voice"
            )
              this.editor.render();
          }
        }, 2500);
      }
    }
    stop() {
      clearTimeout(this.timer);
    }
  }
  window.CharacterVoiceView = CharacterVoiceView;
})();
