const { test } = require("node:test");
const assert = require("node:assert");
const { mask } = require("../rules.js");

test("phone masked", () => {
  const r = mask("call 13800138000 now");
  assert.strictEqual(r.count, 1);
  assert.ok(r.text.includes("[PHONE_1]"));
  assert.ok(!r.text.includes("13800138000"));
});

test("idcard checksum", () => {
  assert.strictEqual(mask("id 11010519491231002X").count, 1);
  assert.strictEqual(mask("id 110105194912310021").count, 0);
});

test("bankcard luhn + BIN", () => {
  assert.strictEqual(mask("card 4111111111111111").count, 1);
  assert.strictEqual(mask("card 4111111111111112").count, 0);
  assert.strictEqual(mask("order 9999999999999995").count, 0);
});

test("email + ipv4", () => {
  const r = mask("mail a@b.co ip 10.0.0.5");
  assert.strictEqual(r.count, 2);
});

test("private key block", () => {
  const k = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----";
  const r = mask(k);
  assert.strictEqual(r.count, 1);
  assert.ok(r.text.includes("[PRIVKEY_1]"));
});

test("assignment secret whole-line bare value", () => {
  const r = mask('pwd: ab#cd ef\nnext: 1');
  assert.strictEqual(r.count, 1);
  assert.ok(r.text.includes("[SECRET_1]"));
  assert.ok(!r.text.includes("ab#cd"));
});

test("jinja reference skipped", () => {
  assert.strictEqual(mask('pwd: "{{ base_pwd }}"').count, 0);
});

test("clean text untouched", () => {
  const r = mask("hello world");
  assert.strictEqual(r.count, 0);
  assert.strictEqual(r.text, "hello world");
});

test("entries carry originals for mapping", () => {
  const r = mask("call 13800138000");
  assert.strictEqual(r.entries[0].original, "13800138000");
  assert.strictEqual(r.entries[0].placeholder, "[PHONE_1]");
});