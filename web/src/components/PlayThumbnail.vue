<script setup lang="ts">
import { computed } from "vue";
import type { Formation, Play } from "../types";
import { fieldTransform, positionLabel, routeColor } from "../field";
const props = defineProps<{ play: Play; formation?: Formation }>();
const transform = computed(() => fieldTransform(props.play, props.formation));
function points(index: number): string {
  const route = props.play.routes[index]!;
  const start = props.formation?.positions.find((player) => player.slot === route.slot);
  return [...(start ? [start] : []), ...route.points]
    .map((point) => transform.value.project(point).join(","))
    .join(" ");
}
</script>
<template>
  <svg class="play-thumbnail" viewBox="0 0 800 630" aria-hidden="true">
    <path d="M0 80H800 M0 176H800 M0 272H800 M0 368H800 M0 464H800 M0 560H800" stroke="var(--grid)" stroke-width="5" />
    <path :d="`M0 ${transform.project({ x: 0, y: 0 })[1]}H800`" stroke="var(--baseline)" stroke-width="6" />
    <polyline
      v-for="(route, index) in play.routes"
      :key="index"
      :points="points(index)"
      fill="none"
      :stroke="routeColor(positionLabel(formation, route.slot))"
      stroke-width="12"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle
      v-for="player in formation?.positions ?? []"
      :key="player.slot"
      :cx="transform.project(player)[0]"
      :cy="transform.project(player)[1]"
      r="15"
      :fill="routeColor(player.label)"
    />
  </svg>
</template>
