/* Creation is a client of the existing owned task journal, never a second queue.
 * Pending receipts are cached per authenticated account for this browser tab.
 * Neither refresh nor recovery calls the generation endpoint again. */
(function (root) {
  const id = () => {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
  };
  const pending = (state) =>
    state && !["saved", "failed", "cancelled"].includes(state.stage);
  class CharacterCreationTask {
    constructor(request, storage) {
      this.request = request;
      this.storage = storage;
      this.state = null;
      this.owner = "";
      this.busy = false;
    }
    setOwner(owner) {
      if (owner === this.owner) return;
      this.owner = owner;
      this.state = null;
      if (!owner) return;
      try {
        const value = JSON.parse(this.storage.getItem(this.key()) || "null");
        if (
          value?.owner === owner &&
          /^[a-f0-9]{32}$/.test(value.createId) &&
          typeof value.prompt === "string" &&
          value.prompt.length <= 2000
        )
          this.state = value;
      } catch (_) {
        /* An unavailable cache must never cause resubmission. */
      }
    }
    key() {
      return "character-creation-v1:" + this.owner;
    }
    store() {
      // Before paid submission this must succeed, so its uncertain receipt can
      // survive navigation. After acceptance the server journal remains truth.
      this.storage.setItem(this.key(), JSON.stringify(this.state));
    }
    async submit(payload, description = payload.prompt) {
      if (this.busy || pending(this.state))
        throw new Error("请先核对原角色任务，不能重复提交。");
      if (!this.owner) throw new Error("请先登录后创建角色");
      this.busy = true;
      const owner = this.owner;
      try {
        this.state = {
          owner,
          createId: id(),
          prompt: description,
          stage: "submitting",
          taskId: "",
        };
        try {
          this.store();
        } catch (_) {
          this.state = null;
          throw new Error(
            "浏览器暂不能保存任务回执，请恢复会话存储后再生成；本次未提交。",
          );
        }
        let accepted;
        try {
          accepted = await this.request("/api/canvas-image-tasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...payload, n: 1 }),
          });
        } catch (error) {
          if (owner !== this.owner) throw error;
          this.state.stage = [400, 401, 403, 404, 413, 422, 429].includes(
            error.status,
          )
            ? "failed"
            : "unknown";
          this.state.error =
            this.state.stage === "unknown"
              ? "受理结果待核对，请在日志的生成任务中查找原任务；不会自动重试。"
              : error.message;
          this.store();
          throw new Error(this.state.error);
        }
        if (owner !== this.owner)
          throw new Error("登录身份已变化，请在原账号的生成任务中核对");
        this.state.taskId = accepted.task_id || "";
        this.state.stage = this.state.taskId ? "queued" : "unknown";
        this.store();
        if (!this.state.taskId)
          throw new Error(
            "受理回执缺少编号，请在生成任务中核对；不会重新提交。",
          );
        return this.state;
      } finally {
        this.busy = false;
      }
    }
    async refresh() {
      const state = this.state,
        owner = this.owner;
      if (!state?.taskId)
        throw new Error(
          "请在日志的生成任务中核对受理记录，然后填入原任务编号。",
        );
      // This endpoint verifies ownership and registers only verified output URLs.
      const task = await this.request(
        "/enterprise/api/me/generation-tasks/" +
          encodeURIComponent(state.taskId),
      );
      if (owner !== this.owner || state !== this.state) return null;
      state.stage = task.status;
      state.error = task.error || "";
      state.source = task.call_source;
      state.images = [
        ...new Set(
          (task.items || [])
            .filter((item) => item.kind === "image")
            .map((item) => item.url),
        ),
      ].slice(0, 12);
      if (state.images.length) state.stage = "result";
      else if (state.stage === "succeeded") {
        state.stage = "unknown";
        state.error =
          "原任务已结束，但没有可保存的图片，请在生成任务详情中核对。";
      }
      this.store();
      return task;
    }
    async attach(taskId) {
      const state = this.state,
        owner = this.owner;
      if (
        !this.state ||
        this.state.taskId ||
        !/^canvas_img_[a-f0-9]{32}$/.test(taskId)
      )
        throw new Error("请输入日志中本人原 API 图片任务的完整编号");
      const task = await this.request(
        "/enterprise/api/me/generation-tasks/" + encodeURIComponent(taskId),
      );
      if (owner !== this.owner || state !== this.state)
        throw new Error("登录身份已变化，请重新核对原任务");
      if (task.type !== "online-image")
        throw new Error("请选择本人原 API 图片任务");
      this.state.taskId = taskId;
      this.store();
    }
    async save(profile) {
      if (this.busy) return;
      const state = this.state,
        owner = this.owner;
      if (state?.stage !== "result" || !state.images?.length)
        throw new Error("请先取得原任务的可用图片");
      this.busy = true;
      try {
        const saved = await this.request("/enterprise/api/me/characters", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...profile,
            images: state.images,
            create_request_id: state.createId,
          }),
        });
        if (owner === this.owner && state === this.state) {
          state.stage = "saved";
          this.store();
        }
        return saved;
      } finally {
        this.busy = false;
      }
    }
    canGenerate() {
      return !this.busy && !pending(this.state);
    }
  }
  root.CharacterCreationTask = CharacterCreationTask;
})(typeof window === "undefined" ? globalThis : window);
