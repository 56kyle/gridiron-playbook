<script setup lang="ts">
import { computed } from "vue";
import type { Formation } from "../types";
import type { PlaybookTab } from "../workspace";
import PlayThumbnail from "./PlayThumbnail.vue";

const props = defineProps<{ tab: PlaybookTab; formations: Formation[]; busy: boolean; canTransfer: boolean }>();
const emit = defineEmits<{
  select: [index: number, extend: boolean, toggle: boolean];
  search: [value: string];
  create: [];
  duplicate: [];
  delete: [];
  transfer: [mode: "copy" | "move" | "merge"];
  reorder: [direction: -1 | 1];
  share: [];
  drag: [event: DragEvent, index: number];
  drop: [event: DragEvent, index: number];
}>();
const visible = computed(() =>
  props.tab.view.plays
    .map((play, index) => ({ play, index }))
    .filter(({ play }) =>
      `${play.play_name} ${play.formation_name}`.toLowerCase().includes(props.tab.search.toLowerCase())
    )
);
const marker = computed(() => (props.tab.selection.length === 1 ? props.tab.selection[0] : null));
function formation(name: string): Formation | undefined {
  return props.formations.find((value) => value.name === name);
}
function select(event: MouseEvent, index: number): void {
  emit("select", index, event.shiftKey, event.ctrlKey || event.metaKey);
}
function rowDrop(event: DragEvent, index: number): void {
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
  emit("drop", event, index + Number(event.clientY > bounds.top + bounds.height / 2));
}
</script>
<template>
  <aside class="play-library" aria-label="Plays">
    <header class="panel-heading">
      <h2>
        Plays <span>{{ tab.view.plays.length }}</span>
      </h2>
      <button class="primary" :disabled="busy" @click="emit('create')">New play</button>
    </header>
    <input
      class="play-search"
      type="search"
      aria-label="Search plays"
      placeholder="Search plays"
      :value="tab.search"
      @input="emit('search', ($event.target as HTMLInputElement).value)"
    />
    <div class="selection-actions" role="toolbar" aria-label="Play actions">
      <button
        class="icon-button"
        aria-label="Duplicate play"
        title="Duplicate play"
        :disabled="busy || tab.selection.length !== 1"
        @click="emit('duplicate')"
      >
        ⧉
      </button>
      <button
        class="icon-button"
        aria-label="Delete plays"
        title="Delete plays"
        :disabled="busy || !tab.selection.length"
        @click="emit('delete')"
      >
        ×
      </button>
      <button
        class="icon-button"
        aria-label="Move up"
        title="Move up"
        :disabled="busy || !tab.selection.length || tab.selection[0] === 0"
        @click="emit('reorder', -1)"
      >
        ↑
      </button>
      <button
        class="icon-button"
        aria-label="Move down"
        title="Move down"
        :disabled="busy || !tab.selection.length || tab.selection.at(-1) === tab.view.plays.length - 1"
        @click="emit('reorder', 1)"
      >
        ↓
      </button>
      <span class="toolbar-spacer" />
      <button :disabled="busy || !canTransfer || !tab.selection.length" @click="emit('transfer', 'copy')">
        Copy to…
      </button>
      <button :disabled="busy || !canTransfer || !tab.selection.length" @click="emit('transfer', 'move')">
        Move to…
      </button>
    </div>
    <div
      class="play-list"
      role="listbox"
      aria-label="Play list"
      aria-multiselectable="true"
      @dragover.prevent
      @drop.self="emit('drop', $event, tab.view.plays.length)"
    >
      <div
        v-for="{ play, index } in visible"
        :key="index"
        data-testid="play-row"
        :data-play-index="index"
        class="play-row"
        :class="{ selected: tab.selection.includes(index), current: marker === index }"
        role="option"
        :aria-selected="tab.selection.includes(index)"
        tabindex="0"
        :draggable="!busy"
        @dragstart="emit('drag', $event, index)"
        @dragover.prevent
        @drop.stop.prevent="rowDrop($event, index)"
        @click="select($event, index)"
        @keydown.enter.prevent="emit('select', index, false, false)"
        @keydown.space.prevent="emit('select', index, false, true)"
      >
        <input
          type="checkbox"
          :aria-label="`Select ${play.play_name}`"
          :checked="tab.selection.includes(index)"
          @click.stop
          @change="emit('select', index, false, true)"
        />
        <PlayThumbnail :play="play" :formation="formation(play.formation_name)" />
        <span class="play-row-text"
          ><strong data-testid="play-name">{{ play.play_name || "Untitled play" }}</strong
          ><span>{{ play.formation_name }}</span></span
        >
      </div>
      <div v-if="!visible.length" class="empty-list">{{ tab.search ? "No matching plays" : "No plays yet" }}</div>
    </div>
    <footer class="library-footer">
      <button :disabled="busy || !canTransfer || !tab.view.plays.length" @click="emit('transfer', 'merge')">
        Merge into…</button
      ><button :disabled="busy || !tab.view.plays.length" @click="emit('share')">Share playbook</button>
    </footer>
  </aside>
</template>
