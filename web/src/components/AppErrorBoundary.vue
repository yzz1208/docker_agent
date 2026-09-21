<script setup lang="ts">
import { onErrorCaptured, ref, watch } from "vue";

const props = defineProps<{
  resetKey: string;
}>();

const error = ref<Error | null>(null);

onErrorCaptured((captured) => {
  error.value =
    captured instanceof Error
      ? captured
      : new Error(String(captured));
  return false;
});

watch(
  () => props.resetKey,
  () => {
    error.value = null;
  },
);

function retry(): void {
  error.value = null;
}

function reloadApp(): void {
  window.location.reload();
}
</script>

<template>
  <div v-if="error" class="route-error panel">
    <p class="section-label">Page error</p>
    <h2>This view could not be rendered.</h2>
    <p>{{ error.message }}</p>
    <div class="route-error__actions">
      <button class="button button--primary" type="button" @click="retry">
        Try again
      </button>
      <button
        class="button button--ghost"
        type="button"
        @click="reloadApp"
      >
        Reload app
      </button>
    </div>
  </div>

  <slot v-else />
</template>
