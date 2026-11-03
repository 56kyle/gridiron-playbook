function insertionOnRoute(points, origin, x, y, hitRadius) {
  let nearest = {point: points.length, x, y};
  let bestDistance = hitRadius;
  for (let index = origin ? 0 : 1; index < points.length; index++) {
    const start = points[index - 1] ?? origin;
    const dx = points[index][0] - start[0], dy = points[index][1] - start[1];
    const lengthSquared = dx * dx + dy * dy;
    if (!lengthSquared) continue;
    const t = ((x - start[0]) * dx + (y - start[1]) * dy) / lengthSquared;
    if (t < 0 || t > 1) continue;
    const px = start[0] + t * dx, py = start[1] + t * dy;
    const distance = Math.hypot(x - px, y - py);
    if (distance < bestDistance) {
      bestDistance = distance;
      nearest = {point: index, x: px, y: py};
    }
  }
  return nearest;
}

export default {
  props: {
    lineup: Array, routes: Array, selected: Number, initialPoint: Number, draftSlot: Number, draftLabel: String,
    fieldWidth: Number, fieldHeight: Number, diagramId: Number, originY: Number, canDraw: Boolean, canEditNodes: Boolean,
    interactive: Boolean,
  },
  emits: ['route_select', 'route_start', 'point_move', 'point_insert', 'point_delete', 'block_add', 'route_finish', 'route_cancel'],
  data() {
    return {
      drag: null, draft: [], undonePoints: [], previewPoint: null,
      activePoint: this.initialPoint ?? null, addingNode: false, insertion: null,
    };
  },
  mounted() {
    if (this.initialPoint != null && document.activeElement === document.body) {
      this.$refs.field.focus({preventScroll: true});
    }
  },
  computed: {
    fieldEvents() {
      return this.interactive ? {
        click: this.placePoint, pointermove: this.movePointer, pointerleave: this.clearPreview,
        pointerup: this.endDrag, lostpointercapture: this.cancelDrag,
        pointercancel: () => { this.clearPreview(); this.cancelDrag(); },
      } : {};
    },
    drawing() { return this.draftSlot != null; },
    patternId() { return 'field-grid-' + this.diagramId; },
    arrowId() { return 'route-arrow-' + this.diagramId; },
    routeOrder() {
      const indices = this.routes.map((_, i) => i).filter(i => i !== this.selected);
      if (this.selected != null && this.routes[this.selected]) indices.push(this.selected);
      return indices;
    },
    draftOrigin() { return this.origin(this.draftSlot); },
    previewStart() { return this.draft.at(-1) ?? this.draftOrigin; },
    minDraftPoints() { return this.draftOrigin ? 1 : 2; },
    selectedRoute() { return this.routes[this.selected]; },
    extensionStart() { return this.selectedRoute.points.at(-1) ?? this.origin(this.selectedRoute.slot); },
    blockTarget() { return this.activePoint ?? this.selectedRoute.points.length - 1; },
    canDeleteNode() {
      return this.activePoint !== null && this.selectedRoute.points.length > (this.origin(this.selectedRoute.slot) ? 1 : 2);
    },
  },
  methods: {
    selectionEvents(select) {
      if (!this.interactive) return {};
      return {click: select, keydown: event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select();
        }
      }};
    },
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
    markerLabel(label) { return label === 'WR-L' || label === 'WR-R' ? 'WR' : label; },
    playerWidth(label) { return Math.max(27, this.markerLabel(label).length * 8.5 + 12); },
    selectRoute(index) {
      if (!this.drawing && !this.addingNode && index !== this.selected) this.$emit('route_select', {route: index});
    },
    selectPlayer(slot) {
      if (this.drawing || this.addingNode) return;
      const route = this.playerRoute(slot);
      if (route !== -1) this.selectRoute(route);
      else if (this.canDraw) this.$emit('route_start', {slot});
    },
    fieldPosition(clientX, clientY) {
      const matrix = this.$refs.field.getScreenCTM();
      if (!matrix) return null;
      const p = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
      return [Math.min(this.fieldWidth, Math.max(0, p.x)), Math.min(this.fieldHeight, Math.max(0, p.y))];
    },
    draftPosition(event) {
      // Click events report whole CSS pixels even when pointer movement has subpixel precision.
      return this.fieldPosition(Math.floor(event.clientX), Math.floor(event.clientY));
    },
    insertionAt(event) {
      const position = this.draftPosition(event);
      if (!position) return null;
      const matrix = this.$refs.field.getScreenCTM();
      const hitRadius = 12 / Math.hypot(matrix.a, matrix.b);
      return insertionOnRoute(this.selectedRoute.points, this.origin(this.selectedRoute.slot), ...position, hitRadius);
    },
    toggleAddNode() {
      this.addingNode = !this.addingNode;
      this.insertion = null;
      this.$refs.field.focus({preventScroll: true});
    },
    deleteNode() {
      if (this.canDeleteNode) this.$emit('point_delete', {point: this.activePoint});
    },
    startDrag(event, index) {
      if (this.drawing || this.addingNode || this.drag || event.button !== 0 || !event.isPrimary) return;
      const point = this.routes[this.selected].points[index];
      const pointer = this.fieldPosition(event.clientX, event.clientY);
      if (!pointer) return;
      this.$refs.field.focus({preventScroll: true});
      if (this.canEditNodes) this.activePoint = index;
      this.$refs.field.setPointerCapture(event.pointerId);
      this.drag = {
        index, pointerId: event.pointerId, position: point, start: point,
        offset: [point[0] - pointer[0], point[1] - pointer[1]],
      };
    },
    moveDrag(event) {
      if (!this.drag || event.pointerId !== this.drag.pointerId) return;
      const pointer = this.fieldPosition(event.clientX, event.clientY);
      if (!pointer) return;
      this.drag.position = [
        Math.min(this.fieldWidth, Math.max(0, pointer[0] + this.drag.offset[0])),
        Math.min(this.fieldHeight, Math.max(0, pointer[1] + this.drag.offset[1])),
      ];
    },
    movePointer(event) {
      if (!event.isPrimary) return;
      if (this.drawing) this.previewPoint = this.draftPosition(event);
      else if (this.addingNode) this.insertion = this.insertionAt(event);
      else this.moveDrag(event);
    },
    clearPreview() {
      this.previewPoint = null;
      this.insertion = null;
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
    placePoint(event) {
      if (event.button !== 0) return;
      if (this.addingNode) {
        const insertion = this.insertionAt(event);
        if (insertion) {
          this.addingNode = false;
          this.insertion = null;
          this.$emit('point_insert', insertion);
        }
        return;
      }
      if (!this.drawing) return;
      const point = this.draftPosition(event);
      if (!point) return;
      this.draft.push(point);
      this.undonePoints = [];
      this.previewPoint = null;
    },
    undoPoint() {
      if (this.draft.length) this.undonePoints.push(this.draft.pop());
    },
    redoPoint() {
      if (this.undonePoints.length) this.draft.push(this.undonePoints.pop());
    },
    cancelDraft() {
      this.previewPoint = null;
      this.$emit('route_cancel');
    },
    handleShortcut(event) {
      if (this.drawing) {
        switch (event.detail) {
          case 'remove-point':
          case 'undo': this.undoPoint(); break;
          case 'redo': this.redoPoint(); break;
          case 'finish': this.finishDraft(); break;
          case 'cancel': this.cancelDraft(); break;
          default: return;
        }
      } else if (this.drag && event.detail === 'cancel') {
        this.cancelDrag();
      } else if (this.addingNode && event.detail === 'cancel') {
        this.toggleAddNode();
      } else if (this.activePoint !== null && event.detail === 'cancel') {
        this.activePoint = null;
      } else if (event.detail === 'delete-node' && !this.drag && !this.addingNode && this.activePoint !== null &&
                 this.$el.contains(document.activeElement)) {
        this.deleteNode();
      } else {
        return;
      }
      event.preventDefault();
    },
    finishDraft() {
      if (this.drawing && this.draft.length >= this.minDraftPoints) {
        this.previewPoint = null;
        this.$emit('route_finish', {points: this.draft.map(([x, y]) => ({x, y}))});
      }
    },
  },
  template: `
    <section class="play-diagram" aria-label="Play diagram" v-on="interactive ? {'playbook-shortcut': handleShortcut} : {}">
      <svg ref="field" class="play-field" data-testid="play-field" :role="interactive ? 'group' : 'img'"
           :aria-label="interactive ? 'Route editing field' : 'Route diagram'" :tabindex="interactive ? 0 : undefined"
           :viewBox="'0 0 ' + fieldWidth + ' ' + fieldHeight"
           style="width:100%;display:block;background:var(--pb-field);user-select:none"
           :style="{cursor: drawing || addingNode ? 'crosshair' : 'default', touchAction: interactive ? 'none' : 'auto'}"
           v-on="fieldEvents">
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
           :role="interactive ? 'button' : undefined" :tabindex="interactive ? (drawing || addingNode ? -1 : 0) : undefined"
           :aria-label="interactive ? 'Select '+routes[index].label+', slot '+routes[index].slot+', route '+(index+1) : undefined"
           :aria-pressed="interactive ? index === selected : undefined" v-on="selectionEvents(() => selectRoute(index))"
           :style="{cursor: interactive ? (drawing ? 'crosshair' : 'pointer') : 'default'}"
           :opacity="drawing || (selected != null && index !== selected) ? .62 : 1">
          <polyline :points="polyline(points(index), origin(routes[index].slot))" fill="none" stroke="transparent"
                    stroke-width="24" pointer-events="stroke" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline :points="polyline(points(index), origin(routes[index].slot))" fill="none" stroke="var(--pb-position-color)"
                    :stroke-width="index === selected ? 4 : 3" stroke-linecap="round" stroke-linejoin="round"
                    :marker-end="points(index).length && !routes[index].endsWithBlock ? 'url(#'+arrowId+')' : undefined"/>
          <g v-if="!origin(routes[index].slot) && points(index).length" data-first-waypoint-label
             :transform="'translate('+points(index)[0].join(' ')+')'">
            <title>First saved point · {{routes[index].label}}</title>
            <circle r="4" fill="var(--pb-position-color)"/>
            <text x="9" y="-9" font-size="15" font-weight="700" paint-order="stroke" stroke="var(--pb-field)"
                  stroke-width="4" fill="var(--pb-position-color)">{{markerLabel(routes[index].label)}}</text>
          </g>
        </g>

        <g v-if="drawing" :data-position="draftLabel" pointer-events="none">
          <polyline data-draft-path :points="polyline(draft, draftOrigin)" fill="none" stroke="var(--pb-position-color)"
                    stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
          <line v-if="previewStart && previewPoint" data-draft-preview :x1="previewStart[0]" :y1="previewStart[1]"
                :x2="previewPoint[0]" :y2="previewPoint[1]" stroke="var(--pb-position-color)"
                stroke-width="3.5" stroke-linecap="round" stroke-dasharray="7 5"/>
          <circle v-for="(p,i) in draft" :key="i" :cx="p[0]" :cy="p[1]" r="5.5"
                  fill="var(--pb-position-color)" stroke="var(--pb-field)" stroke-width="2"/>
        </g>

        <g v-for="player in lineup" :key="'s'+player.slot" :data-lineup-slot="player.slot" :data-position="player.label"
           :transform="'translate('+player.at.join(' ')+')'" :role="interactive ? 'button' : undefined"
           :tabindex="interactive ? (drawing || addingNode ? -1 : 0) : undefined"
           :aria-label="interactive ? (playerRoute(player.slot) < 0 ? 'Draw ' : 'Select ') + player.label + ' route, slot ' + player.slot : undefined"
           v-on="selectionEvents(() => selectPlayer(player.slot))" :style="{cursor: interactive ? (drawing ? 'crosshair' : 'pointer') : 'default'}"
           :opacity="drawing && player.slot !== draftSlot ? .65 : 1">
          <title>{{player.label}} · Slot {{player.slot}}</title>
          <rect :x="-playerWidth(player.label)/2" y="-13" :width="playerWidth(player.label)" height="26" rx="12"
                fill="var(--pb-input)" stroke="var(--pb-position-color)"
                :stroke-width="player.slot === draftSlot || playerRoute(player.slot) === selected ? 3 : 1.75"/>
          <text text-anchor="middle" dy="5" font-size="14" font-weight="750" fill="var(--pb-ink)">{{markerLabel(player.label)}}</text>
        </g>

        <g v-if="selectedRoute && !drawing" :data-position="selectedRoute.label">
          <g v-for="(p,j) in points(selected)" :key="j" :transform="'translate('+p.join(' ')+')'" :data-point-index="j"
             :role="canEditNodes ? 'button' : undefined" :tabindex="canEditNodes && !addingNode ? 0 : -1"
             :aria-label="'Select node '+(j+1)" :aria-pressed="activePoint === j"
             style="cursor:grab" @pointerdown.stop.prevent="startDrag($event,j)"
             @focus="canEditNodes && (activePoint = j)" @click="canEditNodes && (activePoint = j)"
             @keydown.enter.prevent="canEditNodes && (activePoint = j)"
             @keydown.space.prevent="canEditNodes && (activePoint = j)">
            <title>{{selectedRoute.label}} · Node {{j+1}}</title>
            <circle r="12" fill="transparent"/>
            <circle :r="activePoint === j ? 6 : 4" :fill="activePoint === j ? 'var(--pb-position-color)' : 'var(--pb-field)'"
                    :stroke="activePoint === j ? 'var(--pb-ink)' : 'var(--pb-position-color)'" stroke-width="2"/>
          </g>
        </g>
        <g v-if="addingNode" :data-position="selectedRoute.label">
          <rect width="100%" height="100%" fill="transparent"/>
          <g v-if="insertion" pointer-events="none" stroke="var(--pb-position-color)">
            <line v-if="insertion.point === selectedRoute.points.length && extensionStart" :x1="extensionStart[0]" :y1="extensionStart[1]"
                  :x2="insertion.x" :y2="insertion.y" stroke-width="3" stroke-dasharray="7 5"/>
            <circle :cx="insertion.x" :cy="insertion.y" r="5.5" fill="var(--pb-field)" stroke-width="2.5"/>
          </g>
        </g>
      </svg>
      <div v-if="drawing" class="pb-draft-tools">
        <strong aria-live="polite">{{draftLabel}} · {{draft.length}} {{draft.length === 1 ? 'point' : 'points'}}</strong>
        <q-btn flat dense no-caps label="Undo point" :disable="!draft.length" @click="undoPoint"
               aria-keyshortcuts="Control+Z Meta+Z Backspace" title="Undo point (Ctrl/⌘+Z or Backspace)"/>
        <q-btn flat dense no-caps label="Redo point" :disable="!undonePoints.length" @click="redoPoint"
               aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y" title="Redo point (Ctrl/⌘+Shift+Z or Ctrl+Y)"/>
        <q-btn unelevated no-caps color="primary" label="Finish route" :disable="draft.length < minDraftPoints"
               @click="finishDraft" aria-keyshortcuts="Enter" title="Finish route (Enter)"/>
        <q-btn flat dense no-caps label="Cancel" @click="cancelDraft" aria-keyshortcuts="Escape" title="Cancel (Esc)"/>
      </div>
      <div v-else-if="selectedRoute && canEditNodes" class="pb-node-tools" role="group" aria-label="Edit route">
        <q-btn dense no-caps label="Add node" :flat="!addingNode" :unelevated="addingNode" :color="addingNode ? 'primary' : undefined"
               :aria-pressed="addingNode" @click="toggleAddNode" title="Click a segment to insert a node or open field to extend the route"/>
        <q-btn flat dense no-caps label="Delete node" :disable="addingNode || !canDeleteNode" @click="deleteNode"
               aria-keyshortcuts="Delete" title="Delete the selected node (Delete)"/>
        <q-btn flat dense no-caps label="Add block" :disable="addingNode || blockTarget < 0"
               @click="$emit('block_add', {point: blockTarget})"
               :title="activePoint === null ? 'Add a block at the end of the route' : 'Add a block at node '+(activePoint+1)"/>
      </div>
    </section>
  `,
};
