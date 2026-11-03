/* Shared character edit vocabulary and prompts. No network or canvas state. */
(function (root) {
  const groups = {
    skin: [
      ["smooth", "质感磨皮"],
      ["beauty", "AI美颜（脸部）"],
      ["texture", "皮肤纹理（脸部）"],
      ["brightness", "皮肤透亮"],
      ["rosy", "皮肤红润"],
      ["whiten", "皮肤美白"],
    ],
    eyes: [
      ["eye_size", "眼睛大小"],
      ["eye_bright", "亮眼"],
      ["eye_distance", "眼距"],
      ["eye_angle", "眼角"],
      ["brow_height", "眉毛高度"],
    ],
    nose: [
      ["nose_size", "鼻子大小"],
      ["nose_width", "鼻翼宽度"],
      ["nose_height", "鼻梁高度"],
    ],
    lips: [
      ["lip_size", "嘴唇厚度"],
      ["lip_width", "嘴巴宽度"],
    ],
    face: [
      ["face_slim", "瘦脸"],
      ["chin", "下巴长度"],
      ["jaw", "下颌宽度"],
      ["forehead", "额头高度"],
      ["cheek", "颧骨"],
    ],
    body: [
      ["chest", "丰胸"],
      ["height", "AI增高"],
      ["posture", "驼背"],
      ["legs", "长腿"],
      ["shoulder", "直角肩"],
      ["head", "小头"],
      ["slim", "瘦身"],
      ["belly", "瘦肚子"],
      ["arms", "瘦手臂"],
      ["hips", "美臀"],
      ["leg_slim", "瘦腿"],
      ["neck_left", "瘦脖子-左"],
      ["neck_right", "瘦脖子-右"],
      ["waist", "美腰"],
      ["neck_length_left", "天鹅颈-左"],
      ["neck_length_right", "天鹅颈-右"],
      ["shoulder_width", "肩膀宽度"],
      ["body", "全身美型"],
    ],
  };
  const names = Object.fromEntries(Object.values(groups).flat());
  Object.assign(names, {
    feature: "纹身与疤痕",
    hair: "发型",
    hair_color: "发色",
    makeup: "妆容",
    lip_color: "唇色",
    outfit: "服装",
    style: "风格",
    fleck: "祛斑祛痘",
  });
  const assets = [
    ["full_body", "全身图", 165],
    ["portrait", "头像", 165],
    ["expression", "表情九宫格", 165],
    ["turnaround", "角色设定图", 391],
  ];
  function slots(row) {
    const result = { ...row.assets };
    if (!result.full_body)
      result.full_body = row.cover_url || row.images?.[0] || "";
    for (let i = 0; i < (row.asset_labels || []).length; i++) {
      const label = row.asset_labels[i],
        url = row.images[i];
      if (!url) continue;
      if (/头像|portrait/i.test(label)) result.portrait ||= url;
      if (/表情|expression/i.test(label)) result.expression ||= url;
      if (/设定|转面|turnaround/i.test(label)) result.turnaround ||= url;
      if (/全身|full.body/i.test(label) && !row.assets?.full_body)
        result.full_body = url;
    }
    return result;
  }
  function prompt(kind, design = {}) {
    const instruction = {
      edit: "编辑参考图中的同一个角色，保持人物身份、五官辨识度与未指定部分。按以下造型要求调整，输出单人完整全身图，头脚完整入镜。",
      full_body:
        "生成参考图中同一角色的单人正面完整全身图，保持人物身份与服装，头脚完整入镜，简洁背景。",
      portrait:
        "生成参考图中同一角色的正面半身头像，保持五官、发型、服装，面部清晰，简洁背景。",
      expression:
        "生成同一角色的3×3表情九宫格：自然、微笑、大笑、惊讶、生气、悲伤、疑惑、害羞、坚定；各格为同一人物面部特写，保持五官身份，不添加文字。",
      turnaround:
        "生成同一角色的角色设定图，横向排版：正面、侧面、背面全身三视图及面部多角度特写，保持人物身份、体型和服装一致，不添加文字。",
    }[kind];
    if (!instruction) throw new Error("未知角色生成类型");
    const values = Object.entries(design.values || {})
      .filter(([, v]) => v !== 0 && v !== "")
      .map(([k, v]) => names[k] + ": " + v)
      .join("；");
    return (
      instruction +
      "\n" +
      (kind === "edit" ? values + "\n" + (design.notes || "") : "") +
      "\n不添加水印。"
    );
  }
  root.CharacterDesign = { groups, names, assets, slots, prompt };
})(typeof window === "undefined" ? globalThis : window);
