<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import * as engine from "./engine";
import type { EditCommand, Formation, Play, Point, ShareKind } from "./types";
import { Workspace } from "./workspace";
import { openWorkspace, type WorkspaceSession } from "./storage";
import { prepareInstall, prepareRestore, GameFileError, type PreparedGameChange } from "./gameFiles";
import { hasGameDirectoryAccess, readSavedGameDirectory, supportsGameFiles } from "./gameDirectory";
import { downloadBytes, fileStem, MAX_OPEN_BYTES, message, shareBytes } from "./files";
import DialogFrame from "./components/DialogFrame.vue";
import PlayLibrary from "./components/PlayLibrary.vue";
import PlayField from "./components/PlayField.vue";
import PlayInspector from "./components/PlayInspector.vue";
import ShareDialog from "./components/ShareDialog.vue";
import SharePreview from "./components/SharePreview.vue";
import GameDialog from "./components/GameDialog.vue";
import GameFolderDialog from "./components/GameFolderDialog.vue";

const workspace = reactive(new Workspace());
const formations = ref<Formation[]>([]);
const active = computed(() => workspace.active);
const play = computed(() => workspace.play);
const formation = computed(() => formations.value.find((value) => value.name === play.value?.formation_name));
const busy = ref(false);
const ready = ref(false);
const notice = ref("");
const error = ref("");
const recovery = ref<"loading" | "saved" | "saving" | "failed">("loading");
const recoveryError = ref("");
const rawRecovery = ref("");
let session: WorkspaceSession | undefined;
let saveGeneration = 0;
const fileInput = ref<HTMLInputElement>();
const field = ref<InstanceType<typeof PlayField>>();
const newPlay = ref<{ duplicate: boolean; name: string; formation: string } | null>(null);
const transfer = ref<{ mode: "copy" | "move" | "merge"; destination: string } | null>(null);
const share = ref<{ document: string; indices: number[]; kind: ShareKind; name: string } | null>(null);
const importLink = ref<string | null>(null);
interface IncomingShare {
  id: string;
  bytes: Uint8Array;
  plays: Play[];
  kind: ShareKind;
  name: string;
}
const incomingQueue = ref<IncomingShare[]>([]);
const incoming = computed((): IncomingShare | null => incomingQueue.value[0] ?? null);
const help = ref(false);
const confirmation = ref<{ title: string; text: string; action: string; resolve: (accepted: boolean) => void } | null>(
  null
);
type GameAction = { kind: "choose" } | { kind: "install"; document: string } | { kind: "restore" };
const gameDirectory = shallowRef<FileSystemDirectoryHandle | null>(null);
const gameFolderReady = ref(false);
const gameFolderProblem = ref("");
const gameFolderAction = shallowRef<GameAction | null>(null);
const gameChange = ref<{ change: PreparedGameChange; restoring: boolean } | null>(null);
const gameApplying = ref(false);
const dragged = ref<{ source: string; indices: number[]; document: string } | null>(null);

function confirm(title: string, text: string, action: string): Promise<boolean> {
  return new Promise((resolve) => {
    confirmation.value = { title, text, action, resolve };
  });
}
function answer(accepted: boolean): void {
  const pending = confirmation.value;
  confirmation.value = null;
  pending?.resolve(accepted);
}
async function run(operation: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await operation();
  } catch (cause) {
    if (!(cause instanceof GameFileError && cause.code === "cancelled")) error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

watch(
  () => workspace.serialize(),
  (data) => {
    if (!ready.value || !session) return;
    recovery.value = "saving";
    const generation = ++saveGeneration;
    void session
      .save(data)
      .then(() => {
        if (generation === saveGeneration) {
          recovery.value = "saved";
          recoveryError.value = "";
        }
      })
      .catch((cause) => {
        recovery.value = "failed";
        recoveryError.value = message(cause);
      });
  }
);

async function createBook(): Promise<void> {
  await run(async () => {
    const count = workspace.tabs.filter((tab) => tab.name.startsWith("Untitled")).length;
    await workspace.open(await engine.newDocument(), count ? `Untitled ${count + 1}.sav` : "Untitled.sav");
  });
}

function openNewPlay(duplicate = false): void {
  newPlay.value = {
    duplicate,
    name: duplicate ? `${play.value?.play_name ?? "Play"} copy` : "New play",
    formation: play.value?.formation_name ?? formations.value[0]?.name ?? "Twins Right",
  };
}
async function submitPlay(): Promise<void> {
  const form = newPlay.value;
  if (!form || !active.value) return;
  await run(async () => {
    await workspace.edit(
      form.duplicate
        ? { type: "duplicate_play", play_index: active.value!.selection[0]!, play_name: form.name }
        : { type: "create_play", formation_name: form.formation, play_name: form.name },
      [0]
    );
    active.value!.selectedRoute = null;
    active.value!.draft = null;
    newPlay.value = null;
  });
}
async function edit(command: EditCommand): Promise<void> {
  await run(() => workspace.edit(command));
}
function playEdit(type: "rename_play" | "change_formation" | "flip_play" | "clear_routes", value?: string): void {
  if (!active.value || !play.value) return;
  const play_index = active.value.selection[0]!;
  void edit(
    type === "rename_play"
      ? { type, play_index, play_name: value ?? "" }
      : type === "change_formation"
      ? { type, play_index, formation_name: value ?? "" }
      : { type, play_index }
  );
}
function routeEdit(
  type: "move_point" | "insert_point" | "delete_point" | "add_block" | "delete_route",
  point_index?: number,
  point?: Point
): void {
  const tab = active.value;
  if (!tab || tab.selectedRoute === null) return;
  const base = { play_index: tab.selection[0]!, route_index: tab.selectedRoute };
  if (type === "delete_route") {
    void edit({ type, ...base });
    return;
  }
  if (point_index === undefined) return;
  if (type === "move_point" || type === "insert_point") {
    if (point) void edit({ type, ...base, point_index, x: point.x, y: point.y });
  } else void edit({ type, ...base, point_index });
}
function draw(slot: number): void {
  if (!active.value || busy.value) return;
  active.value.draft = { slot, points: [] };
  active.value.selectedRoute = null;
}
function draft(points: Point[]): void {
  if (active.value?.draft) active.value.draft.points = points;
}
async function finishRoute(): Promise<void> {
  const tab = active.value;
  if (!tab?.draft) return;
  const snapshot = tab.draft,
    play_index = tab.selection[0]!;
  await run(async () => {
    const route = tab.view.plays[play_index]!.routes.length;
    await workspace.edit({ type: "add_route", play_index, slot: snapshot.slot, points: snapshot.points });
    tab.draft = null;
    tab.selectedRoute = route;
  });
}
async function closeTab(id: string): Promise<void> {
  const tab = workspace.tabs.find((value) => value.id === id);
  if (!tab) return;
  if (
    (tab.document !== tab.savedDocument || tab.draft) &&
    !(await confirm("Close playbook?", `${tab.name} has changes that have not been downloaded.`, "Close playbook"))
  )
    return;
  workspace.close(id);
}
function selectPlay(index: number, extend: boolean, toggle: boolean): void {
  if (busy.value) return;
  if (active.value?.draft) {
    error.value = "Finish or cancel the route before selecting another play.";
    return;
  }
  workspace.select(index, extend, toggle);
}
function showTransfer(mode: "copy" | "move" | "merge"): void {
  transfer.value = { mode, destination: workspace.tabs.find((tab) => tab.id !== active.value?.id)?.id ?? "" };
}
const transferTitle = computed(() =>
  transfer.value?.mode === "merge" ? "Merge playbook" : transfer.value?.mode === "move" ? "Move plays" : "Copy plays"
);
async function submitTransfer(): Promise<void> {
  const action = transfer.value,
    source = active.value;
  if (!action || !source) return;
  await run(async () => {
    await workspace.transfer(
      source.id,
      action.destination,
      action.mode === "merge" ? source.view.plays.map((_, index) => index) : source.selection,
      0,
      action.mode === "move" ? "move" : "copy"
    );
    transfer.value = null;
  });
}
async function reorder(direction: -1 | 1): Promise<void> {
  const tab = active.value;
  if (!tab?.selection.length) return;
  const insertion = direction === -1 ? tab.selection[0]! - 1 : tab.selection.at(-1)! + 2;
  await run(() => workspace.transfer(tab.id, tab.id, tab.selection, insertion, "move"));
}
function beginDrag(event: DragEvent, index: number): void {
  const tab = active.value;
  if (!tab || busy.value || tab.draft || !event.dataTransfer) {
    event.preventDefault();
    return;
  }
  dragged.value = {
    source: tab.id,
    indices: tab.selection.includes(index) ? [...tab.selection] : [index],
    document: tab.document,
  };
  event.dataTransfer.effectAllowed = "copyMove";
  event.dataTransfer.setData("application/x-gridiron-plays", "plays");
}
function dragOver(event: DragEvent): void {
  if (!dragged.value) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = event.ctrlKey || event.metaKey ? "copy" : "move";
}
async function drop(event: DragEvent, target: string, insertion: number): Promise<void> {
  const source = dragged.value;
  dragged.value = null;
  if (!source || busy.value) return;
  event.preventDefault();
  if (workspace.tabs.find((tab) => tab.id === source.source)?.document !== source.document) {
    error.value = "The source playbook changed. Drag the plays again.";
    return;
  }
  await run(() =>
    workspace.transfer(
      source.source,
      target,
      source.indices,
      insertion,
      event.ctrlKey || event.metaKey ? "copy" : "move"
    )
  );
}
function tabKey(event: KeyboardEvent, index: number): void {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const destination =
    event.key === "Home"
      ? 0
      : event.key === "End"
      ? workspace.tabs.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : workspace.tabs.length - 1)) % workspace.tabs.length;
  workspace.activate(workspace.tabs[destination]!.id);
  requestAnimationFrame(() => document.querySelector<HTMLElement>("[role=tab][aria-selected=true]")?.focus());
}

async function preview(bytes: Uint8Array, name = "Shared playbook"): Promise<void> {
  const snapshot = await engine.inspectShare(bytes);
  incomingQueue.value.push({ id: crypto.randomUUID(), bytes, kind: snapshot.kind, plays: snapshot.plays, name });
}
function removeIncoming(id: string): void {
  incomingQueue.value = incomingQueue.value.filter((value) => value.id !== id);
}
function dismissIncoming(id: string): void {
  if (!busy.value) removeIncoming(id);
}
async function files(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const chosen = [...(input.files ?? [])];
  input.value = "";
  await run(async () => {
    for (const file of chosen) {
      if (file.size > MAX_OPEN_BYTES) throw new Error(`${file.name} exceeds the 64 MiB file limit.`);
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (/\.gridironshare$/i.test(file.name)) await preview(bytes, fileStem(file.name));
      else {
        const document = /\.json$/i.test(file.name)
          ? new TextDecoder("utf-8", { fatal: true }).decode(bytes)
          : await engine.decodeSave(bytes);
        await engine.validateDocument(document);
        await workspace.open(document, `${fileStem(file.name)}.sav`);
      }
    }
  });
}
async function previewLink(): Promise<void> {
  if (!importLink.value) return;
  const link = importLink.value;
  await run(async () => {
    await preview(shareBytes(link));
    importLink.value = null;
  });
}
async function importIncoming(): Promise<void> {
  const value = incoming.value;
  if (!value) return;
  await run(async () => {
    const target = active.value;
    const result = await engine.importShare(target?.document ?? (await engine.newDocument()), value.bytes);
    if (result.kind === "play" && target) await workspace.replace(target.id, result.document, [0]);
    else
      await workspace.open(
        result.document,
        `${fileStem(result.kind === "play" ? value.plays[0]?.play_name ?? value.name : value.name)}.sav`
      );
    removeIncoming(value.id);
    if (location.hash.startsWith("#v1/")) history.replaceState(null, "", location.pathname + location.search);
  });
}
function showShare(kind: ShareKind): void {
  const tab = active.value;
  if (!tab) return;
  share.value = {
    document: tab.document,
    indices: kind === "play" ? [tab.selection[0]!] : tab.view.plays.map((_, index) => index),
    kind,
    name: kind === "play" ? play.value?.play_name ?? "play" : tab.name,
  };
}
async function download(): Promise<void> {
  const tab = active.value;
  if (!tab) return;
  const document = tab.document;
  await run(async () => {
    downloadBytes(await engine.encodeSave(document), `${fileStem(tab.name)}.sav`);
    workspace.markSaved(tab.id, document);
  });
}
async function loadGameFolder(): Promise<void> {
  try {
    gameDirectory.value = await readSavedGameDirectory();
  } catch {
    gameFolderProblem.value = "The saved game folder could not be loaded. Choose it again.";
  } finally {
    gameFolderReady.value = true;
  }
}
async function prepareGameChange(directory: FileSystemDirectoryHandle, action: GameAction): Promise<void> {
  if (action.kind === "choose") return;
  const change =
    action.kind === "restore"
      ? await prepareRestore(directory)
      : await prepareInstall(directory, await engine.encodeSave(action.document));
  gameChange.value = { change, restoring: action.kind === "restore" };
}
async function requestGame(action: GameAction): Promise<void> {
  if (!gameFolderReady.value) return;
  await run(async () => {
    const directory = gameDirectory.value;
    if (!directory || action.kind === "choose") {
      gameFolderAction.value = action;
      return;
    }
    try {
      if (!(await hasGameDirectoryAccess(directory))) {
        gameFolderProblem.value = "Allow access to the saved folder or choose another.";
        gameFolderAction.value = action;
        return;
      }
      await prepareGameChange(directory, action);
    } catch (cause) {
      if (cause instanceof GameFileError && (cause.code === "unavailable" || cause.code === "permission")) {
        gameFolderProblem.value = message(cause);
        gameFolderAction.value = action;
      } else throw cause;
    }
  });
}
async function gameFolderSelected(directory: FileSystemDirectoryHandle, remembered: boolean): Promise<void> {
  const action = gameFolderAction.value;
  gameDirectory.value = directory;
  gameFolderAction.value = null;
  gameFolderProblem.value = "";
  if (action) await run(() => prepareGameChange(directory, action));
  notice.value = remembered
    ? "Game folder connected"
    : "Game folder connected for this visit. The browser could not remember it.";
}

function keydown(event: KeyboardEvent): void {
  if (busy.value || event.defaultPrevented || event.isComposing || document.querySelector("dialog[open]")) return;
  const target = event.target;
  if (target instanceof HTMLElement && (target.isContentEditable || target.closest("input,textarea,select"))) return;
  if (field.value?.handleKey(event)) return;
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key === "z") {
    event.preventDefault();
    void run(() => (event.shiftKey ? workspace.redo() : workspace.undo()));
  } else if (key === "y") {
    event.preventDefault();
    void run(() => workspace.redo());
  } else if (key === "s") {
    event.preventDefault();
    void download();
  } else if (key === "o") {
    event.preventDefault();
    fileInput.value?.click();
  }
}
function beforeUnload(event: BeforeUnloadEvent): void {
  if (recovery.value === "saving" || recovery.value === "failed" || busy.value || gameApplying.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function downloadRecovery(): void {
  downloadBytes(new TextEncoder().encode(rawRecovery.value), "workspace-recovery.json", "application/json");
}

onMounted(async () => {
  window.addEventListener("keydown", keydown);
  window.addEventListener("beforeunload", beforeUnload);
  if (supportsGameFiles()) void loadGameFolder();
  try {
    formations.value = await engine.formationData();
    session = await openWorkspace();
    if (session.data) {
      rawRecovery.value = session.data;
      try {
        await workspace.restore(session.data);
        rawRecovery.value = "";
      } catch (cause) {
        await session.close();
        session = undefined;
        throw cause;
      }
    }
    recovery.value = "saved";
  } catch (cause) {
    recovery.value = "failed";
    recoveryError.value = message(cause);
  } finally {
    ready.value = true;
  }
  if (location.hash.startsWith("#v1/")) await run(() => preview(shareBytes(location.href)));
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", keydown);
  window.removeEventListener("beforeunload", beforeUnload);
  void session?.close();
});
</script>

<template>
  <main class="app-shell" @dragend="dragged = null">
    <header class="app-header">
      <a class="brand" :href="'.'" aria-label="Gridiron Playbook" @click.prevent
        ><span class="brand-mark">G</span><span>GRIDIRON <strong>PLAYBOOK</strong></span></a
      >
      <div class="header-actions">
        <input
          ref="fileInput"
          data-testid="open-files"
          class="visually-hidden"
          type="file"
          accept=".sav,.json,.gridironshare"
          multiple
          @change="files"
        />
        <button :disabled="busy || !ready" title="Open files (Ctrl/⌘ O)" @click="fileInput?.click()">Open files</button>
        <button :disabled="busy || !ready" @click="createBook">New playbook</button>
        <button :disabled="busy || !ready" @click="importLink = ''">Import link</button>
        <button
          class="primary"
          :disabled="busy || !active || !!active.draft"
          title="Download .sav (Ctrl/⌘ S)"
          @click="download"
        >
          Download .sav
        </button>
        <details class="game-menu">
          <summary title="Game playbook">Game</summary>
          <div>
            <template v-if="supportsGameFiles()"
              ><button
                :disabled="busy || !gameFolderReady || !active || !!active.draft"
                @click="active && requestGame({ kind: 'install', document: active.document })"
              >
                Use in game</button
              ><button :disabled="busy || !gameFolderReady" @click="requestGame({ kind: 'restore' })">
                Restore previous playbook</button
              ><button :disabled="busy || !gameFolderReady" @click="requestGame({ kind: 'choose' })">
                Game folder…
              </button></template
            >
            <p v-else>
              Direct installation is unavailable in this browser. Download the .sav file, back up your existing game
              save, then replace it.
            </p>
          </div>
        </details>
        <button class="icon-button" aria-label="Keyboard shortcuts" title="Keyboard shortcuts" @click="help = true">
          ?
        </button>
      </div>
    </header>
    <div v-if="error" class="notice error" role="alert">
      <span>{{ error }}</span
      ><button aria-label="Dismiss error" @click="error = ''">×</button>
    </div>
    <div v-if="notice" class="notice" role="status">
      <span>{{ notice }}</span
      ><button aria-label="Dismiss notification" @click="notice = ''">×</button>
    </div>
    <div v-if="recoveryError" class="notice error" role="alert">
      <span>Local recovery: {{ recoveryError }}</span
      ><button v-if="rawRecovery" @click="downloadRecovery">Download recovery data</button>
    </div>
    <nav v-if="workspace.tabs.length" class="tab-bar" aria-label="Playbooks">
      <div class="tabs" role="tablist">
        <div
          v-for="(tab, index) in workspace.tabs"
          :key="tab.id"
          class="tab-item"
          :class="{ active: tab.id === workspace.activeId }"
          @dragover="dragOver"
          @drop.prevent="drop($event, tab.id, 0)"
        >
          <button
            role="tab"
            :aria-label="tab.name"
            :aria-selected="tab.id === workspace.activeId"
            :tabindex="tab.id === workspace.activeId ? 0 : -1"
            :disabled="busy"
            @click="workspace.activate(tab.id)"
            @keydown="tabKey($event, index)"
          >
            {{ tab.name }}<span v-if="tab.document !== tab.savedDocument" class="dirty-dot" aria-hidden="true">●</span>
          </button>
          <button class="tab-close" :aria-label="`Close ${tab.name}`" :disabled="busy" @click="closeTab(tab.id)">
            ×
          </button>
        </div>
      </div>
      <div class="history-controls">
        <button
          :disabled="busy || !workspace.canUndo || !!active?.draft"
          title="Undo (Ctrl/⌘ Z)"
          aria-label="Undo"
          @click="run(() => workspace.undo())"
        >
          ↶</button
        ><button
          :disabled="busy || !workspace.canRedo || !!active?.draft"
          title="Redo (Ctrl/⌘ Shift Z)"
          aria-label="Redo"
          @click="run(() => workspace.redo())"
        >
          ↷
        </button>
      </div>
    </nav>
    <div v-if="active" class="workspace">
      <PlayLibrary
        :tab="active"
        :formations="formations"
        :busy="busy || !!active.draft"
        :can-transfer="workspace.tabs.length > 1"
        @select="selectPlay"
        @search="active && (active.search = $event)"
        @create="openNewPlay()"
        @duplicate="openNewPlay(true)"
        @delete="edit({ type: 'delete_plays', indices: [...active.selection] })"
        @transfer="showTransfer"
        @reorder="reorder"
        @share="showShare('playbook')"
        @drag="beginDrag"
        @drop="(event, insertion) => active && drop(event, active.id, insertion)"
      />
      <section class="field-panel" :aria-busy="busy" :inert="busy">
        <PlayField
          v-if="play"
          :key="`${active.id}:${active.selection[0]}`"
          ref="field"
          :play="play"
          :formation="formation"
          :selected="active.selectedRoute"
          :draft="active.draft"
          @select="active && (active.selectedRoute = $event)"
          @start="draw"
          @draft="draft"
          @finish="finishRoute"
          @cancel="active && (active.draft = null)"
          @move="(index, point) => routeEdit('move_point', index, point)"
          @insert="(index, point) => routeEdit('insert_point', index, point)"
          @delete="(index) => routeEdit('delete_point', index)"
          @block="(index) => routeEdit('add_block', index)"
        />
        <div v-else class="empty-state">
          <span class="empty-field-mark">＋</span
          ><button class="primary" :disabled="busy" @click="openNewPlay()">Create your first play</button>
        </div>
      </section>
      <PlayInspector
        v-if="play"
        :play="play"
        :formations="formations"
        :formation="formation"
        :selected="active.selectedRoute"
        :drawing="!!active.draft"
        :busy="busy"
        @rename="playEdit('rename_play', $event)"
        @formation="playEdit('change_formation', $event)"
        @select="active && (active.selectedRoute = $event)"
        @draw="draw"
        @delete-route="routeEdit('delete_route')"
        @flip="playEdit('flip_play')"
        @clear="playEdit('clear_routes')"
        @share="showShare('play')"
      />
    </div>
    <section v-else class="empty-state welcome">
      <span class="brand-mark">G</span>
      <h1>Playbook</h1>
      <div>
        <button class="primary" :disabled="busy || !ready" @click="createBook">Create a playbook</button
        ><button :disabled="busy || !ready" @click="fileInput?.click()">Open a playbook</button>
      </div>
    </section>
    <footer class="app-footer">
      <span data-testid="recovery-status" role="status" :class="{ error: recovery === 'failed' }">{{
        recovery === "loading"
          ? "Opening workspace…"
          : recovery === "saving"
          ? "Saving…"
          : recovery === "failed"
          ? "Not saved locally"
          : "Saved locally"
      }}</span
      ><span v-if="busy" role="status">Working…</span>
    </footer>

    <DialogFrame v-if="newPlay" :title="newPlay.duplicate ? 'Duplicate play' : 'New play'" @close="newPlay = null">
      <form @submit.prevent="submitPlay">
        <label class="control-label" for="new-play-name">Play name</label
        ><input id="new-play-name" v-model="newPlay.name" required autofocus maxlength="1024" />
        <template v-if="!newPlay.duplicate"
          ><label class="control-label" for="new-play-formation">Formation</label
          ><select id="new-play-formation" v-model="newPlay.formation">
            <option v-for="value in formations" :key="value.name">{{ value.name }}</option>
          </select></template
        >
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <footer class="dialog-actions">
          <button type="button" @click="newPlay = null">Cancel</button
          ><button class="primary" :disabled="busy || !newPlay.name.trim()">
            {{ newPlay.duplicate ? "Duplicate play" : "Create play" }}
          </button>
        </footer>
      </form>
    </DialogFrame>
    <DialogFrame v-if="transfer" :title="transferTitle" @close="transfer = null"
      ><form @submit.prevent="submitTransfer">
        <label class="control-label" for="destination">Destination</label
        ><select id="destination" v-model="transfer.destination">
          <option
            v-for="tab in workspace.tabs.filter((value) => value.id !== active?.id)"
            :key="tab.id"
            :value="tab.id"
          >
            {{ tab.name }}
          </option>
        </select>
        <footer class="dialog-actions">
          <button type="button" @click="transfer = null">Cancel</button
          ><button class="primary" :disabled="busy || !transfer.destination">{{ transferTitle }}</button>
        </footer>
      </form></DialogFrame
    >
    <ShareDialog v-if="share" v-bind="share" @close="share = null" />
    <DialogFrame v-if="importLink !== null" title="Import link" @close="importLink = null"
      ><form @submit.prevent="previewLink">
        <label class="control-label" for="quickshare-link">Quickshare link</label
        ><textarea id="quickshare-link" v-model="importLink" rows="4" autofocus />
        <footer class="dialog-actions">
          <button type="button" @click="importLink = null">Cancel</button
          ><button class="primary" :disabled="busy || !importLink.trim()">Preview</button>
        </footer>
      </form></DialogFrame
    >
    <SharePreview
      v-if="incoming"
      :key="incoming.id"
      :plays="incoming.plays"
      :kind="incoming.kind"
      :formations="formations"
      :busy="busy"
      @close="dismissIncoming(incoming!.id)"
      @import="importIncoming"
      @download="downloadBytes(incoming!.bytes, `${fileStem(incoming!.name)}.gridironshare`)"
    />
    <GameFolderDialog
      v-if="gameFolderAction"
      :directory="gameDirectory"
      :problem="gameFolderProblem"
      @close="gameFolderAction = null"
      @selected="gameFolderSelected"
      @forgotten="
        gameDirectory = null;
        gameFolderProblem = '';
      "
    />
    <GameDialog
      v-if="gameChange"
      :change="gameChange.change"
      :restoring="gameChange.restoring"
      @applying="gameApplying = $event"
      @close="gameChange = null"
      @done="
        gameChange = null;
        notice = $event.changed
          ? 'Game playbook updated. Previous save backed up.'
          : 'Game playbook is already up to date.';
      "
    />
    <DialogFrame v-if="confirmation" :title="confirmation.title" @close="answer(false)"
      ><p>{{ confirmation.text }}</p>
      <footer class="dialog-actions">
        <button @click="answer(false)">Cancel</button
        ><button class="danger-button" @click="answer(true)">{{ confirmation.action }}</button>
      </footer></DialogFrame
    >
    <DialogFrame v-if="help" title="Keyboard shortcuts" @close="help = false"
      ><dl class="shortcuts">
        <dt>Undo / redo</dt>
        <dd><kbd>Ctrl/⌘ Z</kbd> / <kbd>Ctrl/⌘ Shift Z</kbd></dd>
        <dt>Finish route</dt>
        <dd><kbd>Enter</kbd></dd>
        <dt>Cancel drawing or node edit</dt>
        <dd><kbd>Esc</kbd></dd>
        <dt>Remove last drawn point</dt>
        <dd><kbd>Backspace</kbd> or right-click</dd>
        <dt>Delete selected node</dt>
        <dd><kbd>Delete</kbd></dd>
        <dt>Add node / block</dt>
        <dd><kbd>N</kbd> / <kbd>B</kbd></dd>
        <dt>Select multiple plays</dt>
        <dd><kbd>Ctrl/⌘ click</kbd> / <kbd>Shift click</kbd></dd>
        <dt>Copy plays when dragging</dt>
        <dd><kbd>Ctrl/⌘ drag</kbd></dd>
        <dt>Download save / open files</dt>
        <dd><kbd>Ctrl/⌘ S</kbd> / <kbd>Ctrl/⌘ O</kbd></dd>
      </dl></DialogFrame
    >
  </main>
</template>
