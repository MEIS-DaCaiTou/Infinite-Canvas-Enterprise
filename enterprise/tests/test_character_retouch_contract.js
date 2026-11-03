/* Check adapter values against the recovered engine's actual parameter contract. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pathToFileURL } = require("node:url");
(async () => {
  const root = path.resolve(__dirname, "../..");
  const ctx = vm.createContext({ window: {} });
  vm.runInContext(
    fs.readFileSync(
      path.join(root, "static/js/character-retouch-preview.js"),
      "utf8",
    ),
    ctx,
  );
  const adapter = ctx.window.CharacterRetouchPreview;
  const spec = await import(
    pathToFileURL(
      path.join(root, "static/vendor/liblib-character-retouch/spec.js"),
    )
  );
  for (const [key, mapped] of Object.entries(adapter.mapping)) {
    assert.ok(spec.G[mapped], `engine has no ${mapped}`);
    assert.notEqual(spec.G[mapped].status, "unsupported");
    assert.equal(adapter.minimum(key), spec.G[mapped].min);
    for (const value of [-200, -100, -1, 0, 1, 100, 200, NaN]) {
      const params = adapter.parameters({ [key]: value });
      for (const [name, result] of Object.entries(params)) {
        const def = spec.G[name];
        assert.equal(def.type, "list");
        assert.ok(
          Number.isInteger(result[0]) &&
            result[0] >= def.min &&
            result[0] <= def.max,
          `${key}: ${value}`,
        );
      }
    }
  }
  assert.equal(
    Object.keys(adapter.parameters({ rosy: -57, texture: -28 })).length,
    0,
    "unsupported legacy negatives must not enter the realtime engine",
  );
  assert.equal(adapter.parameters({ eye_angle: 20 }).eye_tilt_right[0], 20);
  assert.equal(adapter.framing("half").transform, "translateY(88px) scale(3.75)");
  assert.equal(adapter.framing("full").transform, "none");
  assert.equal(adapter.framing("half", { imageSize: { width: 0, height: 20 }, crop: {} }).transform,
    adapter.framing("half").transform);
  const position = {imageSize: {width: 800, height: 1200}, crop: {x: 0.4, y: 0.1, width: 0.2, height: 0.15}};
  const matrix = adapter.framing("half", position).transform.match(/-?[\d.]+/g).map(Number);
  const fit = 542 / 1200;
  const centerX = 21 + (425 - 800 * fit) / 2 + 800 * fit * 0.5;
  const centerY = 1200 * fit * 0.175;
  assert.ok(matrix[0] >= 1 && matrix[0] <= 4);
  assert.ok(Math.abs(centerX * matrix[0] + matrix[4] - 233.5) < 0.0001);
  assert.ok(Math.abs(centerY * matrix[3] + matrix[5] - 231) < 0.0001);
  console.log(
    "character retouch: recovered engine parameter names, ranges, types and legacy values passed",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
