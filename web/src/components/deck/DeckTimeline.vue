<script setup lang="ts">
import { computed, nextTick, watch } from "vue";
import { useRecordsStore } from "@/stores/records";
import { api } from "@/api/client";
import type { MemoryRecord } from "@/api/types";

const records = useRecordsStore();

interface Bucket {
  key: string;
  label: string;
  items: MemoryRecord[];
}

const BUCKET_ORDER = ["today", "yesterday", "week", "month", "older", "undated"];

function bucketFor(iso: string | undefined): { key: string; label: string } {
  if (!iso) return { key: "undated", label: "No timestamp" };
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return { key: "undated", label: "No timestamp" };
  const diffDays = Math.floor(
    (Date.now() - date.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (diffDays <= 0) return { key: "today", label: "Today" };
  if (diffDays === 1) return { key: "yesterday", label: "Yesterday" };
  if (diffDays < 7) return { key: "week", label: "Last week" };
  if (diffDays < 30) return { key: "month", label: "Last month" };
  return { key: "older", label: "Older" };
}

const buckets = computed<Bucket[]>(() => {
  const map = new Map<string, Bucket>();
  for (const item of records.items) {
    const ts = item.updated_at ?? item.created_at;
    const { key, label } = bucketFor(ts);
    if (!map.has(key)) map.set(key, { key, label, items: [] });
    map.get(key)!.items.push(item);
  }
  for (const bucket of map.values()) {
    bucket.items.sort((a, b) => {
      const ta = new Date(a.updated_at ?? a.created_at ?? 0).getTime();
      const tb = new Date(b.updated_at ?? b.created_at ?? 0).getTime();
      return tb - ta;
    });
  }
  return BUCKET_ORDER.filter((k) => map.has(k)).map((k) => map.get(k)!);
});

function tags(record: MemoryRecord): string[] {
  const meta = record.metadata as Record<string, unknown> | null | undefined;
  if (!meta) return [];
  const raw = meta.tags;
  if (Array.isArray(raw)) return raw.filter((t): t is string => typeof t === "string");
  if (typeof meta.category === "string") return [meta.category];
  return [];
}

function rowScope(item: MemoryRecord): string {
  return item.user_id || item.agent_id || item.run_id || "";
}

function relativeTime(iso: string | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  return `${months}mo`;
}

async function togglePin(event: Event, item: MemoryRecord) {
  event.stopPropagation();
  await api.pinMemory(item.id, !item.pinned);
  await records.reload();
}

async function remove(event: Event, item: MemoryRecord) {
  event.stopPropagation();
  if (!confirm("Delete this record?")) return;
  await api.deleteMemory(item.id);
  await records.reload();
}

function onCheckboxClick(event: MouseEvent, id: string) {
  event.stopPropagation();
  if (event.shiftKey) {
    records.checkRange(id);
  } else {
    records.toggleCheck(id);
  }
}

watch(
  () => records.selectedId,
  async (id) => {
    if (!id) return;
    await nextTick();
    const node = document.querySelector(
      `[data-timeline-card="${CSS.escape(id)}"]`,
    );
    if (node instanceof HTMLElement) {
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  },
);
</script>

<template>
  <section class="flex flex-col bg-bg">
    <div
      v-if="records.loading && !records.items.length"
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
      v-else-if="!records.items.length"
      class="flex flex-col items-center justify-center gap-1 py-10 text-ink-faint"
    >
      <p>No records</p>
      <p v-if="records.warning" class="max-w-md text-center text-[12px]">
        {{ records.warning }}
      </p>
    </div>

    <div v-else class="flex-1 overflow-auto px-4 py-4">
      <section
        v-for="bucket in buckets"
        :key="bucket.key"
        class="mb-6 last:mb-0"
      >
        <div
          class="sticky top-0 z-10 mb-2 flex items-center gap-2 bg-bg/90 py-1 backdrop-blur"
        >
          <span class="text-[11px] uppercase tracking-wider text-ink-faint">
            {{ bucket.label }}
          </span>
          <span class="text-[11px] text-ink-faint">·</span>
          <span class="font-mono text-[11px] text-ink-faint">
            {{ bucket.items.length }}
          </span>
          <div class="ml-2 flex-1 border-t border-line-subtle" />
        </div>

        <ul class="flex flex-col gap-1.5">
          <li
            v-for="item in bucket.items"
            :key="item.id"
            :data-timeline-card="item.id"
            class="group cursor-pointer rounded-md border bg-surface px-3 py-2.5 transition-colors hover:bg-surface-hover"
            :class="
              records.selectedId === item.id
                ? 'border-accent-500 bg-accent-500/10'
                : records.isChecked(item.id)
                  ? 'border-accent-500/40 bg-accent-500/5'
                  : 'border-line'
            "
            @click="records.select(item.id)"
          >
            <div class="flex items-start gap-2.5">
              <input
                type="checkbox"
                class="mt-0.5 accent-accent-500 transition-opacity"
                :class="
                  records.checkedCount || records.isChecked(item.id)
                    ? 'opacity-100'
                    : 'opacity-40 group-hover:opacity-100'
                "
                :checked="records.isChecked(item.id)"
                @click="onCheckboxClick($event, item.id)"
              />
              <p class="flex-1 text-[13px] text-ink">
                {{ item.display_text || item.memory || "(empty)" }}
              </p>
            </div>

            <div class="mt-2 flex items-center gap-2 pl-[26px] text-[11px] text-ink-muted">
              <span
                v-if="rowScope(item)"
                class="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-ink-faint"
              >
                {{ rowScope(item) }}
              </span>
              <span
                v-for="tag in tags(item)"
                :key="tag"
                class="rounded-sm bg-surface-active px-1.5 py-0.5 font-mono text-ink-faint"
              >
                #{{ tag }}
              </span>
              <span class="font-mono text-ink-faint">
                {{ relativeTime(item.updated_at ?? item.created_at) }}
              </span>
              <span
                v-if="item.pinned"
                class="ml-auto font-mono text-accent-400"
                title="Pinned"
              >●</span>

              <div
                class="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100"
                :class="{ 'opacity-100': records.selectedId === item.id }"
              >
                <button
                  class="rounded-sm px-1.5 py-0.5 text-ink-faint hover:bg-surface-active hover:text-ink"
                  :title="item.pinned ? 'Unpin' : 'Pin'"
                  @click="togglePin($event, item)"
                >
                  {{ item.pinned ? 'unpin' : 'pin' }}
                </button>
                <button
                  class="rounded-sm px-1.5 py-0.5 text-ink-faint hover:bg-danger/15 hover:text-danger"
                  title="Delete"
                  @click="remove($event, item)"
                >
                  del
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>
