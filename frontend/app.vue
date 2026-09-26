<template>
  <NuxtRouteAnnouncer />
  <!-- Injects <link rel="manifest"> and the theme-color meta. @vite-pwa/nuxt builds
       manifest.webmanifest and sw.js either way, but nothing links to them without this,
       so the browser never offers to install the app. -->
  <VitePwaManifest />
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
