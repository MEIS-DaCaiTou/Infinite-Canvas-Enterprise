"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({
  window: {},
  File,
  Blob,
  FormData,
  structuredClone,
});
for (const name of [
  "character-design",
  "character-retouch-preview",
  "character-editor-view",
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
const fixture = () => {
  const row = {
    assets: {
      full_body: "/assets/input/original.png",
      portrait: "/assets/input/old-portrait.png",
    },
    design: { version: 1, values: { eye_size: 40 } },
  };
  let uploads = 0;
  const editor = Object.create(context.CharacterEditorView.prototype);
  Object.assign(editor, {
    editToken: Symbol(),
    original: structuredClone(row),
    studio: {
      draft: row,
      request: async () => {
        uploads++;
        return { files: [{ kind: "image", url: "/assets/input/edited.png" }] };
      },
    },
    preview: {
      export: async () => new Blob(["fixture pixels"], { type: "image/png" }),
    },
  });
  return { editor, row, uploads: () => uploads };
};
(async () => {
  let { editor, row, uploads } = fixture();
  await editor.preparePreview();
  assert.equal(row.assets.full_body, "/assets/input/edited.png");
  assert.equal(row.design.preview_source, "/assets/input/original.png");
  assert.equal(
    row.assets.portrait,
    undefined,
    "old categories cannot describe changed pixels",
  );
  await editor.preparePreview();
  assert.equal(uploads(), 1, "unchanged save reuses the baked result");
  row.design.values.eye_size = 0;
  await editor.preparePreview();
  assert.equal(
    row.assets.full_body,
    "/assets/input/original.png",
    "neutral parameters restore original pixels",
  );
  assert.equal(uploads(), 1, "restoring the original needs no extra upload");
  ({ editor, row, uploads } = fixture());
  editor.preview.export = async () => {
    editor.studio.draft = structuredClone(row);
    return new Blob(["old"]);
  };
  await assert.rejects(editor.preparePreview(), /已变化/);
  assert.equal(uploads(), 0, "a replaced draft cannot receive a stale preview");
  ({ editor, row, uploads } = fixture());
  editor.studio.request = async () => {
    editor.studio.draft = structuredClone(row);
    return { files: [{ kind: "image", url: "/assets/input/late.png" }] };
  };
  await assert.rejects(editor.preparePreview(), /旧预览/);
  assert.equal(
    editor.studio.draft.assets.full_body,
    "/assets/input/original.png",
  );
  console.log(
    "character editor: changed pixels, no duplicate upload, neutral restore and stale draft protection passed",
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
