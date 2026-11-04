export default {
  props: { generation: Number, activeTab: String, selected: Array, disabled: Boolean },
  data() { return { drag: null, marker: null, scrolls: {}, focusTabs: false }; },
  updated() {
    this.$nextTick(() => {
      const list = this.$el.querySelector('[data-play-list]');
      if (list) list.scrollTop = this.scrolls[list.dataset.playList] || 0;
      if (this.focusTabs) {
        this.$el.querySelector('[role="tab"][aria-selected="true"]')?.focus();
        this.focusTabs = false;
      }
    });
  },
  methods: {
    scroll(event) {
      const list = event.target;
      if (list.dataset?.playList) this.scrolls[list.dataset.playList] = list.scrollTop;
    },
    key(event) {
      const tab = event.target.closest('[role="tab"]');
      if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = [...this.$el.querySelectorAll('[role="tab"]')];
      const current = tabs.indexOf(tab);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
        (current + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
      event.preventDefault();
      this.focusTabs = true;
      tabs[index].click();
    },
    start(event) {
      const handle = event.target.closest('[data-drag-play]');
      if (!handle || this.disabled) { event.preventDefault(); return; }
      const index = Number(handle.dataset.dragPlay);
      this.drag = {
        generation: this.generation, source: this.activeTab,
        indices: this.selected.includes(index) ? this.selected : [index],
      };
      event.dataTransfer.effectAllowed = 'copyMove';
      event.dataTransfer.setData('application/x-gridiron-plays', JSON.stringify(this.drag));
    },
    target(event) {
      const tab = event.target.closest('[data-tab-id]');
      if (tab) return { element: tab, destination: tab.dataset.tabId, insertion: 0, after: false };
      const list = event.target.closest('[data-play-list]');
      if (!list) return;
      const row = event.target.closest('[data-play-index]');
      if (!row) return { element: list, destination: list.dataset.playList, insertion: Number(list.dataset.playCount), after: true };
      const bounds = row.getBoundingClientRect();
      const after = event.clientY > bounds.top + bounds.height / 2;
      return { element: row, destination: list.dataset.playList, insertion: Number(row.dataset.playIndex) + Number(after), after };
    },
    over(event) {
      if (!this.drag || this.disabled) return;
      const target = this.target(event);
      if (!target) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = (event.ctrlKey || event.metaKey) && target.destination !== this.drag.source ? 'copy' : 'move';
      this.clearMarker();
      target.element.classList.add(target.after ? 'pb-drop-after' : 'pb-drop-before');
      this.marker = target.element;
    },
    drop(event) {
      const target = this.target(event);
      if (target && this.drag && !this.disabled) {
        event.preventDefault();
        this.$emit('drop_plays', { ...this.drag, destination: target.destination, insertion: target.insertion, is_copy: event.ctrlKey || event.metaKey });
      }
      this.finish();
    },
    clearMarker() {
      this.marker?.classList.remove('pb-drop-before', 'pb-drop-after');
      this.marker = null;
    },
    finish() { this.clearMarker(); this.drag = null; },
  },
  template: '<div @dragstart="start" @dragover="over" @drop="drop" @dragend="finish" @scroll.capture="scroll" @keydown="key"><slot /></div>',
};
