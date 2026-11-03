/* Lifecycle adapter for the original face/body preview engine. No provider calls. */
(function () {
  let engine;
  const mapping = {
    smooth: "face_balance_alpha",
    texture: "sharpen_alpha",
    brightness: "skin_hdr_alpha",
    rosy: "skin_red_alpha",
    whiten: "skin_white_alpha",
    eye_size: "eye_trans",
    eye_bright: "bright_eye",
    eye_distance: "eye_distance",
    eye_angle: "eye_tilt_left",
    brow_height: "eyebrow_height",
    nose_size: "scale_nose",
    nose_width: "shrink_nose",
    nose_height: "bridge_nose",
    lip_size: "mouth_high",
    lip_width: "mouth_breadth",
    face_slim: "narrow_face",
    chin: "jaw_trans",
    jaw: "mandible",
    forehead: "face_forehead",
    cheek: "cheekbone",
    chest: "body_shape_chest_enlarge",
    height: "body_shape_heighten",
    legs: "body_shape_lengthen",
    shoulder: "body_shape_right_shoulder",
    head: "body_shape_shrink_head",
    slim: "body_shape_slim",
    belly: "body_shape_slim_belly",
    arms: "body_shape_slim_hand",
    hips: "body_shape_slim_hip",
    leg_slim: "body_shape_slim_leg",
    waist: "body_shape_slim_waist",
    shoulder_width: "body_shape_thin_shoulders",
  };
  const positiveKeys = new Set([
    "smooth",
    "texture",
    "brightness",
    "rosy",
    "whiten",
    "eye_bright",
    "height",
    "legs",
    "shoulder",
    "head",
    "belly",
    "leg_slim",
    "waist",
  ]);
  const minimum = (key) => (positiveKeys.has(key) ? 0 : -100);
  function parameters(values, applied = {}) {
    const result = {};
    for (const [key, mapped] of Object.entries(mapping)) {
      const value = Number(values[key] || 0) - Number(applied[key] || 0);
      const bounded = Number.isFinite(value)
        ? Math.max(minimum(key), Math.min(100, Math.round(value)))
        : 0;
      if (bounded) result[mapped] = [bounded];
    }
    if (result.eye_tilt_left) result.eye_tilt_right = result.eye_tilt_left;
    return result;
  }
  // Framing constants and face-fit math recovered from public module 802379.
  function framing(mode, position) {
    if (mode !== "half") return { transform: "none", transformOrigin: "50% 8%" };
    const image = position?.imageSize, crop = position?.crop;
    if (!image || !crop ||
        ![image.width, image.height, crop.x, crop.y, crop.width, crop.height].every(Number.isFinite) ||
        image.width <= 0 || image.height <= 0 || crop.width <= 0 || crop.height <= 0)
      return { transform: "translateY(88px) scale(3.75)", transformOrigin: "50% 8%" };
    const fit = Math.min(425 / image.width, 542 / image.height);
    const width = image.width * fit, height = image.height * fit;
    const centerX = 21 + (425 - width) / 2 + width * (crop.x + crop.width / 2);
    const centerY = (542 - height) / 2 + height * (crop.y + crop.height / 2);
    const scale = Math.max(1, Math.min(4, 336.24 / (width * crop.width), 374 / (height * crop.height)));
    return { transform: `matrix(${scale}, 0, 0, ${scale}, ${233.5 - centerX * scale}, ${231 - centerY * scale})`, transformOrigin: "0 0" };
  }
  class CharacterRetouchPreview {
    constructor(source, body, onStatus) {
      this.source = source;
      this.body = body;
      this.onStatus = onStatus;
      this.canvas = document.createElement("canvas");
      this.canvas.setAttribute("aria-label", "角色即时预览");
      this.abort = new AbortController();
      this.values = {};
      this.applied = {};
      this.ready = this.load();
    }
    async load() {
      this.onStatus("正在准备即时预览…");
      try {
        const module = await (engine ||= import(
          "../vendor/liblib-character-retouch/preview.js"
        ).catch((error) => {
          engine = null;
          throw error;
        }));
        if (this.abort.signal.aborted) return;
        this.session = await module.createFacePreviewSession({
          sourceUrl: this.source,
          canvas: this.canvas,
          position: {
            sourceImageUrl: this.source,
            crop: { x: 0.29, y: 0, width: 0.42, height: 0.34 },
          },
          includeFace: true,
          includeBody: this.body,
          signal: this.abort.signal,
          onFrame: () => {
            if (this.capture) {
              const { resolve, reject } = this.capture;
              this.capture = null;
              this.canvas.toBlob(
                (blob) =>
                  blob ? resolve(blob) : reject(new Error("无法保存即时预览")),
                "image/png",
              );
            }
          },
          onError: (error) => {
            this.failed = error;
            this.capture?.reject(error);
            this.capture = null;
            this.onStatus("即时预览暂不可用：" + error.message);
          },
        });
        if (this.abort.signal.aborted) {
          this.session.dispose();
          return;
        }
        this.position = this.session.position;
        this.onStatus("");
        this.update(this.values, this.applied);
      } catch (error) {
        if (!this.abort.signal.aborted) {
          this.failed = error;
          this.canvas.dataset.previewError = error.message;
          console.warn("Character immediate preview:", error.message);
          this.onStatus("即时预览暂不可用，请检查图片中是否只有一个清晰人物。");
        }
      }
    }
    update(values, applied = {}) {
      this.values = { ...values };
      this.applied = { ...applied };
      this.session?.update(
        parameters(values, applied),
        this.viewMode || (this.body ? "body" : "face"),
      );
    }
    async export() {
      await this.ready;
      if (!this.session || this.failed)
        throw new Error("即时预览尚未就绪，暂不能保存形变结果。");
      return new Promise((resolve, reject) => {
        if (this.capture) {
          reject(new Error("正在保存即时预览，请稍候。"));
          return;
        }
        this.capture = { resolve, reject };
        this.update(this.values, this.applied);
      });
    }
    destroy() {
      this.abort.abort();
      this.session?.dispose();
      this.canvas.remove();
      this.capture?.reject(new Error("角色预览已关闭"));
      this.capture = null;
    }
  }
  CharacterRetouchPreview.mapping = mapping;
  CharacterRetouchPreview.parameters = parameters;
  CharacterRetouchPreview.minimum = minimum;
  CharacterRetouchPreview.framing = framing;
  window.CharacterRetouchPreview = CharacterRetouchPreview;
})();
