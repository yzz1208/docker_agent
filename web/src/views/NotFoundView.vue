<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <section class="not-found panel">
    <p class="section-label">404</p>
    <h2>页面不存在</h2>
    <p>
      这个地址不属于当前支持平台，可能是链接已失效或页面已经移动。
    </p>
    <RouterLink class="button button--primary" to="/">
      返回聊天
    </RouterLink>
  </section>
</template>
