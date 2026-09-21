<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <section class="not-found panel">
    <p class="section-label">404</p>
    <h2>Page not found</h2>
    <p>
      This route is not part of the Docker Support Agent product shell.
    </p>
    <RouterLink class="button button--primary" to="/">
      Return to chat
    </RouterLink>
  </section>
</template>
