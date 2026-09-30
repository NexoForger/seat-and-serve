<script setup lang="ts">
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  till: 'M4 8h16v12H4z M7 4h10v4 M8 12h8 M8 16h3 M15 16h1',
  kitchen: 'M7 14a5 5 0 0 1-2-9 5 5 0 0 1 8-2 5 5 0 0 1 6 8l-2 3v6H7z M7 16h10',
  search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  bag: 'M5 7h14l1 14H4z M8 8V6a4 4 0 0 1 8 0v2',
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  list: 'M8 6h13 M8 12h13 M8 18h13 M3 6h1 M3 12h1 M3 18h1',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  plus: 'M12 5v14 M5 12h14',
  clock: 'M12 7v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  check: 'M5 12l4 4L19 6',
  info: 'M12 11v5 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  warning: 'M12 9v4 M12 17h.01 M10.3 3.9 1.8 18.2A2 2 0 0 0 3.5 21h17a2 2 0 0 0 1.7-2.8L13.7 3.9a2 2 0 0 0-3.4 0z',
  error: 'M18 6 6 18 M6 6l12 12',
  refresh: 'M20 8a9 9 0 1 0 1 8 M20 3v5h-5',
  leaf: 'M20 3C9 2 3 7 5 15s16 6 15-12z M5 21L16 9',
};
</script>
<template><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.grid" /></svg></template>
