const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const source = readFileSync(join(__dirname, "../app/api-error.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const sandbox = { exports: {} };
runInNewContext(compiled, sandbox);
const { formatApiError } = sandbox.exports;

test("validation errors render as field messages without exposing input or ctx", () => {
  const detail = [
    { type: "string_too_short", loc: ["body", "name"], msg: "String should have at least 2 characters", input: "A", ctx: { min_length: 2 } },
    { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters", input: "secret", ctx: { min_length: 8 } },
  ];
  const message = formatApiError(detail);
  assert.equal(message, "Full name: String should have at least 2 characters Password: String should have at least 8 characters");
  const html = renderToStaticMarkup(React.createElement("b", { role: "alert" }, message));
  assert.match(html, /Full name:/);
  assert.match(html, /Password:/);
  assert.doesNotMatch(html, /secret|string_too_short|min_length/);
});

test("existing HTTP error strings and clearing errors still work", () => {
  assert.equal(formatApiError("Email already registered"), "Email already registered");
  assert.equal(formatApiError(""), "");
});

test("malformed errors always produce renderable fallback text", () => {
  for (const detail of [null, undefined, {}, [], 42, { msg: { unexpected: true } }]) {
    assert.equal(typeof formatApiError(detail), "string");
    assert.ok(formatApiError(detail));
  }
});
