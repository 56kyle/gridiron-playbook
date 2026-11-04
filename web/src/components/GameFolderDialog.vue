<script setup lang="ts">
import { ref } from "vue";
import {
  DEFAULT_WINDOWS_STEAM_FOLDER,
  forgetGameDirectory,
  reconnectGameDirectory,
  rememberGameDirectory,
  selectGameDirectory,
} from "../gameDirectory";
import { GAME_SAVE_NAME, GameFileError } from "../gameFiles";
import { message } from "../files";
import DialogFrame from "./DialogFrame.vue";

const props = defineProps<{ directory: FileSystemDirectoryHandle | null; problem: string }>();
const emit = defineEmits<{
  close: [];
  selected: [directory: FileSystemDirectoryHandle, remembered: boolean];
  forgotten: [];
}>();
const busy = ref(false);
const error = ref(props.problem);
const copied = ref(false);
const windows = navigator.userAgent.includes("Windows");

async function accept(directory: FileSystemDirectoryHandle): Promise<void> {
  let remembered = true;
  try {
    await rememberGameDirectory(directory);
  } catch {
    remembered = false;
  }
  emit("selected", directory, remembered);
}
async function choose(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await accept(await selectGameDirectory(props.directory ?? undefined));
  } catch (cause) {
    if (!(cause instanceof GameFileError && cause.code === "cancelled")) error.value = message(cause);
  } finally {
    busy.value = false;
  }
}
async function reconnect(): Promise<void> {
  if (!props.directory || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await reconnectGameDirectory(props.directory);
    await accept(props.directory);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}
async function forget(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await forgetGameDirectory();
    emit("forgotten");
  } catch {
    error.value = "The saved folder could not be forgotten. Try again.";
  } finally {
    busy.value = false;
  }
}
async function copyPath(): Promise<void> {
  try {
    await navigator.clipboard.writeText(DEFAULT_WINDOWS_STEAM_FOLDER);
    copied.value = true;
  } catch {
    error.value = "Select and copy the folder path.";
  }
}
</script>
<template>
  <DialogFrame title="Game folder" :dismissible="!busy" @close="!busy && emit('close')">
    <div v-if="directory" class="saved-game-folder">
      <strong>{{ directory.name }}</strong
      ><span>{{ GAME_SAVE_NAME }}</span>
    </div>
    <p v-else>Choose SaveGames or the Gridiron install folder.</p>
    <details class="game-folder-help" :open="!directory">
      <summary>Find in Steam</summary>
      <p>Gridiron → Manage → Browse local files</p>
      <template v-if="windows">
        <label for="steam-folder-path">Default Steam folder</label>
        <div class="game-folder-path">
          <input
            id="steam-folder-path"
            :value="DEFAULT_WINDOWS_STEAM_FOLDER"
            readonly
            @focus="($event.target as HTMLInputElement).select()"
          />
          <button :disabled="busy" @click="copyPath">{{ copied ? "Copied" : "Copy path" }}</button>
        </div>
      </template>
    </details>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <footer class="dialog-actions">
      <button v-if="directory" class="forget-game-folder" :disabled="busy" @click="forget">Forget folder</button>
      <button v-else :disabled="busy" @click="emit('close')">Cancel</button>
      <button :class="{ primary: !directory }" :disabled="busy" @click="choose">
        {{ directory ? "Choose another…" : "Choose folder…" }}
      </button>
      <button v-if="directory" class="primary" :disabled="busy" @click="reconnect">Use saved folder</button>
    </footer>
  </DialogFrame>
</template>
