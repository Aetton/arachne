const { test } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");
const template = fs.readFileSync(
  path.join(__dirname, "../frontend/templates/dashboard.html"),
  "utf8",
);
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise((resolve) => setTimeout(resolve, 15));
test("search temporarily opens ancestors without overwriting saved collapse state", async () => {
  const dom = new JSDOM(
    `<input id="scenario-search"><details class="scenario-group" data-component="root"><summary><span class="scenario-group-count"></span></summary><details class="scenario-group" data-component="child"><summary><span class="scenario-group-count"></span></summary><button class="scenario-card" data-search="build"></button></details></details>`,
    { url: "http://localhost", runScripts: "outside-only" },
  );
  const w = dom.window,
    d = w.document;
  w.localStorage.setItem("arachne-component-open:root", "false");
  w.localStorage.setItem("arachne-component-open:child", "false");
  w.eval(script);
  await settle();
  const search = d.querySelector("input");
  search.value = "build";
  search.dispatchEvent(new w.Event("input"));
  await settle();
  assert.ok(
    [...d.querySelectorAll("details")].every((g) => g.open && !g.hidden),
  );
  assert.equal(w.localStorage.getItem("arachne-component-open:root"), "false");
  search.value = "";
  search.dispatchEvent(new w.Event("input"));
  await settle();
  assert.ok([...d.querySelectorAll("details")].every((g) => !g.open));
  assert.equal(w.localStorage.getItem("arachne-component-open:child"), "false");
  dom.window.close();
});
