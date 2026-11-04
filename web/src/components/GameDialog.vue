<script setup lang="ts">
import { ref } from "vue";
import type { PreparedGameChange, GameChangeResult } from "../gameFiles";
import { message } from "../files";
import DialogFrame from "./DialogFrame.vue";
const props = defineProps<{ change: PreparedGameChange; restoring: boolean }>();
const emit = defineEmits<{ close: []; done: [result: GameChangeResult]; applying: [value: boolean] }>();
const closed = ref(false);
const busy = ref(false);
const error = ref("");
async function apply(): Promise<void> {
  if (!closed.value || busy.value) return;
  busy.value = true;
  error.value = "";
  emit("applying", true);
  try {
    emit("done", await props.change.apply());
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
    emit("applying", false);
  }
}
</script>
<template>
  <DialogFrame
    :title="restoring ? 'Restore previous playbook' : 'Use in game'"
    :dismissible="!busy"
    @close="!busy && emit('close')"
  >
    <dl class="game-details">
      <dt>Game save</dt>
      <dd>{{ change.targetName }}</dd>
      <template v-if="change.restoreBackupName"
        ><dt>Restore from</dt>
        <dd>
          {{ change.restoreBackupName
          }}<time v-if="change.restoreCreatedAt">{{ new Date(change.restoreCreatedAt).toLocaleString() }}</time>
        </dd></template
      >
    </dl>
    <p>
      {{
        change.changed
          ? "The current game save will be backed up and verified before replacement."
          : "The game already has this playbook."
      }}
    </p>
    <label class="check-label"><input v-model="closed" type="checkbox" :disabled="busy" />Gridiron is closed</label>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <footer class="dialog-actions">
      <button :disabled="busy" @click="emit('close')">Cancel</button
      ><button class="primary" :disabled="!closed || busy" @click="apply">
        {{ busy ? "Applying…" : restoring ? "Restore playbook" : "Use in game" }}
      </button>
    </footer>
  </DialogFrame>
</template>
