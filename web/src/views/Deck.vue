<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "@/api/client";
import { useRecordsStore } from "@/stores/records";
import { useScopeStore } from "@/stores/scope";
import { useScopesStore } from "@/stores/scopes";
import { useUiStore } from "@/stores/ui";
import DeckRail from "@/components/deck/DeckRail.vue";
import DeckTable from "@/components/deck/DeckTable.vue";
import DeckTimeline from "@/components/deck/DeckTimeline.vue";
import DeckInspector from "@/components/deck/DeckInspector.vue";
import AddRecordDialog from "@/components/deck/AddRecordDialog.vue";
import BulkBar from "@/components/deck/BulkBar.vue";
import StatusStrip from "@/components/StatusStrip.vue";
import { ref } from "vue";

const records = useRecordsStore();
const scope = useScopeStore();
const scopesStore = useScopesStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

const addOpen = ref(false);

function readUrl() {
  const q = route.query;
  scope.user_id = typeof q.user === "string" ? q.user : "";
  scope.agent_id = typeof q.agent === "string" ? q.agent : "";
  scope.run_id = typeof q.run === "string" ? q.run : "";
  records.query = typeof q.q === "string" ? q.q : "";
  records.pinnedOnly = q.pinned === "true";
}

function writeUrl() {
  const query: Record<string, string> = {};
  if (scope.user_id) query.user = scope.user_id;
  if (scope.agent_id) query.agent = scope.agent_id;
  if (scope.run_id) query.run = scope.run_id;
  if (records.query) query.q = records.query;
  if (records.pinnedOnly) query.pinned = "true";
  router.replace({ query });
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

async function deleteSelected() {
  const current = records.selected;
  if (!current) return;
  if (!confirm("Delete this record?")) return;
  await api.deleteMemory(current.id);
  records.select(null);
  await records.reload();
}

async function togglePinnedSelected() {
  const current = records.selected;
  if (!current) return;
  await api.pinMemory(current.id, !current.pinned);
  await records.reload();
}

function onKeydown(event: KeyboardEvent) {
  if (event.defaultPrevented) return;
  if (isEditableTarget(event.target)) return;
  if (ui.palette || addOpen.value) return;

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    records.checkAll();
    return;
  }

  if (event.metaKey || event.ctrlKey || event.altKey) return;

  if (event.key === "Escape") {
    if (records.checkedCount > 0) {
      event.preventDefault();
      records.clearChecks();
    }
    return;
  }

  if (event.key === " ") {
    if (!records.selected) return;
    event.preventDefault();
    records.toggleCheck(records.selected.id);
    return;
  }

  switch (event.key) {
    case "j":
    case "ArrowDown":
      event.preventDefault();
      records.moveSelection(1);
      break;
    case "k":
    case "ArrowUp":
      event.preventDefault();
      records.moveSelection(-1);
      break;
    case "g":
      event.preventDefault();
      records.selectFirst();
      break;
    case "G":
      event.preventDefault();
      records.selectLast();
      break;
    case "n":
      event.preventDefault();
      addOpen.value = true;
      break;
    case "p":
      event.preventDefault();
      togglePinnedSelected();
      break;
    case "x":
    case "Delete":
      event.preventDefault();
      deleteSelected();
      break;
    case "r":
      event.preventDefault();
      records.reload();
      scopesStore.reload();
      break;
    case "/":
      event.preventDefault();
      ui.openPalette();
      break;
    case "t":
      event.preventDefault();
      ui.toggleDeckView();
      break;
  }
}

async function onRecordCreated() {
  await Promise.all([records.reload(), scopesStore.reload()]);
}

onMounted(() => {
  readUrl();
  records.reload();
  window.addEventListener("keydown", onKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
});

watch(
  () => [
    scope.user_id,
    scope.agent_id,
    scope.run_id,
    records.pinnedOnly,
    records.query,
  ],
  () => {
    writeUrl();
    records.reload();
  },
);
</script>

<template>
  <div class="grid h-full grid-rows-[48px_1fr_28px]">
    <header
      class="flex items-center justify-between border-b border-line bg-bg-raised px-4"
    >
      <div class="flex items-center gap-3">
        <div
          class="h-4 w-4 rounded-xs"
          :style="{ background: 'var(--accent-500)' }"
        />
        <span class="font-mono text-[13px] text-ink-strong">AgentMemory</span>
        <span class="text-ink-faint">/</span>
        <span class="text-ink-muted">Deck</span>
      </div>

      <div class="flex items-center gap-2">
        <div class="flex rounded-sm border border-line-strong bg-surface p-0.5 text-[12px]">
          <button
            class="rounded-xs px-2 py-0.5 transition-colors"
            :class="
              ui.deckView === 'table'
                ? 'bg-surface-active text-ink-strong'
                : 'text-ink-muted hover:text-ink'
            "
            @click="ui.setDeckView('table')"
          >
            Table
          </button>
          <button
            class="rounded-xs px-2 py-0.5 transition-colors"
            :class="
              ui.deckView === 'timeline'
                ? 'bg-surface-active text-ink-strong'
                : 'text-ink-muted hover:text-ink'
            "
            @click="ui.setDeckView('timeline')"
          >
            Timeline
          </button>
        </div>
        <button
          class="rounded-sm border border-line-strong bg-surface px-2.5 py-1 text-[12px] text-ink hover:bg-surface-hover"
          @click="addOpen = true"
        >
          + New
          <span class="ml-1.5 font-mono text-[10px] text-ink-faint">n</span>
        </button>
        <button
          class="rounded-sm border border-line-strong bg-surface px-2 py-1 font-mono text-[12px] text-ink-muted hover:bg-surface-hover hover:text-ink"
          @click="ui.openPalette()"
        >
          <span>Search</span>
          <span class="ml-2 text-ink-faint">⌘K</span>
        </button>
        <button
          class="rounded-sm border border-line-strong bg-surface px-2 py-1 text-[12px] text-ink-muted hover:bg-surface-hover hover:text-ink"
          @click="ui.inspectorOpen = !ui.inspectorOpen"
        >
          {{ ui.inspectorOpen ? "Hide inspector" : "Show inspector" }}
        </button>
      </div>
    </header>

    <div
      class="grid min-h-0 overflow-hidden"
      :class="
        ui.inspectorOpen
          ? 'grid-cols-[240px_1fr_380px]'
          : 'grid-cols-[240px_1fr]'
      "
    >
      <DeckRail />
      <div class="flex min-w-0 flex-col overflow-hidden">
        <BulkBar />
        <div class="relative flex-1 overflow-hidden">
          <Transition name="view-fade" mode="out-in">
            <DeckTable
              v-if="ui.deckView === 'table'"
              class="absolute inset-0"
            />
            <DeckTimeline v-else class="absolute inset-0" />
          </Transition>
        </div>
      </div>
      <Transition name="inspector">
        <DeckInspector
          v-if="ui.inspectorOpen"
          class="min-w-0 overflow-hidden"
        />
      </Transition>
    </div>

    <StatusStrip />

    <Transition name="overlay">
      <AddRecordDialog
        v-if="addOpen"
        @close="addOpen = false"
        @created="onRecordCreated"
      />
    </Transition>
  </div>
</template>
