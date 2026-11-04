<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
withDefaults(defineProps<{ title: string; wide?: boolean; dismissible?: boolean }>(), { dismissible: true });
const emit = defineEmits<{ close: [] }>();
const element = ref<HTMLDialogElement>();
onMounted(() => element.value?.showModal());
onBeforeUnmount(() => element.value?.close());
</script>
<template>
  <dialog ref="element" :class="{ wide }" :aria-label="title" @cancel.prevent="dismissible && emit('close')">
    <header class="dialog-heading">
      <h2>{{ title }}</h2>
      <button
        class="icon-button"
        aria-label="Close dialog"
        title="Close"
        :disabled="!dismissible"
        @click="emit('close')"
      >
        ×
      </button>
    </header>
    <slot />
  </dialog>
</template>
