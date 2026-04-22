import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/api/client";
import type { ScopeEntry, ScopeKind } from "@/api/types";

export const useScopesStore = defineStore("scopes", () => {
  const items = ref<ScopeEntry[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const loaded = ref(false);

  const byKind = computed<Record<ScopeKind, ScopeEntry[]>>(() => {
    const buckets: Record<ScopeKind, ScopeEntry[]> = {
      user: [],
      agent: [],
      run: [],
    };
    for (const item of items.value) {
      if (buckets[item.kind]) buckets[item.kind].push(item);
    }
    for (const kind of Object.keys(buckets) as ScopeKind[]) {
      buckets[kind].sort((a, b) => (b.count ?? 0) - (a.count ?? 0));
    }
    return buckets;
  });

  async function reload() {
    loading.value = true;
    error.value = null;
    try {
      const payload = await api.scopes();
      items.value = payload.items ?? [];
      loaded.value = true;
    } catch (exc) {
      error.value = (exc as Error).message;
    } finally {
      loading.value = false;
    }
  }

  async function ensureLoaded() {
    if (!loaded.value && !loading.value) await reload();
  }

  return { items, loading, error, loaded, byKind, reload, ensureLoaded };
});
