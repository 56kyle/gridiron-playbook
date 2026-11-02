const ROUTE_COLORS = ['#ffd787', '#8ce3d2', '#a7caff', '#f7a9b6', '#d9b9ff', '#c0de86'];

export default {
  props: {
    routes: Array, selected: Number, draftSlot: Number, originY: Number,
    fieldWidth: Number, fieldHeight: Number, diagramId: Number,
  },
  emits: ['route_select', 'point_move', 'route_finish', 'route_cancel'],
  data() {
    return { drag: null, draft: [] };
  },
  computed: {
    drawing() { return this.draftSlot != null; },
    patternId() { return 'field-grid-' + this.diagramId; },
    arrowId() { return 'route-arrow-' + this.diagramId; },
    routeOrder() {
      const indices = this.routes.map((_, i) => i).filter(i => i !== this.selected);
      if (this.selected != null && this.routes[this.selected]) indices.push(this.selected);
      return indices;
    },
  },
  methods: {
    color(route) { return ROUTE_COLORS[Math.abs(route.slot) % ROUTE_COLORS.length]; },
    points(routeIndex) {
      const original = this.routes[routeIndex].points;
      if (!this.drag || routeIndex !== this.selected) return original;
      return original.map((p, i) => i === this.drag.index ? this.drag.position : p);
    },
    polyline(points) { return points.map(p => p.join(',')).join(' '); },
    fieldPosition(event) {
      const matrix = this.$refs.field.getScreenCTM();
      if (!matrix) return null;
      const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      return [Math.min(this.fieldWidth, Math.max(0, p.x)), Math.min(this.fieldHeight, Math.max(0, p.y))];
    },
    selectRoute(index) {
      if (!this.drawing && index !== this.selected) this.$emit('route_select', {route: index});
    },
    startDrag(event, index) {
      if (this.drawing || this.drag || event.button !== 0 || !event.isPrimary) return;
      const anchor = this.routes[this.selected].points[index];
      const pointer = this.fieldPosition(event);
      if (!pointer) return;
      this.$refs.field.setPointerCapture(event.pointerId);
      this.drag = {
        index, pointerId: event.pointerId, position: anchor,
        offset: [anchor[0] - pointer[0], anchor[1] - pointer[1]], start: anchor,
      };
    },
    moveDrag(event) {
      if (!this.drag || event.pointerId !== this.drag.pointerId) return;
      const pointer = this.fieldPosition(event);
      if (!pointer) return;
      this.drag.position = [
        Math.min(this.fieldWidth, Math.max(0, pointer[0] + this.drag.offset[0])),
        Math.min(this.fieldHeight, Math.max(0, pointer[1] + this.drag.offset[1])),
      ];
    },
    endDrag(event) {
      if (!this.drag || event.pointerId !== this.drag.pointerId) return;
      this.moveDrag(event);
      const {position: [x, y], start, index} = this.drag;
      this.cancelDrag();
      if (Math.hypot(x - start[0], y - start[1]) > 0.01) {
        this.$emit('point_move', {point: index, x, y});
      }
    },
    cancelDrag() {
      if (!this.drag) return;
      const {pointerId} = this.drag;
      this.drag = null;
      if (this.$refs.field.hasPointerCapture(pointerId)) this.$refs.field.releasePointerCapture(pointerId);
    },
    addDraftPoint(event) {
      if (!this.drawing || event.button !== 0) return;
      const point = this.fieldPosition(event);
      if (point) this.draft.push(point);
    },
    finishDraft() {
      if (this.drawing && this.draft.length >= 2) {
        this.$emit('route_finish', {points: this.draft.map(([x,y]) => ({x,y}))});
      }
    },
  },
  template: `
    <section class="play-diagram" aria-label="Play diagram" @keydown.esc="drawing ? $emit('route_cancel') : cancelDrag()">
      <svg ref="field" class="play-field" data-testid="play-field" role="group" aria-label="Route editing field" tabindex="0"
           :viewBox="'0 0 ' + fieldWidth + ' ' + fieldHeight"
           style="width:100%;display:block;max-height:64vh;border-radius:12px;background:#123e34;touch-action:none;user-select:none"
           :style="{cursor: drawing ? 'crosshair' : 'default'}" @click="addDraftPoint"
           @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag">
        <defs>
          <pattern :id="patternId" width="960" height="100" patternUnits="userSpaceOnUse">
            <rect width="960" height="100" fill="#123e34" />
            <rect width="960" height="50" fill="#19483c" />
            <path d="M0 0H960 M0 50H960" fill="none" stroke="#acc8af" opacity=".26" stroke-width="2"/>
            <path d="M316 0V100 M644 0V100" stroke="#c5deca" opacity=".38" stroke-width="12" stroke-dasharray="1.5 8.5"/>
          </pattern>
          <marker :id="arrowId" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M1 1L11 6L1 11L4 6Z" fill="context-stroke"/>
          </marker>
        </defs>
        <rect width="100%" height="100%" :fill="'url(#' + patternId + ')'"/>
        <rect x="14" y="14" :width="fieldWidth-28" :height="fieldHeight-28" rx="3" fill="none" stroke="#d3e7ce" opacity=".44" stroke-width="2"/>
        <g opacity=".7" pointer-events="none">
          <path :d="'M14 ' + originY + 'H' + (fieldWidth-14)" stroke="#e2eed7" stroke-dasharray="9 6" />
          <text x="23" :y="originY-8" font-size="10" fill="#ecf7eb" font-family="monospace">Y = 0</text>
        </g>
        <g v-for="index in routeOrder" :key="index" :data-route-index="index" role="button" :tabindex="drawing ? -1 : 0"
           :aria-label="'Select route ' + (index+1) + ', slot ' + routes[index].slot"
           :aria-pressed="index === selected" @click="selectRoute(index)" @keydown.enter.prevent="selectRoute(index)"
           :style="{cursor: drawing ? 'crosshair' : 'pointer'}"
           :opacity="drawing || (selected != null && index !== selected) ? .67 : 1">
          <polyline :points="polyline(points(index))" fill="none" stroke="transparent" stroke-width="20"
                    pointer-events="stroke" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline :points="polyline(points(index))" fill="none" :stroke="color(routes[index])"
                    :stroke-width="index === selected ? 5 : 3.5" stroke-linecap="round"
                    stroke-linejoin="round" :marker-end="'url(#' + arrowId + ')'"/>
          <g v-if="points(index).length" :transform="'translate('+points(index)[0].join(' ')+')'">
            <circle r="13" fill="#092c27" :stroke="color(routes[index])" stroke-width="2.5"/>
            <text text-anchor="middle" dy="4.5" font-size="13" font-weight="bold" :fill="color(routes[index])">{{routes[index].slot}}</text>
          </g>
          <g v-if="index === selected && !drawing" v-for="(p,j) in points(index)" :key="j"
             :transform="'translate('+p.join(' ')+')'" :data-point-index="j" style="cursor:grab"
             @pointerdown.stop.prevent="startDrag($event,j)">
            <title>Drag point {{j+1}} of slot {{routes[index].slot}}</title>
            <circle :r="j === 0 ? 15 : 11" fill="transparent" />
            <circle v-if="j !== 0" r="6" fill="#f5ffec" stroke="#113a30" stroke-width="2"/>
          </g>
        </g>
        <g v-if="drawing" pointer-events="none">
          <polyline :points="polyline(draft)" fill="none" stroke="#ffdc87" stroke-width="4" stroke-linecap="round" stroke-dasharray="7 5"/>
          <circle v-for="(p,i) in draft" :key="i" :cx="p[0]" :cy="p[1]" r="6" fill="#ffdc87" stroke="#17382c" stroke-width="2"/>
        </g>
        <text v-if="!routes.length && !drawing" :x="fieldWidth/2" y="92" text-anchor="middle"
              fill="#e3eee3" font-size="20" pointer-events="none">Choose Draw route to place your first points</text>
      </svg>
      <div v-if="drawing" style="display:flex;align-items:center;gap:.65rem;flex-wrap:wrap;padding:.65rem 0">
        <strong aria-live="polite">Slot {{draftSlot}} · {{draft.length}} points</strong>
        <span>Click the field to add points.</span>
        <q-btn flat dense no-caps label="Undo point" :disable="!draft.length" @click="draft.pop()"/>
        <q-btn unelevated no-caps color="primary" label="Finish route" :disable="draft.length < 2" @click="finishDraft"/>
        <q-btn flat dense no-caps label="Cancel" @click="$emit('route_cancel')"/>
      </div>
      <p v-else style="margin:.55rem 0 0;font-size:.8rem;color:inherit;opacity:.75">
        Select a route, then drag its points. Slot numbers mark route starts. Grid lines are schematic.
      </p>
    </section>
  `,
};
