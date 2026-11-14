import test from "node:test";
import assert from "node:assert/strict";
import { appendSiteScripts } from "../src/lib/siteScripts.mjs";

function fakeDocument(events, fail = false) {
  const append = placement => script => {
    events.push([placement, script.src, script.dataset.siteScriptScope, script.async]);
    queueMicrotask(() => fail ? script.onerror() : script.onload());
  };
  return {
    createElement: () => ({ dataset: {}, setAttribute(key, value) { this[key] = key === "async" ? true : value; } }),
    head: { appendChild: append("head") }, body: { appendChild: append("body") },
  };
}

test("head precedes body, scripts retain attributes and scope", async () => {
  const events = [];
  await appendSiteScripts({head: [{src: "/first.js"}, {src: "https://example.com/widget.js", async: ""}], body: [{src: "/last.js"}]}, "public", {
    document: fakeDocument(events), isActive: () => true,
    reportFailure: () => assert.fail("unexpected failure"),
  });
  assert.deepEqual(events, [["head", "/first.js", "public", false], ["head", "https://example.com/widget.js", "public", true], ["body", "/last.js", "public", false]]);
});

test("a failed external script does not block following scripts", async () => {
  const events = []; let failures = 0;
  await appendSiteScripts({head: [{src: "/bad.js"}], body: [{src: "/next.js"}]}, "customer", {
    document: fakeDocument(events, true), isActive: () => true, reportFailure: () => failures++,
  });
  assert.equal(failures, 2);
  assert.equal(events[1][1], "/next.js");
});

test("stops loading when scope is no longer active", async () => {
  const events = [];
  await appendSiteScripts({head: [{src: "/first.js"}], body: [{src: "/last.js"}]}, "public", {
    document: fakeDocument(events), isActive: () => events.length === 0, reportFailure() {},
  });
  assert.equal(events.length, 1);
});
