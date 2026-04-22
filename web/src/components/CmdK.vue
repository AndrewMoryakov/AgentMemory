<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRecordsStore } from "@/stores/records";
import { useScopeStore } from "@/stores/scope";

const emit = defineEmits<{
  (e: "close"): void;
}>();

const records = useRecordsStore();
const scope = useScopeStore();

const term = ref("");
const inputRef = ref<HTMLInputElement | null>(null);
const activeIndex = ref(0);

interface CmdItem {
  kind: "record" | "scope" | "command";
  label: string;
  hint?: string;
  action: () => void;
}

function norm(text: string) {
  return text.toLowerCase();
}

function matches(haystack: string, needle: string): boolean {
  if (!needle) return true;
  const h = norm(haystack);
  let i = 0;
  for (const ch of norm(needle)) {
    const found = h.indexOf(ch, i);
    if (found === -1) return false;
    i = found + 1;
  }
  return true;
}

const results = computed<CmdItem[]>(() => {
  const q = term.value.trim();

  if (q.startsWith("scope:")) {
    const raw = q.slice("scope:".length).trim();
    const [field, ...rest] = raw.split("=");
    const value = rest.join("=").trim();
    const f = field.trim() as "user" | "agent" | "run";
    if (!value) return [];
    const key =
      f === "user" ? "user_id" : f === "agent" ? "agent_id" : f === "run" ? "run_id" : null;
    if (!key) return [];
    return [
      {
        kind: "scope" as const,
        label: `scope: ${key} = ${value}`,
        hint: "set exclusive scope",
        action: () => {
          scope.setExclusive(key, value);
          emit("close");
        },
      },
    ];
  }

  const recordItems: CmdItem[] = records.items
    .filter((item) =>
      matches(`${item.display_text ?? ""} ${item.id} ${item.user_id ?? ""} ${item.agent_id ?? ""}`, q),
    )
    .slice(0, 12)
    .map((item) => ({
      kind: "record" as const,
      label: item.display_text ?? item.id,
      hint: item.user_id || item.agent_id || item.run_id || item.id.slice(0, 8),
      action: () => {
        records.select(item.id);
        emit("close");
      },
    }));

  const commandItems: CmdItem[] = [
    {
      kind: "command" as const,
      label: "Reload records",
      hint: "refetch",
      action: () => {
        records.reload();
        emit("close");
      },
    },
    {
      kind: "command" as const,
      label: "Clear scope",
      hint: "show all scopes",
      action: () => {
        scope.clear();
        emit("close");
      },
    },
  ].filter((item) => matches(item.label, q));

  return [...recordItems, ...commandItems];
});

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") {
    emit("close");
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    activeIndex.value = Math.min(activeIndex.value + 1, results.value.length - 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    activeIndex.value = Math.max(activeIndex.value - 1, 0);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const item = results.value[activeIndex.value];
    if (item) item.action();
  }
}

onMounted(() => {
  nextTick(() => inputRef.value?.focus());
});
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm pt-[15vh]"
    @click.self="emit('close')"
  >
    <Transition name="panel" appear>
      <div
        class="w-[560px] max-w-[92vw] overflow-hidden rounded-lg border border-line-strong bg-bg-raised shadow-2xl"
        @keydown="onKey"
      >
      <input
        ref="inputRef"
        v-model="term"
        placeholder="Search records, or: scope:user=demo-u"
        class="w-full border-b border-line bg-transparent px-4 py-3 text-[14px] text-ink outline-none"
        @input="activeIndex = 0"
      />
      <ul class="max-h-[50vh] overflow-auto py-1">
        <li
          v-for="(item, index) in results"
          :key="item.kind + index + item.label"
          class="flex cursor-pointer items-center justify-between px-4 py-2 text-[13px]"
          :class="
            index === activeIndex
              ? 'bg-accent-500 text-accent-contrast'
              : 'text-ink hover:bg-surface-hover'
          "
          @mouseenter="activeIndex = index"
          @click="item.action()"
        >
          <span class="truncate">{{ item.label }}</span>
          <span
            class="ml-3 shrink-0 font-mono text-[11px]"
            :class="index === activeIndex ? 'opacity-80' : 'text-ink-faint'"
          >
            {{ item.hint ?? item.kind }}
          </span>
        </li>
        <li
          v-if="!results.length"
          class="px-4 py-6 text-center text-[12px] text-ink-faint"
        >
          No matches
        </li>
      </ul>
    </div>
    </Transition>
  </div>
</template>
