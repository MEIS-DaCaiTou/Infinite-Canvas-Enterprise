"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const values = new Map();
const storage = {
  getItem: (k) => values.get(k),
  setItem: (k, v) => values.set(k, v),
  removeItem: (k) => values.delete(k),
};
const context = vm.createContext({
  window: {},
  crypto: require("node:crypto").webcrypto,
  Uint8Array,
  sessionStorage: storage,
  setTimeout,
  clearTimeout,
});
for (const name of [
  "character-design",
  "character-creation-task",
  "character-asset-batch",
]) {
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../static/js/" + name + ".js"),
      "utf8",
    ),
    context,
  );
  Object.assign(context, context.window);
}
const Batch = context.CharacterAssetBatch;
const requests = [];
let failAt = 2;
let saves = 0;
let saved;
const taskIds = new Map();
const action = {
  row: {
    id: "role",
    name: "Fixture",
    assets: { full_body: "/assets/input/body.png" },
  },
  studio: {
    creation: { task: { owner: "alice" } },
    request: async (url, options) => {
      if (options?.method === "POST") {
        const payload = JSON.parse(options.body);
        assert.equal(payload.n, 1);
        requests.push(payload);
        const id =
          "canvas_img_" + requests.length.toString(16).padStart(32, "0");
        taskIds.set(id, requests.length);
        return { task_id: id };
      }
      const i = taskIds.get(url.split("/").pop());
      if (i === failAt)
        return {
          status: "unknown",
          error: "provider acceptance unknown",
          can_query: false,
          items: [],
        };
      return {
        status: "succeeded",
        items: [{ kind: "image", url: "/assets/output/" + i + ".png" }],
      };
    },
  },
  root: { hidden: false },
  payload: (kind) => ({
    prompt: kind,
    reference_images: [{ url: "/assets/input/body.png" }],
  }),
  onAdopt: async (assets) => {
    saves++;
    saved = assets;
    return true;
  },
  async run(fn) {
    assert.equal(this.working, undefined);
    this.working = true;
    try {
      await fn();
    } catch (e) {
      this.error = e.message;
    } finally {
      this.working = undefined;
    }
  },
};
async function run() {
  let batch = new Batch(action);
  await batch.tick();
  assert.equal(requests.length, 2);
  assert.equal(
    saves,
    0,
    "uncertain second item prevents save and third submission",
  );
  batch.stop();
  batch = new Batch(action);
  await batch.tick();
  assert.equal(
    requests.length,
    2,
    "reopening/querying keeps the first result and unknown receipt",
  );
  assert.throws(() => batch.tasks.expression.archiveUnknown(false), /核对/);
  batch.tasks.expression.archiveUnknown(true);
  failAt = 0;
  await batch.tick();
  assert.equal(
    requests.length,
    4,
    "only the explicitly cleared item and remaining item submit",
  );
  assert.equal(saves, 1);
  assert.equal(saved.portrait, "/assets/output/1.png");
  assert.equal(saved.expression, "/assets/output/3.png");
  action.root.hidden = false;
  batch = new Batch(action);
  await batch.tick();
  assert.equal(requests.length, 4, "saving the same set does not pay again");
  action.row = {
    id: "already-complete",
    name: "Existing",
    assets: {
      full_body: "/assets/input/body.png",
      portrait: "/assets/input/p.png",
      expression: "/assets/input/e.png",
      turnaround: "/assets/input/t.png",
    },
  };
  action.root.hidden = false;
  batch = new Batch(action);
  await batch.tick();
  assert.equal(
    requests.length,
    4,
    "complete typed assets are saved without paid regeneration",
  );
  assert.equal(saved.turnaround, "/assets/input/t.png");
  console.log(
    "character asset set: serial ownership scopes, uncertain stop, explicit restart and completed-item reuse passed",
  );
}
run().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
