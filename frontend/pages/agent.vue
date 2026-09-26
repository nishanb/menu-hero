<script setup lang="ts">
definePageMeta({ layout: 'default' })

useHead({ title: 'AI Agent' })
useSeoMeta({ description: 'Chat with the Menu Hero AI agents.' })
</script>

<template>
  <section class="agent-page">
    <AgentChat />
  </section>
</template>

<style scoped>
.agent-page {
  display: grid;
  justify-items: center;
}
</style>
