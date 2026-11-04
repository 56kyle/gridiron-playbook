import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import test from "node:test";
import { initSync, apply_edit, inspect_document, new_document, transfer_plays } from "../src/wasm/gridiron_wasm.js";
import type { DocumentView, TransferredPlays } from "../src/types";
import { Workspace } from "../src/workspace";
import type { WorkspaceEngine } from "../src/workspace";

initSync({
  module: new WebAssembly.Module(readFileSync(new URL("../src/wasm/gridiron_wasm_bg.wasm", import.meta.url))),
});
const api: WorkspaceEngine = {
  inspectDocument: async (document) => JSON.parse(inspect_document(document)) as DocumentView,
  applyEdit: async (document, command) => apply_edit(document, JSON.stringify(command)),
  transferPlays: async (source, target, indices, insertion, mode) =>
    JSON.parse(transfer_plays(source, target, JSON.stringify(indices), insertion, mode)) as TransferredPlays,
};
function book(names: string[]): string {
  return [...names]
    .reverse()
    .reduce(
      (document, play_name) =>
        apply_edit(document, JSON.stringify({ type: "create_play", formation_name: "Twins Right", play_name })),
      new_document()
    );
}
function names(workspace: Workspace): string[] {
  return workspace.active?.view.plays.map((play) => play.play_name) ?? [];
}

test("create and duplicate prepend while history retains the original download baseline", async () => {
  const workspace = new Workspace(api);
  const original = book(["First", "Second"]);
  const tab = await workspace.open(original, "book.sav");
  await workspace.edit({ type: "create_play", formation_name: "Twins Left", play_name: "New" }, [0]);
  await workspace.edit({ type: "duplicate_play", play_index: 2, play_name: "Copy" }, [0]);
  assert.deepEqual(names(workspace), ["Copy", "New", "First", "Second"]);
  assert.equal(tab.savedDocument, original);
  await workspace.undo();
  await workspace.undo();
  assert.equal(tab.document, original);
});

test("cross-book move is one undo transaction and reopens a closed affected book", async () => {
  const workspace = new Workspace(api);
  const source = await workspace.open(book(["A", "B", "C"]), "source.sav");
  const destination = await workspace.open(book(["D"]), "target.sav");
  await workspace.transfer(source.id, destination.id, [0, 2], 0, "move");
  assert.deepEqual(names(workspace), ["A", "C", "D"]);
  assert.deepEqual(
    source.view.plays.map((play) => play.play_name),
    ["B"]
  );
  workspace.close(source.id);
  const unrelated = await workspace.open(book(["Other"]), "other.sav");
  await workspace.undo();
  assert.deepEqual(
    workspace.tabs.find((tab) => tab.id === source.id)?.view.plays.map((play) => play.play_name),
    ["A", "B", "C"]
  );
  assert.deepEqual(
    destination.view.plays.map((play) => play.play_name),
    ["D"]
  );
  assert.equal(workspace.activeId, unrelated.id);
  await workspace.redo();
  assert.deepEqual(
    destination.view.plays.map((play) => play.play_name),
    ["A", "C", "D"]
  );
});

test("copy preserves source and same-book reordering preserves selected source order", async () => {
  const workspace = new Workspace(api);
  const source = await workspace.open(book(["A", "B", "C", "D"]), "source.sav");
  const original = source.document;
  const target = await workspace.open(book(["X"]), "target.sav");
  await workspace.transfer(source.id, target.id, [3, 1], 0, "copy");
  assert.equal(source.document, original);
  assert.deepEqual(names(workspace), ["B", "D", "X"]);
  await workspace.transfer(target.id, target.id, [0, 1], 3, "move");
  assert.deepEqual(names(workspace), ["X", "B", "D"]);
  assert.deepEqual(target.selection, [1, 2]);
});

test("failed transfer changes neither book nor undo history", async () => {
  const workspace = new Workspace(api);
  const source = await workspace.open(book(["A"]), "source.sav");
  const target = await workspace.open(book(["B"]), "target.sav");
  const before = workspace.serialize();
  await assert.rejects(workspace.transfer(source.id, target.id, [2], 0, "move"));
  assert.equal(workspace.serialize(), before);
  assert.equal(workspace.canUndo, false);
});

test("same-book copy inserts duplicates without moving the original plays", async () => {
  const workspace = new Workspace(api);
  const tab = await workspace.open(book(["A", "B", "C"]), "book.sav");
  await workspace.transfer(tab.id, tab.id, [0, 2], 1, "copy");
  assert.deepEqual(names(workspace), ["A", "A", "C", "B", "C"]);
  assert.deepEqual(tab.selection, [1, 2]);
  await workspace.undo();
  assert.deepEqual(names(workspace), ["A", "B", "C"]);
});

test("a new edit after undo invalidates redo", async () => {
  const workspace = new Workspace(api);
  await workspace.open(book(["A"]), "book.sav");
  await workspace.edit({ type: "rename_play", play_index: 0, play_name: "B" });
  await workspace.undo();
  assert.equal(workspace.canRedo, true);
  await workspace.edit({ type: "rename_play", play_index: 0, play_name: "C" });
  assert.equal(workspace.canRedo, false);
  assert.deepEqual(names(workspace), ["C"]);
});

test("workspace recovery preserves opaque docs, dirty baseline, selected tab and unfinished route", async () => {
  const workspace = new Workspace(api);
  const original = `${book(["A"])}\n`;
  const first = await workspace.open(original, "first.sav");
  const last = await workspace.open(book(["B"]), "last.sav");
  await workspace.edit({ type: "rename_play", play_index: 0, play_name: "Edited" });
  last.draft = { slot: 5, points: [{ x: 12.5, y: 20, z: 0 }] };
  last.search = "Edited";
  const restored = new Workspace(api);
  await restored.restore(workspace.serialize());
  assert.equal(restored.tabs[0]?.document, first.document);
  assert.equal(restored.tabs[0]?.savedDocument, original);
  assert.equal(restored.activeId, last.id);
  assert.deepEqual(restored.active?.draft, last.draft);
  assert.equal(restored.active?.savedDocument, last.savedDocument);
  assert.equal(restored.active?.search, "Edited");
  assert.equal(restored.canUndo, false);
  assert.equal(restored.canRedo, false);
});

test("invalid recovered tab identities leave an existing workspace intact", async () => {
  const workspace = new Workspace(api);
  await workspace.open(book(["A"]), "book.sav");
  const before = workspace.serialize();
  const duplicate = JSON.parse(before) as { version: number; tabs: unknown[]; activeId: string };
  duplicate.tabs.push(duplicate.tabs[0]);
  await assert.rejects(workspace.restore(JSON.stringify(duplicate)));
  assert.equal(workspace.serialize(), before);
});

test("invalid recovered documents are rejected before any tab is replaced", async () => {
  const workspace = new Workspace(api);
  await workspace.open(book(["A"]), "book.sav");
  const before = workspace.serialize();
  const invalid = JSON.parse(before) as { tabs: { document: string }[] };
  invalid.tabs[0]!.document = "{}";
  await assert.rejects(workspace.restore(JSON.stringify(invalid)));
  assert.equal(workspace.serialize(), before);
});

test("changing the download baseline does not falsely mark subsequent edits saved", async () => {
  const workspace = new Workspace(api);
  const tab = await workspace.open(book(["A"]), "book.sav");
  const download = tab.document;
  await workspace.edit({ type: "rename_play", play_index: 0, play_name: "B" });
  workspace.markSaved(tab.id, download);
  assert.notEqual(tab.document, tab.savedDocument);
});

test("transfer and import cannot discard a route draft in a destination tab", async () => {
  const workspace = new Workspace(api);
  const destination = await workspace.open(book(["Target"]), "target.sav");
  destination.draft = { slot: 5, points: [{ x: 300, y: 800, z: 0 }] };
  const source = await workspace.open(book(["Source"]), "source.sav");
  const before = workspace.serialize();
  await assert.rejects(workspace.transfer(source.id, destination.id, [0], 0, "copy"));
  await assert.rejects(workspace.replace(destination.id, book(["Replacement"])));
  assert.equal(workspace.serialize(), before);
  assert.equal(workspace.canUndo, false);
});

test("undo cannot discard an unfinished draft in an inactive affected tab", async () => {
  const workspace = new Workspace(api);
  const tab = await workspace.open(book(["A"]), "edited.sav");
  await workspace.edit({ type: "rename_play", play_index: 0, play_name: "B" });
  tab.draft = { slot: 5, points: [{ x: 300, y: 800, z: 0 }] };
  await workspace.open(book(["Unrelated"]), "other.sav");
  const before = workspace.serialize();
  await assert.rejects(workspace.undo());
  assert.equal(workspace.serialize(), before);
  assert.equal(workspace.canUndo, true);
  tab.draft = null;
  await workspace.undo();
  assert.equal(tab.view.plays[0]?.play_name, "A");
});
