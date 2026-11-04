<script setup lang="ts">
import { computed, ref } from "vue";
import type { Formation, Play, ShareKind } from "../types";
import DialogFrame from "./DialogFrame.vue";
import PlayField from "./PlayField.vue";
const props = defineProps<{ plays: Play[]; kind: ShareKind; formations: Formation[]; busy: boolean }>();
const emit = defineEmits<{ close: []; import: []; download: [] }>();
const selected = ref(0);
const play = computed(() => props.plays[selected.value]);
const formation = computed(() => props.formations.find((value) => value.name === play.value?.formation_name));
</script>
<template>
  <DialogFrame title="Quickshare" wide :dismissible="!busy" @close="emit('close')">
    <div class="share-preview">
      <div class="preview-list" role="listbox" aria-label="Shared plays">
        <button
          v-for="(entry, index) in plays"
          :key="index"
          role="option"
          :aria-selected="selected === index"
          :class="{ selected: selected === index }"
          @click="selected = index"
        >
          <strong>{{ entry.play_name }}</strong
          ><span>{{ entry.formation_name }}</span>
        </button>
      </div>
      <PlayField v-if="play" :play="play" :formation="formation" :selected="null" :draft="null" readonly />
    </div>
    <footer class="dialog-actions">
      <span>{{ plays.length }} {{ plays.length === 1 ? "play" : "plays" }}</span
      ><button @click="emit('download')">Download share file</button
      ><button class="primary" :disabled="busy" @click="emit('import')">
        {{ kind === "play" ? "Import play" : "Open playbook" }}
      </button>
    </footer>
  </DialogFrame>
</template>
