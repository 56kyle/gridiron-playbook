<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import type { Formation, Play, Point } from "../types";
import type { Draft } from "../workspace";
import {
  FIELD_HEIGHT,
  FIELD_WIDTH,
  fieldTransform,
  insertionOnRoute,
  markerLabel,
  positionLabel,
  routeColor,
  type FieldPoint,
} from "../field";

const props = withDefaults(
  defineProps<{
    play: Play;
    formation?: Formation;
    selected: number | null;
    draft: Draft | null;
    readonly?: boolean;
  }>(),
  { readonly: false }
);
const emit = defineEmits<{
  select: [index: number];
  start: [slot: number];
  draft: [points: Point[]];
  finish: [];
  cancel: [];
  move: [index: number, point: Point];
  insert: [index: number, point: Point];
  delete: [index: number];
  block: [index: number];
}>();
const field = ref<SVGSVGElement>();
const id = useId().replaceAll(":", "");
const transform = computed(() => fieldTransform(props.play, props.formation));
const selectedRoute = computed(() => (props.selected === null ? undefined : props.play.routes[props.selected]));
const activePoint = ref<number | null>(null);
const addingNode = ref(false);
const preview = ref<FieldPoint | null>(null);
const insertion = ref<{ index: number; position: FieldPoint } | null>(null);
const undone = ref<Point[]>([]);
const drag = ref<{
  pointer: number;
  index: number;
  start: FieldPoint;
  position: FieldPoint;
  offset: FieldPoint;
} | null>(null);
const routeOrder = computed(() =>
  props.play.routes.map((_, i) => i).sort((a, b) => Number(a === props.selected) - Number(b === props.selected))
);
const draftPoints = computed(() => props.draft?.points.map(transform.value.project) ?? []);
const minimumPoints = computed(() => (props.draft && origin(props.draft.slot) ? 1 : 2));
const originY = computed(() => transform.value.project({ x: 0, y: 0 })[1]);
const draftLabel = computed(() => positionLabel(props.formation, props.draft?.slot ?? -1));
const nodeMinimum = computed(() => (selectedRoute.value && origin(selectedRoute.value.slot) ? 1 : 2));
const blockTarget = computed(() => activePoint.value ?? (selectedRoute.value?.points.length ?? 0) - 1);

watch(
  () => [props.selected, props.draft?.slot, props.play.formation_name],
  () => {
    activePoint.value = null;
    addingNode.value = false;
    insertion.value = null;
    preview.value = null;
    undone.value = [];
  }
);
watch(
  () => selectedRoute.value?.points.length,
  (length) => {
    if (activePoint.value !== null && activePoint.value >= (length ?? 0)) activePoint.value = null;
  }
);

function origin(slot: number): FieldPoint | undefined {
  const position = props.formation?.positions.find((player) => player.slot === slot);
  return position && transform.value.project(position);
}
function points(index: number): FieldPoint[] {
  return props.play.routes[index]!.points.map((point, pointIndex) =>
    index === props.selected && drag.value?.index === pointIndex ? drag.value.position : transform.value.project(point)
  );
}
function polyline(route: FieldPoint[], start?: FieldPoint): string {
  return (start ? [start, ...route] : route).map((point) => point.join(",")).join(" ");
}
function color(slot: number): string {
  return routeColor(positionLabel(props.formation, slot));
}
function focus(): void {
  field.value?.focus({ preventScroll: true });
}
function choosePlayer(slot: number): void {
  if (props.readonly || props.draft || addingNode.value) return;
  const route = props.play.routes.findIndex((candidate) => candidate.slot === slot);
  route < 0 ? emit("start", slot) : emit("select", route);
  focus();
}
function chooseRoute(index: number): void {
  if (!props.readonly && !props.draft && !addingNode.value) {
    emit("select", index);
    focus();
  }
}
function pointer(event: MouseEvent | PointerEvent): FieldPoint | null {
  const matrix = field.value?.getScreenCTM();
  if (!matrix) return null;
  const point = new DOMPoint(Math.floor(event.clientX), Math.floor(event.clientY)).matrixTransform(matrix.inverse());
  return [Math.max(0, Math.min(FIELD_WIDTH, point.x)), Math.max(0, Math.min(FIELD_HEIGHT, point.y))];
}
function nearest(position: FieldPoint): { index: number; position: FieldPoint } | null {
  if (!selectedRoute.value || props.selected === null) return null;
  const matrix = field.value?.getScreenCTM();
  return insertionOnRoute(
    points(props.selected),
    origin(selectedRoute.value.slot),
    position,
    12 / (matrix ? Math.hypot(matrix.a, matrix.b) : 1)
  );
}
function place(event: MouseEvent): void {
  if (props.readonly || event.button !== 0) return;
  const position = pointer(event);
  if (!position) return;
  if (addingNode.value) {
    const target = nearest(position);
    if (target) {
      emit("insert", target.index, transform.value.unproject(target.position));
      addingNode.value = false;
      insertion.value = null;
    }
  } else if (props.draft) {
    emit("draft", [...props.draft.points, transform.value.unproject(position)]);
    undone.value = [];
    preview.value = null;
  }
  focus();
}
function movePointer(event: PointerEvent): void {
  if (props.readonly) return;
  const position = pointer(event);
  if (!position) return;
  if (props.draft) preview.value = position;
  else if (addingNode.value) insertion.value = nearest(position);
  else if (drag.value?.pointer === event.pointerId) {
    drag.value.position = [
      Math.min(FIELD_WIDTH, Math.max(0, position[0] + drag.value.offset[0])),
      Math.min(FIELD_HEIGHT, Math.max(0, position[1] + drag.value.offset[1])),
    ];
  }
}
function startDrag(event: PointerEvent, index: number): void {
  if (props.readonly || props.draft || addingNode.value || event.button !== 0 || props.selected === null) return;
  const position = pointer(event),
    point = points(props.selected)[index];
  if (!position || !point) return;
  activePoint.value = index;
  focus();
  field.value?.setPointerCapture(event.pointerId);
  drag.value = {
    pointer: event.pointerId,
    index,
    start: point,
    position: point,
    offset: [point[0] - position[0], point[1] - position[1]],
  };
}
function cancelDrag(): void {
  const current = drag.value;
  drag.value = null;
  if (current && field.value?.hasPointerCapture(current.pointer)) field.value.releasePointerCapture(current.pointer);
}
function endDrag(event: PointerEvent): void {
  if (drag.value?.pointer !== event.pointerId) return;
  movePointer(event);
  const current = drag.value;
  cancelDrag();
  if (Math.hypot(current.position[0] - current.start[0], current.position[1] - current.start[1]) > 0.01)
    emit("move", current.index, transform.value.unproject(current.position));
}
function undoPoint(): void {
  if (!props.draft?.points.length) return;
  const remaining = [...props.draft.points];
  undone.value.push(remaining.pop()!);
  emit("draft", remaining);
}
function redoPoint(): void {
  const point = undone.value.pop();
  if (point && props.draft) emit("draft", [...props.draft.points, point]);
}
function finish(): void {
  if (props.draft && props.draft.points.length >= minimumPoints.value) emit("finish");
}
function toggleNode(): void {
  addingNode.value = !addingNode.value;
  insertion.value = null;
  focus();
}
function deleteNode(): void {
  if (activePoint.value !== null && (selectedRoute.value?.points.length ?? 0) > nodeMinimum.value)
    emit("delete", activePoint.value);
}
function handleKey(event: KeyboardEvent): boolean {
  if (props.readonly || event.altKey) return false;
  const key = event.key.toLowerCase(),
    modifier = event.ctrlKey || event.metaKey;
  if (props.draft) {
    if (modifier && key === "z") event.shiftKey ? redoPoint() : undoPoint();
    else if (event.ctrlKey && key === "y") redoPoint();
    else if (!modifier && ["backspace", "delete"].includes(key)) undoPoint();
    else if (!modifier && key === "enter") finish();
    else if (key === "escape") emit("cancel");
    else return false;
  } else if (key === "escape") {
    if (drag.value) cancelDrag();
    else if (addingNode.value) toggleNode();
    else if (activePoint.value !== null) activePoint.value = null;
    else return false;
  } else if (key === "delete" && activePoint.value !== null && field.value?.contains(document.activeElement))
    deleteNode();
  else if (key === "b" && !modifier && selectedRoute.value) emit("block", blockTarget.value);
  else if (key === "n" && !modifier && selectedRoute.value) toggleNode();
  else return false;
  event.preventDefault();
  return true;
}
defineExpose({ handleKey });
</script>

<template>
  <section class="play-diagram" aria-label="Play diagram">
    <svg
      ref="field"
      data-testid="play-field"
      class="play-field"
      :viewBox="`0 0 ${FIELD_WIDTH} ${FIELD_HEIGHT}`"
      :role="readonly ? 'img' : 'group'"
      :aria-label="readonly ? 'Route diagram' : 'Route editing field'"
      :tabindex="readonly ? undefined : 0"
      :style="{ cursor: draft || addingNode ? 'crosshair' : 'default' }"
      @click="place"
      @pointermove="movePointer"
      @pointerup="endDrag"
      @lostpointercapture="cancelDrag"
      @pointercancel="cancelDrag"
      @pointerleave="
        preview = null;
        insertion = null;
      "
      @contextmenu.prevent="draft && undoPoint()"
    >
      <defs>
        <pattern :id="`${id}-grid`" width="800" height="96" patternUnits="userSpaceOnUse" :y="originY">
          <rect width="800" height="96" fill="var(--field)" />
          <path d="M0 0H800" stroke="var(--grid)" stroke-width="2" />
          <path d="M0 48H800" stroke="var(--grid-minor)" />
          <path d="M267 0V96 M533 0V96" stroke="var(--grid)" stroke-width="9" stroke-dasharray="1 8" />
        </pattern>
        <marker
          :id="`${id}-arrow`"
          viewBox="0 0 12 12"
          refX="10"
          refY="6"
          markerWidth="4"
          markerHeight="4"
          orient="auto"
        >
          <path d="M1 1L11 6L1 11" fill="none" stroke="context-stroke" stroke-width="2.2" stroke-linejoin="round" />
        </marker>
      </defs>
      <rect width="800" height="630" :fill="`url(#${id}-grid)`" />
      <path d="M18 0V630 M782 0V630" stroke="var(--grid)" pointer-events="none" />
      <path :d="`M18 ${originY}H782`" stroke="var(--baseline)" stroke-width="1.5" pointer-events="none">
        <title>Line of scrimmage</title>
      </path>
      <g
        v-for="index in routeOrder"
        :key="index"
        :data-route-index="index"
        :role="readonly ? undefined : 'button'"
        :tabindex="readonly || draft || addingNode ? undefined : 0"
        :aria-label="`Select ${positionLabel(formation, play.routes[index]!.slot)} route ${index + 1}`"
        :aria-pressed="selected === index"
        :opacity="draft || (selected !== null && selected !== index) ? 0.5 : 1"
        @click="chooseRoute(index)"
        @keydown.enter.prevent="chooseRoute(index)"
        @keydown.space.prevent="chooseRoute(index)"
      >
        <polyline
          :points="polyline(points(index), origin(play.routes[index]!.slot))"
          fill="none"
          stroke="transparent"
          stroke-width="24"
          pointer-events="stroke"
        />
        <polyline
          :points="polyline(points(index), origin(play.routes[index]!.slot))"
          fill="none"
          :stroke="color(play.routes[index]!.slot)"
          :stroke-width="selected === index ? 4 : 3"
          stroke-linecap="round"
          stroke-linejoin="round"
          :marker-end="play.routes[index]!.points.length && !play.routes[index]!.ends_with_block ? `url(#${id}-arrow)` : undefined"
        />
      </g>
      <g v-if="draft" pointer-events="none" :stroke="color(draft.slot)">
        <polyline
          data-draft-path
          :points="polyline(draftPoints, origin(draft.slot))"
          fill="none"
          stroke-width="3.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <polyline
          v-if="preview"
          data-draft-preview
          :points="polyline([preview], draftPoints.at(-1) ?? origin(draft.slot))"
          fill="none"
          stroke-width="3.5"
          stroke-dasharray="7 5"
          :marker-end="`url(#${id}-arrow)`"
        />
        <circle
          v-for="(point, index) in draftPoints"
          :key="index"
          :cx="point[0]"
          :cy="point[1]"
          r="5"
          :fill="color(draft.slot)"
          stroke="var(--field)"
          stroke-width="2"
        />
      </g>
      <g
        v-for="player in formation?.positions ?? []"
        :key="player.slot"
        :data-lineup-slot="player.slot"
        :transform="`translate(${transform.project(player).join(' ')})`"
        :role="readonly ? undefined : 'button'"
        :tabindex="readonly || draft || addingNode ? undefined : 0"
        :aria-label="`${play.routes.some((route) => route.slot === player.slot) ? 'Select' : 'Draw'} ${
          player.label
        } route, slot ${player.slot}`"
        @click.stop="choosePlayer(player.slot)"
        @keydown.enter.prevent="choosePlayer(player.slot)"
        @keydown.space.prevent="choosePlayer(player.slot)"
      >
        <title>{{ player.label }} · Slot {{ player.slot }}</title>
        <rect
          :x="-Math.max(30, markerLabel(player.label).length * 8 + 10) / 2"
          y="-13"
          :width="Math.max(30, markerLabel(player.label).length * 8 + 10)"
          height="26"
          rx="12"
          fill="var(--input)"
          :stroke="color(player.slot)"
          :stroke-width="draft?.slot === player.slot || selectedRoute?.slot === player.slot ? 3 : 1.8"
        />
        <text text-anchor="middle" dy="5" font-size="14" font-weight="750" fill="var(--ink)">
          {{ markerLabel(player.label) }}
        </text>
      </g>
      <g v-if="!readonly && selectedRoute && selected !== null && !draft">
        <g
          v-for="(point, index) in points(selected)"
          :key="index"
          :data-point-index="index"
          :transform="`translate(${point.join(' ')})`"
          role="button"
          :tabindex="addingNode ? -1 : 0"
          :aria-label="`Select node ${index + 1}`"
          :aria-pressed="activePoint === index"
          @pointerdown.stop.prevent="startDrag($event, index)"
          @click.stop="activePoint = index"
          @focus="activePoint = index"
          @keydown.enter.prevent="activePoint = index"
          @keydown.space.prevent="activePoint = index"
        >
          <circle r="12" fill="transparent" />
          <circle
            :r="activePoint === index ? 6 : 4"
            :fill="activePoint === index ? color(selectedRoute.slot) : 'var(--field)'"
            :stroke="activePoint === index ? 'var(--ink)' : color(selectedRoute.slot)"
            stroke-width="2"
          />
        </g>
      </g>
      <g v-if="addingNode" pointer-events="none">
        <circle
          v-if="insertion"
          :cx="insertion.position[0]"
          :cy="insertion.position[1]"
          r="6"
          fill="var(--field)"
          stroke="var(--accent)"
          stroke-width="2.5"
        />
      </g>
    </svg>
    <div v-if="draft && !readonly" class="field-tools">
      <strong>{{ markerLabel(draftLabel) }}</strong>
      <button :disabled="!draft.points.length" title="Undo point (Ctrl/⌘ Z or Backspace)" @click="undoPoint">
        Undo point
      </button>
      <button :disabled="!undone.length" title="Redo point (Ctrl/⌘ Shift Z)" @click="redoPoint">Redo point</button>
      <button
        class="primary"
        :disabled="draft.points.length < minimumPoints"
        title="Finish route (Enter)"
        @click="finish"
      >
        Finish route
      </button>
      <button title="Cancel route (Esc)" @click="emit('cancel')">Cancel</button>
    </div>
    <div v-else-if="selectedRoute && !readonly" class="field-tools">
      <button
        :class="{ primary: addingNode }"
        :aria-pressed="addingNode"
        title="Insert on a segment or extend the route (N)"
        @click="toggleNode"
      >
        Add node
      </button>
      <button
        :disabled="activePoint === null || selectedRoute.points.length <= nodeMinimum || addingNode"
        title="Delete selected node (Delete)"
        @click="deleteNode"
      >
        Delete node
      </button>
      <button
        :disabled="blockTarget < 0 || addingNode"
        title="Add a block at the selected node or route end (B)"
        @click="emit('block', blockTarget)"
      >
        Add block
      </button>
    </div>
  </section>
</template>
