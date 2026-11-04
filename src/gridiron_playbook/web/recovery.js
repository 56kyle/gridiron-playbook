const SESSION_KEY = 'gridiron.working-copy';
const RECENT_KEY = 'gridiron.recent-working-copy';
const validId = value => /^[0-9a-f]{32}$/.test(value || '');
const newId = () => crypto.randomUUID().replaceAll('-', '');

export default {
  props: { failed: Boolean },
  data() { return { workspaceId: null, release: null, stopped: false, durable: false, storageFailed: false }; },
  mounted() {
    window.addEventListener('beforeunload', this.beforeUnload);
    window.addEventListener('focus', this.remember);
    this.initialize();
  },
  beforeUnmount() {
    this.stopped = true;
    this.release?.();
    window.removeEventListener('beforeunload', this.beforeUnload);
    window.removeEventListener('focus', this.remember);
  },
  methods: {
    remember() {
      if (this.durable && this.workspaceId) {
        try { localStorage.setItem(RECENT_KEY, this.workspaceId); }
        catch { this.unavailable(); }
      }
    },
    unavailable() {
      if (!this.storageFailed) { this.storageFailed = true; this.$emit('unavailable'); }
    },
    beforeUnload(event) {
      if (this.failed) { event.preventDefault(); event.returnValue = ''; }
    },
    async acquire(id) {
      if (!navigator.locks) return false;
      return new Promise((resolve, reject) => {
        navigator.locks.request(`gridiron-working-${id}`, {ifAvailable: true}, lock => {
          if (!lock || this.stopped) { resolve(false); return; }
          return new Promise(release => { this.release = release; resolve(true); });
        }).catch(reject);
      });
    },
    async initialize() {
      try {
        this.release?.();
        this.release = null;
        const session = sessionStorage.getItem(SESSION_KEY);
        const recent = localStorage.getItem(RECENT_KEY);
        const source = validId(session) ? session : validId(recent) ? recent : null;
        let id = source || newId();
        if (!await this.acquire(id)) { id = newId(); await this.acquire(id); }
        if (this.stopped) return;
        this.workspaceId = id;
        this.$emit('ready', {workspace_id: id, source_id: source});
      } catch {
        this.unavailable();
      }
    },
    async saved(id, revision) {
      if (this.stopped) return;
      try {
        if (id !== this.workspaceId) {
          this.release?.();
          this.release = null;
          this.workspaceId = id;
          await this.acquire(id);
        }
        sessionStorage.setItem(SESSION_KEY, id);
        localStorage.setItem(RECENT_KEY, id);
        this.durable = true;
        this.$el.setAttribute('data-recovery-status', 'ready');
        this.$el.setAttribute('data-recovery-revision', String(revision));
        if (this.storageFailed) { this.storageFailed = false; this.$emit('available'); }
      } catch {
        this.unavailable();
      }
    },
  },
  template: '<span hidden aria-hidden="true"></span>',
};
