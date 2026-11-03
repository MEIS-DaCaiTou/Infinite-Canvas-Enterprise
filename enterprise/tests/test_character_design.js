"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const ctx = vm.createContext({});
vm.runInContext(
  fs.readFileSync(
    path.join(__dirname, "../../static/js/character-design.js"),
    "utf8",
  ),
  ctx,
);
const design = ctx.CharacterDesign;
const legacy = {
  images: ["/assets/input/body.png", "/assets/input/portrait.png"],
  asset_labels: ["全身图", "头像"],
};
assert.equal(design.slots(legacy).portrait, legacy.images[1]);
assert.equal(
  design.slots({ images: ["/a.png"] }).expression,
  undefined,
  "extra references cannot silently become generated categories",
);
assert.equal(
  design.slots({ ...legacy, assets: { portrait: "/assets/output/new.png" } })
    .portrait,
  "/assets/output/new.png",
);
assert.match(
  design.prompt("edit", {
    values: { smooth: 25, hair: "长直发" },
    notes: "保留服装",
  }),
  /质感磨皮: 25.*发型: 长直发/s,
);
assert.match(design.prompt("expression"), /3×3/);
assert.match(design.prompt("turnaround"), /三视图/);
assert.throws(() => design.prompt("unknown"), /未知/);
console.log(
  "character design: typed legacy mapping, generated category identity and prompt contracts passed",
);

assert.equal(
  design.slots({
    ...legacy,
    assets: { full_body: "/assets/output/adopted.png" },
  }).full_body,
  "/assets/output/adopted.png",
);
