<script setup lang="ts">
import { ref } from "vue";
import type { Formation, Play } from "../types";
import { markerLabel, positionLabel, routeColor } from "../field";
const props = defineProps<{
  play: Play;
  formations: Formation[];
  formation?: Formation;
  selected: number | null;
  drawing: boolean;
  busy: boolean;
}>();
const emit = defineEmits<{
  rename: [name: string];
  formation: [name: string];
  select: [index: number];
  draw: [slot: number];
  deleteRoute: [];
  flip: [];
  clear: [];
  share: [];
}>();
const slot = ref(5);
const customSlot = ref(7);
</script>
<template>
  <aside class="play-inspector" aria-label="Play details">
    <label class="control-label" for="play-name">Play name</label>
    <input
      id="play-name"
      aria-label="Play name"
      class="play-name-input"
      :value="play.play_name"
      :disabled="busy || drawing"
      @change="emit('rename', ($event.target as HTMLInputElement).value)"
    />
    <label class="control-label" for="play-formation">Formation</label>
    <select
      id="play-formation"
      aria-label="Formation"
      :value="play.formation_name"
      :disabled="busy || drawing"
      @change="emit('formation', ($event.target as HTMLSelectElement).value)"
    >
      <option v-if="!formations.some((value) => value.name === play.formation_name)" :value="play.formation_name">
        {{ play.formation_name }}
      </option>
      <option v-for="value in formations" :key="value.name" :value="value.name">{{ value.name }}</option>
    </select>
    <div class="panel-heading route-heading">
      <h2>
        Routes <span>{{ play.routes.length }}</span>
      </h2>
      <button
        class="icon-button"
        aria-label="Delete route"
        title="Delete route"
        :disabled="busy || drawing || selected === null"
        @click="emit('deleteRoute')"
      >
        ×
      </button>
    </div>
    <div class="route-list" role="listbox" aria-label="Routes">
      <button
        v-for="(route, index) in play.routes"
        :key="index"
        :data-testid="`route-${index}`"
        class="route-row"
        :class="{ selected: selected === index }"
        role="option"
        :aria-selected="selected === index"
        :disabled="drawing || busy"
        @click="emit('select', index)"
      >
        <span class="position-dot" :style="{ background: routeColor(positionLabel(formation, route.slot)) }" />
        <strong>{{ markerLabel(positionLabel(formation, route.slot)) }}</strong
        ><span>{{ (route.yards ?? 0).toFixed(1) }} yds</span>
      </button>
    </div>
    <div class="draw-controls">
      <select v-model.number="slot" aria-label="Route position" :disabled="busy || drawing">
        <option v-for="player in formation?.positions ?? []" :key="player.slot" :value="player.slot">
          {{ player.label }}
        </option>
        <option :value="-1">Other slot</option>
      </select>
      <input
        v-if="slot === -1 || !formation"
        v-model.number="customSlot"
        aria-label="Player slot"
        type="number"
        min="0"
        max="255"
      />
      <button :disabled="busy || drawing" @click="emit('draw', slot === -1 || !formation ? customSlot : slot)">
        Draw route
      </button>
    </div>
    <div class="inspector-bottom">
      <div class="two-buttons">
        <button :disabled="busy || drawing" @click="emit('flip')">Flip</button
        ><button :disabled="busy || drawing || !play.routes.length" @click="emit('clear')">Clear routes</button>
      </div>
      <button class="primary" :disabled="busy || drawing" @click="emit('share')">Share play</button>
    </div>
  </aside>
</template>
