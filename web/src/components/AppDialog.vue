<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    busy?: boolean;
  }>(),
  {
    description: "",
    confirmLabel: "Confirm",
    cancelLabel: "Cancel",
    danger: false,
    busy: false,
  },
);

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

function handleKeydown(event: KeyboardEvent): void {
  if (!props.open || props.busy) {
    return;
  }
  if (event.key === "Escape") {
    emit("close");
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="dialog-backdrop"
      role="presentation"
      @mousedown.self="!busy && emit('close')"
    >
      <section
        class="dialog-card"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
      >
        <div class="dialog-card__header">
          <div>
            <p class="section-label">Conversation action</p>
            <h2>{{ title }}</h2>
          </div>
          <button
            class="dialog-close"
            type="button"
            aria-label="Close dialog"
            :disabled="busy"
            @click="emit('close')"
          >
            ×
          </button>
        </div>

        <div class="dialog-card__body">
          <p v-if="description" class="dialog-description">
            {{ description }}
          </p>
          <slot />
        </div>

        <div class="dialog-card__footer">
          <button
            class="button button--ghost"
            type="button"
            :disabled="busy"
            @click="emit('close')"
          >
            {{ cancelLabel }}
          </button>
          <button
            class="button"
            :class="danger ? 'button--danger-solid' : 'button--primary'"
            type="button"
            :disabled="busy"
            @click="emit('confirm')"
          >
            {{ busy ? "Working…" : confirmLabel }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
