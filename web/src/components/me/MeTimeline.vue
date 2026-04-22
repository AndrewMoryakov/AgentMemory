<script setup lang="ts">
import { computed } from "vue";
import type { MemoryRecord } from "@/api/types";

const props = defineProps<{ items: MemoryRecord[] }>();
const emit = defineEmits<{ (e: "forget", id: string): void }>();

interface Group {
  key: string;
  label: string;
  items: MemoryRecord[];
}

function bucketLabel(iso: string | undefined): { key: string; label: string } {
  if (!iso) return { key: "older", label: "Older" };
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return { key: "older", label: "Older" };
  const today = new Date();
  const diffDays = Math.floor(
    (today.getTime() - date.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (diffDays <= 0) return { key: "today", label: "Today" };
  if (diffDays === 1) return { key: "yesterday", label: "Yesterday" };
  if (diffDays < 7) return { key: "week", label: "Last week" };
  if (diffDays < 30) return { key: "month", label: "Last month" };
  return { key: "older", label: "Older" };
}

const ORDER = ["today", "yesterday", "week", "month", "older"];

const groups = computed<Group[]>(() => {
  const map = new Map<string, Group>();
  for (const item of props.items) {
    const ts = item.updated_at ?? item.created_at;
    const { key, label } = bucketLabel(ts);
    if (!map.has(key)) {
      map.set(key, { key, label, items: [] });
    }
    map.get(key)!.items.push(item);
  }
  return ORDER.filter((k) => map.has(k)).map((k) => map.get(k)!);
});

function tags(record: MemoryRecord): string[] {
  const meta = record.metadata as Record<string, unknown> | null | undefined;
  if (!meta) return [];
  const raw = meta.tags;
  if (Array.isArray(raw)) return raw.filter((t) => typeof t === "string") as string[];
  if (typeof meta.category === "string") return [meta.category];
  return [];
}

function relativeTime(iso: string | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <section v-for="group in groups" :key="group.key">
      <h2
        class="mb-3 text-[11px] uppercase tracking-wider text-ink-faint"
      >
        {{ group.label }}
      </h2>
      <ul class="flex flex-col gap-2">
        <li
          v-for="item in group.items"
          :key="item.id"
          class="rounded-md border border-line bg-surface p-4"
        >
          <p class="text-ink">
            {{ item.display_text || item.memory || "(empty)" }}
          </p>
          <div class="mt-3 flex items-center gap-3 text-[11px] text-ink-muted">
            <span
              v-for="tag in tags(item)"
              :key="tag"
              class="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-ink-faint"
            >
              #{{ tag }}
            </span>
            <span class="font-mono">{{ relativeTime(item.updated_at ?? item.created_at) }}</span>
            <button
              class="ml-auto text-[11px] text-danger hover:underline"
              @click="emit('forget', item.id)"
            >
              forget
            </button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
