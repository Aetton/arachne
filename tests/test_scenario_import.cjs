const { test } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");
test("import sends one raw YAML request and prevents duplicate submission", async () => {
  const dom = new JSDOM(
    `<button id="scenario-import-open"></button><dialog id="scenario-import-dialog"><form id="scenario-import-form"><input id="scenario-import-file" type="file"><select id="scenario-import-mode"><option value="update">Update</option></select><div id="scenario-import-status"></div><button id="scenario-import-submit"></button><button type="button">Cancel</button></form></dialog>`,
    { url: "http://localhost", runScripts: "outside-only" },
  );
  const w = dom.window,
    d = w.document,
    requests = [];
  let finish;
  w.fetch = (url, options) => {
    requests.push({ url, options });
    return new Promise((resolve) => {
      finish = resolve;
    });
  };
  w.eval(
    fs.readFileSync(
      path.join(__dirname, "../frontend/static/js/scenario-yaml-import.js"),
      "utf8",
    ),
  );
  const input = d.querySelector("input");
  Object.defineProperty(input, "files", {
    value: [
      {
        name: "test.yaml",
        size: 20,
        text: async () => "components:\n  new: {}",
      },
    ],
  });
  input.dispatchEvent(new w.Event("change"));
  await new Promise((r) => setImmediate(r));
  const form = d.querySelector("form");
  form.dispatchEvent(new w.Event("submit", { cancelable: true }));
  form.dispatchEvent(new w.Event("submit", { cancelable: true }));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/admin/scenarios/import?mode=update");
  assert.equal(requests[0].options.body, "components:\n  new: {}");
  assert.equal(input.disabled, true);
  finish({
    ok: false,
    redirected: false,
    json: async () => ({ detail: "Invalid parent" }),
  });
  await new Promise((r) => setImmediate(r));
  assert.equal(input.disabled, false);
  assert.match(
    d.querySelector("#scenario-import-status").textContent,
    /Invalid parent/,
  );
  dom.window.close();
});
