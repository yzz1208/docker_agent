<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Docker Support Agent</p>
        <h1>Support Console</h1>
      </div>

      <nav class="topbar__nav" aria-label="Primary">
        <RouterLink to="/">Chat</RouterLink>
        <RouterLink to="/settings">Settings</RouterLink>
      </nav>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
