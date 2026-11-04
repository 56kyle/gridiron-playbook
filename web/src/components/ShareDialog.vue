<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { encodeShare } from "../engine";
import type { ShareKind, SharePrecision } from "../types";
import { downloadBytes, fileStem, message, shareUrl } from "../files";
import DialogFrame from "./DialogFrame.vue";

const props = defineProps<{ document: string; indices: number[]; kind: ShareKind; name: string }>();
const emit = defineEmits<{ close: [] }>();
const precision = ref<SharePrecision>("exact");
const data = ref<Uint8Array>();
const link = ref("");
const error = ref("");
const status = ref("");
const busy = ref(false);
const warning = ref(false);
let generation = 0;
const level = computed(() => (link.value.length > 4000 ? "nitro" : link.value.length > 2000 ? "standard" : null));
const warningText = computed(() =>
  level.value === "nitro"
    ? "This link exceeds Discord’s 4,000-character Nitro message limit. Send the share file instead, or copy the link for another service."
    : "This link exceeds Discord’s 2,000-character non-Nitro message limit. Send the share file instead, or copy the link for another service."
);

watch(
  precision,
  async () => {
    const current = ++generation;
    busy.value = true;
    error.value = "";
    status.value = "";
    data.value = undefined;
    link.value = "";
    warning.value = false;
    try {
      const bytes = await encodeShare(props.document, props.indices, props.kind, precision.value);
      if (current !== generation) return;
      data.value = bytes;
      link.value = shareUrl(bytes);
    } catch (cause) {
      if (current === generation) error.value = message(cause);
    } finally {
      if (current === generation) busy.value = false;
    }
  },
  { immediate: true }
);

async function copy(confirmed = false): Promise<void> {
  if (level.value && !confirmed) {
    warning.value = true;
    return;
  }
  warning.value = false;
  try {
    await navigator.clipboard.writeText(link.value);
    status.value = "Link copied";
  } catch {
    error.value = "Clipboard access was denied. Select and copy the link above.";
  }
}
function download(): void {
  if (data.value) downloadBytes(data.value, `${fileStem(props.name)}.gridironshare`);
}
async function exact(): Promise<void> {
  try {
    downloadBytes(
      await encodeShare(props.document, props.indices, props.kind, "exact"),
      `${fileStem(props.name)}-exact.gridironshare`
    );
  } catch (cause) {
    error.value = message(cause);
  }
}
</script>
<template>
  <DialogFrame :title="kind === 'play' ? 'Share play' : 'Share playbook'" @close="emit('close')">
    <fieldset class="precision-options">
      <legend>Precision</legend>
      <label><input v-model="precision" type="radio" value="exact" />Exact</label>
      <label><input v-model="precision" type="radio" value="1mm" />1 mm</label>
      <label><input v-model="precision" type="radio" value="1cm" />1 cm</label>
    </fieldset>
    <textarea
      class="share-link"
      aria-label="Share link"
      :value="link"
      readonly
      rows="3"
      @focus="($event.target as HTMLTextAreaElement).select()"
    />
    <div class="share-size">
      <output data-testid="share-length" :class="{ warning: level === 'standard', danger: level === 'nitro' }">{{
        busy ? "Encoding…" : `${link.length.toLocaleString()} characters`
      }}</output
      ><span role="status">{{ status }}</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <footer class="dialog-actions">
      <button :disabled="!data || busy" @click="download">Download share file</button
      ><button v-if="precision !== 'exact'" :disabled="busy" @click="exact">Download exact file</button
      ><button class="primary" :disabled="!link || busy" @click="copy()">Copy link</button>
    </footer>
    <DialogFrame
      v-if="warning"
      :title="level === 'nitro' ? 'Exceeds Discord Nitro limit' : 'Exceeds Discord message limit'"
      @close="warning = false"
    >
      <p :class="level === 'nitro' ? 'danger' : 'warning'" role="alert">{{ warningText }}</p>
      <footer class="dialog-actions">
        <button
          @click="
            download();
            warning = false;
          "
        >
          Download share file</button
        ><button @click="warning = false">Cancel</button
        ><button :class="level === 'nitro' ? 'danger-button' : 'primary'" @click="copy(true)">Copy anyway</button>
      </footer>
    </DialogFrame>
  </DialogFrame>
</template>
