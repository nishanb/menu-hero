<script setup lang="ts">
const config = useRuntimeConfig()
const year = new Date().getFullYear()
</script>

<template>
  <div class="app mh-legacy">
    <a class="skip-link" href="#main">Skip to content</a>

    <header class="app-header">
      <div class="container app-header__inner">
        <NuxtLink to="/" class="brand">
          <span class="brand__mark">
            <img src="/brand-mark.png" alt="" width="14" height="17">
          </span>
          <span class="brand__name">{{ config.public.appName }}</span>
        </NuxtLink>
        <nav class="nav" aria-label="Main">
          <NuxtLink to="/" class="nav__link">Home</NuxtLink>
          <NuxtLink to="/agent" class="nav__link">Agent</NuxtLink>
        </nav>
      </div>
    </header>

    <main id="main" class="app-main container">
      <slot />
    </main>

    <footer class="app-footer">
      <div class="container app-footer__inner">
        <span>&copy; {{ year }} {{ config.public.appName }}</span>
        <span class="app-footer__stack">Nuxt 4 &rarr; FastAPI &rarr; agents</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.app {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: color-mix(in srgb, var(--color-surface) 88%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--mh-border);
}

.app-header__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  min-height: 3.5rem;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--color-text);
  text-decoration: none;
}

.brand__mark {
  display: inline-grid;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: var(--mh-radius-sm);
  background: #fff;
  box-shadow: var(--shadow-sm);
}

.brand__mark img {
  height: 1.05rem;
  width: auto;
}

.nav {
  display: flex;
  gap: var(--space-1);
}

.nav__link {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-pill);
  color: var(--color-text-muted);
  text-decoration: none;
  font-weight: 500;
  transition: background-color 120ms ease, color 120ms ease;
}

.nav__link:hover {
  color: var(--color-text);
  background: var(--color-surface-2);
}

.nav__link.router-link-exact-active {
  color: var(--mh-accent);
  background: color-mix(in srgb, var(--mh-accent) 12%, transparent);
}

.app-main {
  flex: 1;
  padding-block: var(--space-6) var(--space-7);
}

.app-footer {
  border-top: 1px solid var(--mh-border);
  padding-block: var(--space-4);
  font-size: 0.85rem;
  color: var(--color-text-muted);
}

.app-footer__inner {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2);
}

.app-footer__stack {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
</style>
