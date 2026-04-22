<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { useUiStore } from "@/stores/ui";
import CmdK from "@/components/CmdK.vue";

const ui = useUiStore();

function onKeydown(event: KeyboardEvent) {
  const isCmdK =
    (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
  if (isCmdK) {
    event.preventDefault();
    ui.togglePalette();
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <router-view />
  <Transition name="overlay">
    <CmdK v-if="ui.palette" @close="ui.closePalette()" />
  </Transition>
</template>
