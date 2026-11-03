export default {
  props: {options: Array, result: Object, longLink: Object, problem: String, viewerProblem: String, downloading: Boolean},
  emits: ['measure', 'reveal', 'download'],
  data() { return {precision: 'exact', confirming: false}; },
  computed: {
    measured() { return this.result?.precision === this.precision; },
    oversizedUrl() { return this.longLink?.precision === this.precision ? this.longLink.url : null; },
    urgent() { return this.result?.level === 'nitro'; },
    count() { return this.result?.length.toLocaleString('en-US'); },
  },
  mounted() { if (!this.viewerProblem) this.$emit('measure', {precision: this.precision}); },
  methods: {
    choose(precision) {
      this.confirming = false;
      this.precision = precision;
      if (!this.viewerProblem) this.$emit('measure', {precision});
    },
    requestCopy(event) {
      if (!this.measured || this.problem) return;
      if (this.result.level) {
        this.confirming = true;
        this.$emit('reveal', {precision: this.precision});
      } else {
        this.copy(this.result.url, event);
      }
    },
    async copy(url, event) {
      if (!url) return;
      const field = event.target.closest('.pb-copy-surface').querySelector('input[aria-label="Share link"]');
      try {
        await navigator.clipboard.writeText(url);
        this.confirming = false;
        Quasar.Notify.create('Link copied');
      } catch {
        field.focus();
        field.select();
        Quasar.Notify.create('Use the copy command to copy the selected link.');
      }
    },
  },
  template: `
    <div class="pb-copy-surface column q-gutter-y-sm">
      <q-select label="Precision" aria-label="Precision" outlined dense emit-value map-options
                :model-value="precision" :options="options" @update:model-value="choose"/>
      <div v-if="viewerProblem">{{viewerProblem}}</div>
      <div v-else-if="problem" role="alert">{{problem}}</div>
      <div v-else data-testid="share-length" aria-live="polite">{{ measured ? count + ' characters' : 'Measuring link…' }}</div>
      <template v-if="measured">
        <q-input v-if="!result.level" label="Share link" aria-label="Share link" readonly outlined dense :model-value="result.url"/>
        <div v-else :class="urgent ? 'text-negative' : 'text-warning'">
          {{urgent ? 'Exceeds Discord Nitro’s 4,000-character limit.' : 'Exceeds Discord’s 2,000-character limit without Nitro.'}}
        </div>
      </template>
      <q-btn v-if="!viewerProblem" label="Copy link" icon="content_copy" color="primary" unelevated no-caps
             :disable="!measured || !!problem" @click="requestCopy"/>
      <div class="row q-gutter-xs">
        <q-btn label="Download share file" icon="download" flat no-caps
               :disable="downloading" @click="$emit('download', {precision})"/>
        <q-btn v-if="precision !== 'exact'" label="Download exact file" flat no-caps
               :disable="downloading" @click="$emit('download', {precision: 'exact'})"/>
      </div>
      <q-dialog v-model="confirming">
        <q-card v-if="measured" class="pb-dialog pb-copy-surface column" aria-live="polite">
          <h2 class="pb-heading q-ma-none">{{urgent ? 'Discord Nitro limit exceeded' : 'Discord message limit exceeded'}}</h2>
          <div>{{count}} characters. {{urgent
            ? 'This exceeds even Discord Nitro’s 4,000-character message limit. Send the share file in Discord.'
            : 'This exceeds Discord’s 2,000-character message limit without Nitro. Send the share file instead.'}}</div>
          <q-input label="Share link" aria-label="Share link" readonly outlined dense :model-value="oversizedUrl || ''"/>
          <div class="row q-gutter-sm">
            <q-btn flat no-caps label="Cancel" @click="confirming = false"/>
            <q-btn unelevated no-caps label="Copy anyway" :color="urgent ? 'negative' : 'primary'"
                   :disable="!oversizedUrl" @click="copy(oversizedUrl, $event)"/>
          </div>
        </q-card>
      </q-dialog>
    </div>
  `,
};
