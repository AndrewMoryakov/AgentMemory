<script setup lang="ts">
import { computed } from "vue";
import { useRecordsStore } from "@/stores/records";
import type { MemoryRecord } from "@/api/types";

const records = useRecordsStore();

const rows = computed<MemoryRecord[]>(() => records.items);

function shortId(id: string) {
  if (!id) return "";
  return id.length > 10 ? id.slice(0, 8) + "…" : id;
}

function rowScope(item: MemoryRecord) {
  return item.user_id || item.agent_id || item.run_id || "";
}

function onCheckboxClick(event: MouseEvent, id: string) {
  event.stopPropagation();
  if (event.shiftKey) {
    records.checkRange(id);
  } else {
    records.toggleCheck(id);
  }
}
</script>

<template>
  <section class="flex flex-col bg-bg">
    <div
      class="flex h-9 items-center border-b border-line px-3 font-mono text-[11px] uppercase tracking-wider text-ink-faint"
    >
      <span class="flex w-6 items-center">
        <input
          type="checkbox"
          class="accent-accent-500"
          :checked="records.allChecked"
          :indeterminate.prop="records.someChecked"
          :disabled="!rows.length"
          @change="records.toggleCheckAll()"
          @click.stop
        />
      </span>
      <span class="w-20">id</span>
      <span class="w-32">scope</span>
      <span class="flex-1">text</span>
      <span class="w-20 text-right">updated</span>
      <span class="w-6"></span>
    </div>

    <div
      v-if="records.loading && !rows.length"
      class="flex items-center justify-center py-10 text-ink-faint"
    >
      Loading…
    </div>

    <div
      v-else-if="records.error"
      class="m-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger"
    >
      {{ records.error }}
    </div>

    <div
      v-else-if="!rows.length"
      class="flex flex-col items-center justify-center gap-1 py-10 text-ink-faint"
    >
      <p>No records</p>
      <p v-if="records.warning" class="max-w-md text-center text-[12px]">
        {{ records.warning }}
      </p>
    </div>

    <div v-else class="flex-1 overflow-auto">
      <div
        v-for="item in rows"
        :key="item.id"
        class="flex h-8 cursor-pointer items-center border-b border-line-subtle px-3 text-[12px] hover:bg-surface-hover"
        :class="{
          'bg-accent-500/15 text-ink-strong':
            records.selectedId === item.id,
          'bg-accent-500/5': records.isChecked(item.id) && records.selectedId !== item.id,
        }"
        @click="records.select(item.id)"
      >
        <span class="flex w-6 items-center">
          <input
            type="checkbox"
            class="accent-accent-500"
            :checked="records.isChecked(item.id)"
            @click="onCheckboxClick($event, item.id)"
          />
        </span>
        <span class="w-20 font-mono text-ink-faint">{{ shortId(item.id) }}</span>
        <span class="w-32 truncate font-mono text-ink-muted">{{ rowScope(item) }}</span>
        <span class="flex-1 truncate">{{ item.display_text || item.memory || "(empty)" }}</span>
        <span class="w-20 text-right font-mono text-[11px] text-ink-faint">
          {{ (item.updated_at || item.created_at || "").slice(0, 10) }}
        </span>
        <span class="w-6 text-center">
          <span v-if="item.pinned" class="text-accent-400">●</span>
        </span>
      </div>
    </div>
  </section>
</template>
