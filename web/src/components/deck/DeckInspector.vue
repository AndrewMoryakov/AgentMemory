<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "@/api/client";
import { useRecordsStore } from "@/stores/records";

const records = useRecordsStore();

const memory = ref("");
const metadataText = ref("");
const pinned = ref(false);
const dirty = ref(false);
const saving = ref(false);
const saveError = ref<string | null>(null);

const selected = computed(() => records.selected);

watch(
  selected,
  (item) => {
    if (!item) {
      memory.value = "";
      metadataText.value = "";
      pinned.value = false;
      dirty.value = false;
      return;
    }
    memory.value = item.display_text ?? item.memory ?? "";
    metadataText.value = JSON.stringify(item.metadata ?? {}, null, 2);
    pinned.value = Boolean(item.pinned);
    dirty.value = false;
    saveError.value = null;
  },
  { immediate: true },
);

function markDirty() {
  dirty.value = true;
}

async function save() {
  if (!selected.value) return;
  saving.value = true;
  saveError.value = null;
  try {
    let metadata: Record<string, unknown> = {};
    if (metadataText.value.trim()) {
      metadata = JSON.parse(metadataText.value);
    }
    await api.updateMemory(selected.value.id, {
      memory: memory.value,
      metadata,
      pinned: pinned.value,
    });
    await records.reload();
    dirty.value = false;
  } catch (exc) {
    saveError.value = (exc as Error).message;
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selected.value) return;
  if (!confirm("Delete this record?")) return;
  await api.deleteMemory(selected.value.id);
  records.select(null);
  await records.reload();
}
</script>

<template>
  <aside class="flex flex-col border-l border-line bg-surface-sunken">
    <header
      class="flex h-9 items-center justify-between border-b border-line px-3 font-mono text-[11px] uppercase tracking-wider text-ink-faint"
    >
      <span>Inspector</span>
      <span v-if="selected" class="normal-case text-ink-muted">
        {{ selected.id }}
      </span>
    </header>

    <div
      v-if="!selected"
      class="flex flex-1 items-center justify-center text-ink-faint"
    >
      Select a record to inspect.
    </div>

    <div v-else class="flex flex-1 flex-col gap-3 overflow-auto p-3">
      <label class="flex flex-col gap-1">
        <span class="text-[11px] uppercase tracking-wider text-ink-faint">
          Memory
        </span>
        <textarea
          v-model="memory"
          rows="6"
          class="resize-y rounded-md border border-line bg-surface px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
          @input="markDirty"
        />
      </label>

      <label class="flex flex-col gap-1">
        <span class="text-[11px] uppercase tracking-wider text-ink-faint">
          Metadata (JSON)
        </span>
        <textarea
          v-model="metadataText"
          rows="8"
          class="resize-y rounded-md border border-line bg-surface px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
          @input="markDirty"
        />
      </label>

      <label class="flex items-center gap-2 text-[12px]">
        <input
          type="checkbox"
          v-model="pinned"
          class="accent-accent-500"
          @change="markDirty"
        />
        <span>Pinned</span>
      </label>

      <div
        v-if="saveError"
        class="rounded-md border border-danger/40 bg-danger/10 px-2 py-1.5 text-[12px] text-danger"
      >
        {{ saveError }}
      </div>

      <div class="mt-auto flex gap-2 pt-2">
        <button
          class="flex-1 rounded-md bg-accent-500 px-3 py-1.5 text-[12px] font-medium text-accent-contrast hover:bg-accent-600 disabled:opacity-40"
          :disabled="!dirty || saving"
          @click="save"
        >
          {{ saving ? "Saving…" : dirty ? "Save" : "Saved" }}
        </button>
        <button
          class="rounded-md border border-line-strong bg-surface px-3 py-1.5 text-[12px] text-danger hover:bg-danger/10"
          @click="remove"
        >
          Delete
        </button>
      </div>
    </div>
  </aside>
</template>
