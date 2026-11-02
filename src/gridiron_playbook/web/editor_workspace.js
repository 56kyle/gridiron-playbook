function shortcutFor(event) {
  if (event.altKey) return;
  if (event.ctrlKey || event.metaKey) {
    const key = event.key.toLowerCase();
    if (key === 'z') return event.shiftKey ? 'redo' : 'undo';
    if (key === 'y' && event.ctrlKey && !event.shiftKey) return 'redo';
  } else if (!event.shiftKey) {
    if (event.key === 'Enter') return 'finish';
    if (event.key === 'Escape') return 'cancel';
    if (event.key === 'Backspace') return 'remove-point';
    if (event.key === 'Delete') return 'delete-node';
  }
}

export default {
  mounted() { window.addEventListener('keydown', this.onKeyDown, true); },
  beforeUnmount() { window.removeEventListener('keydown', this.onKeyDown, true); },
  methods: {
    onKeyDown(event) {
      if (event.defaultPrevented || event.isComposing || event.repeat) return;
      const action = shortcutFor(event);
      if (!action) return;
      const target = event.target;
      if (target.isContentEditable || target.closest?.('input, textarea, select, [role="textbox"], [role="combobox"]')) return;
      if (document.querySelector('.q-dialog, .q-menu')) return;
      if (action === 'finish' && target.closest?.('button, a[href]')) return;

      const diagram = this.$el.querySelector('.play-diagram');
      const shortcut = new CustomEvent('playbook-shortcut', {detail: action, cancelable: true});
      if (!diagram || diagram.dispatchEvent(shortcut)) {
        const button = this.$el.querySelector(`button[data-history="${action}"]:enabled`);
        if (!button) return;
        button.click();
      }
      event.preventDefault();
      event.stopPropagation();
    },
  },
  template: '<main><slot /></main>',
};
