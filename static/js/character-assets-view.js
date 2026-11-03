/* Typed role assets use existing media URLs. Missing categories stay explicit. */
(function () {
  const el = (tag, cls, text) =>
    Object.assign(document.createElement(tag), {
      className: cls || "",
      ...(text === undefined ? {} : { textContent: text }),
    });
  const button = (text, fn, cls = "") => {
    const b = el("button", cls, text);
    b.type = "button";
    b.onclick = fn;
    return b;
  };
  function open(gallery, row) {
    gallery.closeAssets();
    const detail = el("section", "character-assets-detail");
    detail.setAttribute("aria-label", row.name + " · 角色资产详情");
    detail.setAttribute("role", "region");
    gallery.detail = detail;
    gallery.root.classList.add("has-asset-detail");
    for (const node of gallery.root.querySelectorAll(
      ".character-header,.character-toolbar,.character-grid",
    ))
      node.inert = true;
    const dismiss = button(
      "",
      () => gallery.closeAssets(),
      "character-assets-dismiss",
    );
    dismiss.setAttribute("aria-label", "关闭角色资产");
    const cards = el("div", "character-assets-cards");
    const slots = CharacterDesign.slots(row);
    for (const [kind, label, width] of CharacterDesign.assets) {
      const card = el("article", "character-asset-slot");
      card.style.width = width + "px";
      const url = slots[kind];
      if (url) {
        const view = button(
          "",
          () => preview(detail, url, label),
          "character-asset-image",
        );
        view.setAttribute("aria-label", "预览" + label);
        const img = el("img");
        img.src = url;
        img.alt = row.name + " · " + label;
        img.draggable = false;
        view.append(img);
        img.onerror = () => {
          view.replaceChildren(el("span", "", "图片暂不可用"));
          view.disabled = true;
        };
        card.append(view);
      } else
        card.append(el("div", "character-asset-missing", "尚未生成" + label));
      const actions = el("div", "character-asset-slot-actions");
      actions.append(el("span", "", label));
      const generate = button(url ? "重新生成" : "生成", () =>
        gallery.callbacks.onGenerateAsset(row, kind),
      );
      generate.setAttribute("aria-label", (url ? "重新生成" : "生成") + label);
      actions.append(generate);
      if (url) {
        const download = el("a", "", "下载");
        download.href = url;
        download.download = row.name + "-" + label;
        actions.append(download);
      }
      const assign = el("select");
      assign.setAttribute("aria-label", "指定" + label + "参考图");
      assign.add(new Option("从已有参考图指定…", ""));
      (row.images || []).forEach((ref, index) =>
        assign.add(new Option("参考图 " + (index + 1), ref)),
      );
      assign.onchange = () => {
        if (assign.value)
          gallery.callbacks.onAssignAsset(row, kind, assign.value);
      };
      card.append(actions, assign);
      cards.append(card);
    }
    const close = button(
      "×",
      () => gallery.closeAssets(),
      "character-assets-back",
    );
    close.setAttribute("aria-label", "返回角色库");
    const hint = el(
      "p",
      "character-assets-hint",
      "选择图片可放大预览。生成结果采用后保存，原参考图保留。",
    );
    detail.append(
      dismiss,
      cards,
      close,
      hint,
      el("div", "character-assets-name", row.name),
    );
    const voice = el("div", "character-assets-voice");
    if (row.voice?.url) {
      voice.append(el("span", "", row.voice.voice || "角色音色"));
      const audio = el("audio");
      audio.controls = true;
      audio.src = row.voice.url;
      audio.setAttribute("aria-label", "角色音色试听");
      voice.append(audio);
    } else voice.append(el("span", "", "尚未设置角色音色"));
    const changeVoice = button(row.voice?.url ? "更换音色" : "选择音色", () =>
      gallery.callbacks.onVoice(row),
    );
    voice.append(changeVoice);
    detail.append(voice);
    gallery.body.append(detail);
    gallery.choose(row);
    close.focus();
  }
  function preview(root, url, label) {
    const overlay = el("div", "character-asset-preview");
    overlay.setAttribute("role", "region");
    overlay.setAttribute("aria-label", label + "大图");
    const img = el("img");
    img.src = url;
    img.alt = label;
    const close = button("×", () => overlay.remove());
    close.setAttribute("aria-label", "关闭图片预览");
    overlay.onkeydown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        overlay.remove();
        root.querySelector(".character-assets-back")?.focus();
      }
    };
    overlay.append(close, img);
    root.append(overlay);
    close.focus();
  }
  window.CharacterAssetsView = { open };
})();
