import { ref, watch } from "vue";

const STORAGE_KEY = "agentmemory.theme";

type Theme = string;

const current = ref<Theme>(
  (typeof localStorage !== "undefined" && localStorage.getItem(STORAGE_KEY)) ||
    "violet",
);

if (typeof document !== "undefined") {
  document.documentElement.setAttribute("data-theme", current.value);
}

watch(current, (value) => {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", value);
  }
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(STORAGE_KEY, value);
  }
});

export function useTheme() {
  return {
    theme: current,
    setTheme(next: Theme) {
      current.value = next;
    },
  };
}
