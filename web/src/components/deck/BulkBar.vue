<script setup lang="ts">
import { ref } from "vue";
import { api } from "@/api/client";
import { useRecordsStore } from "@/stores/records";

const records = useRecordsStore();

const busy = ref<string | null>(null); // current bulk operation, for spinner
const progress = ref({ done: 0, total: 0 });

async function runBulk(
  label: string,
  action: (id: string) => Promise<unknown>,
) {
  const ids = records.checkedItems.map((item) => item.id);
  if (!ids.length) return;
  busy.value = label;
  progress.value = { done: 0, total: ids.length };
  try {
    for (const id of ids) {
      await action(id);
      progress.value.done += 1;
    }
    await records.reload();
  } finally {
    busy.value = null;
    progress.value = { done: 0, total: 0 };
  }
}

function pinAll() {
  return runBulk("pin", (id) => api.pinMemory(id, true));
}
function unpinAll() {
  return runBulk("unpin", (id) => api.pinMemory(id, false));
}
function deleteAll() {
  const n = records.checkedCount;
  if (!confirm(`Delete ${n} record${n === 1 ? "" : "s"}? This cannot be undone.`)) return;
  return runBulk("delete", (id) => api.deleteMemory(id));
}

function invertSelection() {
  records.invertChecks();
}
</script>

<template>
  <Transition name="bulk">
    <div
      v-if="records.checkedCount > 0"
      class="flex items-center gap-2 border-b border-line bg-accent-500/10 px-3 py-1.5 text-[12px]"
    >
    <span class="font-mono text-ink-strong">
      {{ records.checkedCount }} selected
    </span>

    <span class="text-ink-faint">·</span>

    <button
      class="rounded-sm px-2 py-0.5 text-ink-muted hover:bg-surface-hover hover:text-ink"
      @click="records.checkAll()"
    >
      Select all ({{ records.items.length }})
    </button>
    <button
      class="rounded-sm px-2 py-0.5 text-ink-muted hover:bg-surface-hover hover:text-ink"
      @click="invertSelection"
    >
      Invert
    </button>
    <button
      class="rounded-sm px-2 py-0.5 text-ink-muted hover:bg-surface-hover hover:text-ink"
      @click="records.clearChecks()"
    >
      Clear
      <span class="ml-1 font-mono text-[10px] text-ink-faint">esc</span>
    </button>

    <div class="ml-auto flex items-center gap-2">
      <span v-if="busy" class="font-mono text-[11px] text-ink-muted">
        {{ busy }} {{ progress.done }}/{{ progress.total }}
      </span>

      <button
        class="rounded-sm border border-line-strong bg-surface px-2 py-0.5 text-ink hover:bg-surface-hover disabled:opacity-40"
        :disabled="!!busy"
        @click="pinAll"
      >
        Pin
      </button>
      <button
        class="rounded-sm border border-line-strong bg-surface px-2 py-0.5 text-ink hover:bg-surface-hover disabled:opacity-40"
        :disabled="!!busy"
        @click="unpinAll"
      >
        Unpin
      </button>
      <button
        class="rounded-sm border border-danger/40 bg-danger/10 px-2 py-0.5 text-danger hover:bg-danger/20 disabled:opacity-40"
        :disabled="!!busy"
        @click="deleteAll"
      >
        Delete
      </button>
    </div>
    </div>
  </Transition>
</template>
