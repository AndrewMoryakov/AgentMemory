import { defineStore } from "pinia";
import { ref, watch } from "vue";

export type DeckView = "table" | "timeline";

const STORAGE_KEY = "agentmemory.ui.deckView";

function loadDeckView(): DeckView {
  if (typeof localStorage === "undefined") return "table";
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw === "timeline" ? "timeline" : "table";
}

export const useUiStore = defineStore("ui", () => {
  const palette = ref(false);
  const deckView = ref<DeckView>(loadDeckView());
  const inspectorOpen = ref(true);

  watch(deckView, (value) => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(STORAGE_KEY, value);
    }
  });

  function openPalette() {
    palette.value = true;
  }
  function closePalette() {
    palette.value = false;
  }
  function togglePalette() {
    palette.value = !palette.value;
  }
  function setDeckView(value: DeckView) {
    deckView.value = value;
  }
  function toggleDeckView() {
    deckView.value = deckView.value === "table" ? "timeline" : "table";
  }

  return {
    palette,
    deckView,
    inspectorOpen,
    openPalette,
    closePalette,
    togglePalette,
    setDeckView,
    toggleDeckView,
  };
});
