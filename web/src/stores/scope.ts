import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { Scope } from "@/api/types";

export const useScopeStore = defineStore("scope", () => {
  const user_id = ref("");
  const agent_id = ref("");
  const run_id = ref("");

  const asObject = computed<Scope>(() => ({
    user_id: user_id.value || undefined,
    agent_id: agent_id.value || undefined,
    run_id: run_id.value || undefined,
  }));

  const isEmpty = computed(
    () => !user_id.value && !agent_id.value && !run_id.value,
  );

  const summary = computed(() => {
    if (user_id.value) return `user:${user_id.value}`;
    if (agent_id.value) return `agent:${agent_id.value}`;
    if (run_id.value) return `run:${run_id.value}`;
    return "no scope";
  });

  function setExclusive(field: keyof Scope, value: string) {
    user_id.value = field === "user_id" ? value : "";
    agent_id.value = field === "agent_id" ? value : "";
    run_id.value = field === "run_id" ? value : "";
  }

  function clear() {
    user_id.value = "";
    agent_id.value = "";
    run_id.value = "";
  }

  return {
    user_id,
    agent_id,
    run_id,
    asObject,
    isEmpty,
    summary,
    setExclusive,
    clear,
  };
});
