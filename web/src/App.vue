<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { RouterLink, RouterView } from "vue-router";

import AppErrorBoundary from "./components/AppErrorBoundary.vue";
import { useBackendHealth } from "./composables/useBackendHealth";

const backend = useBackendHealth();

onMounted(() => {
  backend.start();
});

onBeforeUnmount(() => {
  backend.stop();
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Docker Support Agent</p>
        <h1>Support Console</h1>
      </div>

      <div class="topbar__actions">
        <button
          class="backend-status"
          :data-state="backend.state.value"
          type="button"
          :title="backend.detail.value"
          @click="backend.check"
        >
          <span class="backend-status__dot" />
          <span>{{ backend.label.value }}</span>
        </button>

        <nav class="topbar__nav" aria-label="Primary">
          <RouterLink to="/">Chat</RouterLink>
          <RouterLink to="/settings">Settings</RouterLink>
        </nav>
      </div>
    </header>

    <main class="app-main">
      <RouterView v-slot="{ Component, route }">
        <AppErrorBoundary :reset-key="route.fullPath">
          <component :is="Component" />
        </AppErrorBoundary>
      </RouterView>
    </main>
  </div>
</template>
