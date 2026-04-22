<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { useUiStore } from "@/stores/ui";
import CmdK from "@/components/CmdK.vue";
import HelpOverlay from "@/components/HelpOverlay.vue";

const ui = useUiStore();

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    ui.togglePalette();
    return;
  }

  if (event.key === "Escape") {
    if (ui.help) {
      event.preventDefault();
      ui.closeHelp();
      return;
    }
    if (ui.palette) {
      event.preventDefault();
      ui.closePalette();
      return;
    }
  }

  if (isEditableTarget(event.target)) return;
  if (event.key === "?" && !event.metaKey && !event.ctrlKey) {
    event.preventDefault();
    ui.toggleHelp();
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
  <Transition name="overlay">
    <HelpOverlay v-if="ui.help" @close="ui.closeHelp()" />
  </Transition>
</template>
