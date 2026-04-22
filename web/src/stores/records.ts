import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, ApiError } from "@/api/client";
import type { MemoryRecord } from "@/api/types";
import { useScopeStore } from "./scope";

export const useRecordsStore = defineStore("records", () => {
  const scope = useScopeStore();

  const items = ref<MemoryRecord[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const warning = ref<string | null>(null);
  const query = ref("");
  const pinnedOnly = ref(false);
  const selectedId = ref<string | null>(null);
  const checked = ref<Set<string>>(new Set());
  const lastCheckedId = ref<string | null>(null);

  const selected = computed<MemoryRecord | null>(() => {
    if (!selectedId.value) return null;
    return items.value.find((item) => item.id === selectedId.value) ?? null;
  });

  const checkedItems = computed<MemoryRecord[]>(() =>
    items.value.filter((item) => checked.value.has(item.id)),
  );
  const checkedCount = computed(() => checked.value.size);
  const allChecked = computed(
    () =>
      items.value.length > 0 &&
      items.value.every((item) => checked.value.has(item.id)),
  );
  const someChecked = computed(
    () => checked.value.size > 0 && !allChecked.value,
  );

  async function reload() {
    loading.value = true;
    error.value = null;
    warning.value = null;
    try {
      const payload = await api.listMemories({
        query: query.value.trim() || undefined,
        ...scope.asObject,
        pinned: pinnedOnly.value || undefined,
      });
      items.value = payload.items ?? [];
      warning.value = payload.warning ?? null;
      if (
        selectedId.value &&
        !items.value.some((item) => item.id === selectedId.value)
      ) {
        selectedId.value = items.value[0]?.id ?? null;
      }
      if (checked.value.size) {
        const present = new Set(items.value.map((item) => item.id));
        const next = new Set<string>();
        for (const id of checked.value) {
          if (present.has(id)) next.add(id);
        }
        checked.value = next;
      }
    } catch (exc) {
      items.value = [];
      error.value =
        exc instanceof ApiError ? exc.message : (exc as Error).message;
    } finally {
      loading.value = false;
    }
  }

  function select(id: string | null) {
    selectedId.value = id;
  }

  function moveSelection(delta: number) {
    if (!items.value.length) return;
    const currentIndex = items.value.findIndex(
      (item) => item.id === selectedId.value,
    );
    if (currentIndex === -1) {
      selectedId.value = items.value[0].id;
      return;
    }
    const nextIndex = Math.min(
      items.value.length - 1,
      Math.max(0, currentIndex + delta),
    );
    selectedId.value = items.value[nextIndex].id;
  }

  function selectFirst() {
    selectedId.value = items.value[0]?.id ?? null;
  }

  function selectLast() {
    selectedId.value = items.value[items.value.length - 1]?.id ?? null;
  }

  function isChecked(id: string): boolean {
    return checked.value.has(id);
  }

  function toggleCheck(id: string) {
    const next = new Set(checked.value);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    checked.value = next;
    lastCheckedId.value = id;
  }

  function setChecked(id: string, value: boolean) {
    const next = new Set(checked.value);
    if (value) next.add(id);
    else next.delete(id);
    checked.value = next;
    lastCheckedId.value = id;
  }

  function checkRange(toId: string) {
    if (!lastCheckedId.value) {
      toggleCheck(toId);
      return;
    }
    const fromIndex = items.value.findIndex(
      (item) => item.id === lastCheckedId.value,
    );
    const toIndex = items.value.findIndex((item) => item.id === toId);
    if (fromIndex === -1 || toIndex === -1) {
      toggleCheck(toId);
      return;
    }
    const [start, end] =
      fromIndex < toIndex ? [fromIndex, toIndex] : [toIndex, fromIndex];
    const next = new Set(checked.value);
    for (let i = start; i <= end; i++) {
      next.add(items.value[i].id);
    }
    checked.value = next;
    lastCheckedId.value = toId;
  }

  function checkAll() {
    checked.value = new Set(items.value.map((item) => item.id));
  }

  function clearChecks() {
    checked.value = new Set();
    lastCheckedId.value = null;
  }

  function toggleCheckAll() {
    if (allChecked.value) clearChecks();
    else checkAll();
  }

  function invertChecks() {
    const next = new Set<string>();
    for (const item of items.value) {
      if (!checked.value.has(item.id)) next.add(item.id);
    }
    checked.value = next;
    lastCheckedId.value = null;
  }

  return {
    items,
    loading,
    error,
    warning,
    query,
    pinnedOnly,
    selectedId,
    selected,
    checked,
    checkedItems,
    checkedCount,
    allChecked,
    someChecked,
    reload,
    select,
    moveSelection,
    selectFirst,
    selectLast,
    isChecked,
    toggleCheck,
    setChecked,
    checkRange,
    checkAll,
    clearChecks,
    toggleCheckAll,
    invertChecks,
  };
});
