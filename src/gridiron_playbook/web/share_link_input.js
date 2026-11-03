export default {
  props: {disabled: Boolean},
  emits: ['presence'],
  data() { return {text: ''}; },
  methods: {
    edit(value) {
      const hadText = !!this.text.trim();
      this.text = value;
      const hasText = !!value.trim();
      if (hadText !== hasText) this.$emit('presence', {hasText});
    },
    clear() { this.edit(''); },
  },
  template: `<q-input label="Share link" aria-label="Share link" class="pb-pasted-link" outlined dense
    :model-value="text" :disable="disabled" @update:model-value="edit"/>`,
};
