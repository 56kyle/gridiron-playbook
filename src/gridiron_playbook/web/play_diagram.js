// The lineup comes from the game's formation data; points are the editable save data.
export default {
  props: {
    lineup: Array, routes: Array, selected: Number, draftSlot: Number, draftLabel: String,
    fieldWidth: Number, fieldHeight: Number, diagramId: Number, originY: Number, canDraw: Boolean,
  },
  emits: ['route_select', 'route_start', 'point_move', 'route_finish', 'route_cancel'],
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
    draftOrigin() { return this.origin(this.draftSlot); },
    minDraftPoints() { return this.draftOrigin ? 1 : 2; },
  },
  methods: {
    origin(slot) {
      return this.lineup.find(player => player.slot === slot)?.at;
    },
    points(index) {
      const points = this.routes[index].points;
      if (!this.drag || index !== this.selected) return points;
      return points.map((p, i) => i === this.drag.index ? this.drag.position : p);
    },
    polyline(points, origin) {
      return (origin ? [origin, ...points] : points).map(p => p.join(',')).join(' ');
    },
    playerRoute(slot) {
      if (this.routes[this.selected]?.slot === slot) return this.selected;
      return this.routes.findIndex(route => route.slot === slot);
    },
    playerWidth(label) { return Math.max(27, label.length * 8.5 + 12); },
    selectRoute(index) {
      if (!this.drawing && index !== this.selected) this.$emit('route_select', {route: index});
    },
    selectPlayer(slot) {
      if (this.drawing) return;
      const route = this.playerRoute(slot);
      if (route !== -1) this.selectRoute(route);
      else if (this.canDraw) this.$emit('route_start', {slot});
    },
    fieldPosition(event) {
      const matrix = this.$refs.field.getScreenCTM();
      if (!matrix) return null;
      const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      return [Math.min(this.fieldWidth, Math.max(0, p.x)), Math.min(this.fieldHeight, Math.max(0, p.y))];
    },
    startDrag(event, index) {
      if (this.drawing || this.drag || event.button !== 0 || !event.isPrimary) return;
      const point = this.routes[this.selected].points[index];
      const pointer = this.fieldPosition(event);
      if (!pointer) return;
      this.$refs.field.setPointerCapture(event.pointerId);
      this.drag = {
        index, pointerId: event.pointerId, position: point, start: point,
        offset: [point[0] - pointer[0], point[1] - pointer[1]],
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
      if (this.drawing && this.draft.length >= this.minDraftPoints) {
        this.$emit('route_finish', {points: this.draft.map(([x, y]) => ({x, y}))});
      }
    },
  },
  template: `
    <section class="play-diagram" aria-label="Play diagram" @keydown.esc="drawing ? $emit('route_cancel') : cancelDrag()">
      <svg ref="field" class="play-field" data-testid="play-field" role="group" aria-label="Route editing field" tabindex="0"
           :viewBox="'0 0 ' + fieldWidth + ' ' + fieldHeight"
           style="width:100%;display:block;background:var(--pb-field);touch-action:none;user-select:none"
           :style="{cursor: drawing ? 'crosshair' : 'default'}" @click="addDraftPoint"
           @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag">
        <defs>
          <pattern :id="patternId" :width="fieldWidth" height="96" patternUnits="userSpaceOnUse" :y="originY">
            <rect :width="fieldWidth" height="96" fill="var(--pb-field)"/>
            <path :d="'M0 0H'+fieldWidth" stroke="var(--pb-grid)" stroke-width="2"/>
            <path :d="'M0 48H'+fieldWidth" stroke="var(--pb-grid-minor)"/>
            <path :d="'M'+fieldWidth/3+' 0V96 M'+2*fieldWidth/3+' 0V96'" fill="none" stroke="var(--pb-grid)"
                  stroke-width="9" stroke-dasharray="1 8"/>
          </pattern>
          <marker :id="arrowId" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M1 1L11 6L1 11" fill="none" stroke="context-stroke" stroke-width="2.2" stroke-linejoin="round"/>
          </marker>
        </defs>
        <rect width="100%" height="100%" :fill="'url(#'+patternId+')'"/>
        <g pointer-events="none" fill="none">
          <path :d="'M18 0V'+fieldHeight+' M'+(fieldWidth-18)+' 0V'+fieldHeight" stroke="var(--pb-grid)"/>
          <path :d="'M18 '+originY+'H'+(fieldWidth-18)" stroke="var(--pb-baseline)" stroke-width="1.5">
            <title>Line of scrimmage</title>
          </path>
        </g>

        <g v-for="index in routeOrder" :key="'r'+index" :data-route-index="index" :data-position="routes[index].label"
           role="button" :tabindex="drawing ? -1 : 0" :aria-label="'Select '+routes[index].label+', slot '+routes[index].slot+', route '+(index+1)"
           :aria-pressed="index === selected" @click="selectRoute(index)" @keydown.enter.prevent="selectRoute(index)"
           @keydown.space.prevent="selectRoute(index)" :style="{cursor: drawing ? 'crosshair' : 'pointer'}"
           :opacity="drawing || (selected != null && index !== selected) ? .62 : 1">
          <polyline :points="polyline(points(index), origin(routes[index].slot))" fill="none" stroke="transparent"
                    stroke-width="24" pointer-events="stroke" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline :points="polyline(points(index), origin(routes[index].slot))" fill="none" stroke="var(--pb-position-color)"
                    :stroke-width="index === selected ? 4 : 3" stroke-linecap="round" stroke-linejoin="round"
                    :marker-end="points(index).length ? 'url(#'+arrowId+')' : undefined"/>
          <g v-if="!origin(routes[index].slot) && points(index).length" data-first-waypoint-label
             :transform="'translate('+points(index)[0].join(' ')+')'">
            <title>First saved point · {{routes[index].label}}</title>
            <circle r="4" fill="var(--pb-position-color)"/>
            <text x="9" y="-9" font-size="15" font-weight="700" paint-order="stroke" stroke="var(--pb-field)"
                  stroke-width="4" fill="var(--pb-position-color)">{{routes[index].label}}</text>
          </g>
        </g>

        <g v-if="drawing" :data-position="draftLabel" pointer-events="none">
          <polyline :points="polyline(draft, draftOrigin)" fill="none" stroke="var(--pb-position-color)"
                    stroke-width="3.5" stroke-linecap="round" stroke-dasharray="7 5"/>
          <circle v-for="(p,i) in draft" :key="i" :cx="p[0]" :cy="p[1]" r="5.5"
                  fill="var(--pb-position-color)" stroke="var(--pb-field)" stroke-width="2"/>
        </g>

        <g v-for="player in lineup" :key="'s'+player.slot" :data-lineup-slot="player.slot" :data-position="player.label"
           :transform="'translate('+player.at.join(' ')+')'" role="button" :tabindex="drawing ? -1 : 0"
           :aria-label="(playerRoute(player.slot) < 0 ? 'Draw ' : 'Select ') + player.label + ' route, slot ' + player.slot"
           @click="selectPlayer(player.slot)" @keydown.enter.prevent="selectPlayer(player.slot)" @keydown.space.prevent="selectPlayer(player.slot)"
           :style="{cursor: drawing ? 'crosshair' : 'pointer'}"
           :opacity="drawing && player.slot !== draftSlot ? .65 : 1">
          <title>{{player.label}} · Slot {{player.slot}}</title>
          <rect :x="-playerWidth(player.label)/2" y="-13" :width="playerWidth(player.label)" height="26" rx="12"
                fill="var(--pb-input)" stroke="var(--pb-position-color)"
                :stroke-width="player.slot === draftSlot || playerRoute(player.slot) === selected ? 3 : 1.75"/>
          <text text-anchor="middle" dy="5" font-size="14" font-weight="750" fill="var(--pb-ink)">{{player.label}}</text>
        </g>

        <g v-if="selected != null && routes[selected] && !drawing" :data-position="routes[selected].label">
          <g v-for="(p,j) in points(selected)" :key="j" :transform="'translate('+p.join(' ')+')'" :data-point-index="j"
             style="cursor:grab" @pointerdown.stop.prevent="startDrag($event,j)">
            <title>{{routes[selected].label}} · Point {{j+1}}</title>
            <circle r="12" fill="transparent"/>
            <circle r="5.75" fill="var(--pb-field)" stroke="var(--pb-position-color)" stroke-width="2.5"/>
          </g>
        </g>
      </svg>
      <div v-if="drawing" class="pb-draft-tools" style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;padding:.65rem 0">
        <strong aria-live="polite">{{draftLabel}} · {{draft.length}} {{draft.length === 1 ? 'point' : 'points'}}</strong>
        <q-btn flat dense no-caps label="Undo point" :disable="!draft.length" @click="draft.pop()"/>
        <q-btn unelevated no-caps color="primary" label="Finish route" :disable="draft.length < minDraftPoints" @click="finishDraft"/>
        <q-btn flat dense no-caps label="Cancel" @click="$emit('route_cancel')"/>
      </div>
    </section>
  `,
};
