import assert from "node:assert/strict";
import test from "node:test";
import { base64Url, shareBytes, shareUrlAt, fileStem } from "../src/files";

test("Quickshare base64 round trips each padding length", () => {
  for (const input of [new Uint8Array([255]), new Uint8Array([255, 254]), new Uint8Array([255, 254, 253])]) {
    assert.deepEqual(shareBytes(`https://example.org/playbook/#v1/${base64Url(input)}`), input);
  }
});

test("Quickshare links reject noncanonical padding and unsupported envelopes", () => {
  for (const link of ["#v1/_x", "#v1/a", "#v1/Zg==", "#v2/Zg", "#v1/+w", "#v1/"]) assert.throws(() => shareBytes(link));
});

test("download names cannot contain path components", () => {
  assert.equal(fileStem("../A:B.sav"), "..-A-B");
  assert.equal(fileStem(""), "playbook");
});

test("share links retain a GitHub Pages project directory", () => {
  const bytes = new Uint8Array([1, 2, 3]);
  for (const page of [
    "https://example.github.io/gridiron-playbook/",
    "https://example.github.io/gridiron-playbook/index.html?draft=1#v1/old",
  ]) {
    assert.equal(shareUrlAt(bytes, page, "./"), "https://example.github.io/gridiron-playbook/#v1/AQID");
  }
});
