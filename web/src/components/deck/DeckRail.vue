<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "@/api/client";
import type { ClientIntegration, ScopeKind, StatsTotals } from "@/api/types";
import { useScopeStore } from "@/stores/scope";
import { useScopesStore } from "@/stores/scopes";
import { useRecordsStore } from "@/stores/records";
import { useOpsStore } from "@/stores/ops";
import Sparkline from "@/components/Sparkline.vue";

const scope = useScopeStore();
const scopes = useScopesStore();
const records = useRecordsStore();
const ops = useOpsStore();

const totals = ref<StatsTotals>({});
const clients = ref<ClientIntegration[]>([]);
const expanded = ref<ScopeKind | null>(null);
const customInput = ref("");

async function load() {
  try {
    const [stats, c] = await Promise.all([api.stats(), api.clients()]);
    totals.value = stats.totals ?? {};
    clients.value = c.results ?? [];
  } catch {
    /* handled by StatusStrip */
  }
}

onMounted(() => {
  load();
  scopes.ensureLoaded();
  ops.start();
});

onUnmounted(() => {
  ops.stop();
});

function opSeries(name: string): number[] {
  return ops.series[name] ?? [];
}

function opErrors(name: string): number {
  return ops.snapshots[name]?.errors ?? 0;
}

function opP50(name: string): number | null {
  const v = ops.snapshots[name]?.latency_p50_ms;
  return typeof v === "number" ? v : null;
}

function opTotal(name: string): number {
  return ops.snapshots[name]?.ok ?? 0;
}

const FIELD_BY_KIND: Record<ScopeKind, "user_id" | "agent_id" | "run_id"> = {
  user: "user_id",
  agent: "agent_id",
  run: "run_id",
};

function currentValue(kind: ScopeKind): string {
  return scope[FIELD_BY_KIND[kind]];
}

function toggle(kind: ScopeKind) {
  expanded.value = expanded.value === kind ? null : kind;
  customInput.value = "";
}

function pick(kind: ScopeKind, value: string) {
  scope.setExclusive(FIELD_BY_KIND[kind], value);
  expanded.value = null;
  customInput.value = "";
}

function applyCustom(kind: ScopeKind) {
  const value = customInput.value.trim();
  if (!value) return;
  pick(kind, value);
}

function clearOne(kind: ScopeKind) {
  scope[FIELD_BY_KIND[kind]] = "";
}
</script>

<template>
  <aside
    class="flex flex-col gap-4 border-r border-line bg-surface-sunken p-3 overflow-y-auto"
  >
    <section>
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[11px] uppercase tracking-wider text-ink-faint">
          Scope
        </span>
        <button
          v-if="!scope.isEmpty"
          class="text-[11px] text-ink-muted hover:text-ink"
          @click="scope.clear()"
        >
          clear all
        </button>
      </div>

      <div class="flex flex-col gap-1 text-[12px]">
        <template v-for="kind in (['user', 'agent', 'run'] as ScopeKind[])" :key="kind">
          <div>
            <div
              class="flex items-center rounded-sm hover:bg-surface-hover"
              :class="{ 'bg-surface-hover': expanded === kind }"
            >
              <button
                class="flex flex-1 items-center justify-between px-2 py-1 text-left font-mono"
                :class="currentValue(kind) ? 'text-ink-strong' : 'text-ink-muted'"
                @click="toggle(kind)"
              >
                <span>{{ kind }}</span>
                <span class="truncate pl-2 text-ink-faint">
                  {{ currentValue(kind) || '—' }}
                </span>
              </button>
              <button
                v-if="currentValue(kind)"
                class="px-1.5 py-1 text-ink-faint hover:text-danger"
                title="Clear"
                @click="clearOne(kind)"
              >
                ×
              </button>
            </div>

            <Transition name="rail-expand">
              <div
                v-if="expanded === kind"
                class="ml-2 mt-1 flex flex-col gap-0.5 border-l border-line-subtle pl-2 pb-1"
              >
                <div
                  v-if="scopes.loading && !scopes.byKind[kind].length"
                  class="px-2 py-1 text-[11px] text-ink-faint"
                >
                  Loading…
                </div>
                <div
                  v-else-if="!scopes.byKind[kind].length"
                  class="px-2 py-1 text-[11px] text-ink-faint"
                >
                  No known {{ kind }}s yet.
                </div>
                <button
                  v-for="entry in scopes.byKind[kind]"
                  :key="entry.value"
                  class="flex items-center justify-between rounded-sm px-2 py-1 text-left font-mono transition-colors hover:bg-surface-active"
                  :class="
                    currentValue(kind) === entry.value
                      ? 'text-ink-strong bg-accent-500/15'
                      : 'text-ink'
                  "
                  @click="pick(kind, entry.value)"
                >
                  <span class="truncate">{{ entry.value }}</span>
                  <span class="ml-2 shrink-0 text-[10px] text-ink-faint">
                    {{ entry.count }}
                  </span>
                </button>

                <form
                  class="mt-1 flex gap-1"
                  @submit.prevent="applyCustom(kind)"
                >
                  <input
                    v-model="customInput"
                    :placeholder="`custom ${kind}_id`"
                    class="flex-1 rounded-sm border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink outline-none focus:border-accent-500"
                  />
                  <button
                    type="submit"
                    class="rounded-sm bg-accent-500 px-2 py-1 text-[11px] text-accent-contrast transition-colors hover:bg-accent-600 disabled:opacity-40"
                    :disabled="!customInput.trim()"
                  >
                    set
                  </button>
                </form>
              </div>
            </Transition>
          </div>
        </template>
      </div>
    </section>

    <section>
      <div class="mb-2 text-[11px] uppercase tracking-wider text-ink-faint">
        Filters
      </div>
      <label class="flex items-center gap-2 rounded-sm px-2 py-1 text-[12px] hover:bg-surface-hover">
        <input
          type="checkbox"
          :checked="records.pinnedOnly"
          class="accent-accent-500"
          @change="records.pinnedOnly = ($event.target as HTMLInputElement).checked"
        />
        <span>Pinned only</span>
      </label>
    </section>

    <section>
      <div class="mb-2 text-[11px] uppercase tracking-wider text-ink-faint">
        Counts
      </div>
      <div class="grid grid-cols-2 gap-1 font-mono text-[12px]">
        <div class="rounded-sm bg-surface px-2 py-1.5">
          <div class="text-ink-faint text-[10px]">records</div>
          <div class="text-ink-strong">{{ totals.memories ?? 0 }}</div>
        </div>
        <div class="rounded-sm bg-surface px-2 py-1.5">
          <div class="text-ink-faint text-[10px]">pinned</div>
          <div class="text-ink-strong">{{ totals.pinned ?? 0 }}</div>
        </div>
      </div>
    </section>

    <section>
      <div class="mb-2 flex items-center justify-between text-[11px] uppercase tracking-wider text-ink-faint">
        <span>Ops (live)</span>
        <span
          class="h-1.5 w-1.5 rounded-full"
          :class="ops.active ? 'bg-success pulse-dot' : 'bg-ink-faint'"
          :title="ops.active ? 'Polling /admin/stats/operations' : 'Idle'"
        />
      </div>
      <ul class="flex flex-col gap-0.5 font-mono text-[12px]">
        <li
          v-if="!ops.operationNames.length"
          class="px-2 py-1 text-[11px] text-ink-faint"
        >
          No operations yet.
        </li>
        <li
          v-for="name in ops.operationNames"
          :key="name"
          class="flex items-center gap-2 rounded-sm px-2 py-1"
          :title="`${opTotal(name)} calls · ${opErrors(name)} errors${opP50(name) !== null ? ` · p50 ${opP50(name)}ms` : ''}`"
        >
          <span class="flex-1 truncate text-ink-muted">{{ name }}</span>
          <Sparkline
            :data="opSeries(name)"
            :color="opErrors(name) > 0 ? 'var(--danger)' : 'var(--accent-500)'"
            :width="56"
            :height="12"
          />
          <span class="w-8 shrink-0 text-right text-[10px] text-ink-faint">
            {{ opTotal(name) }}
          </span>
        </li>
      </ul>
    </section>

    <section>
      <div class="mb-2 text-[11px] uppercase tracking-wider text-ink-faint">
        Clients
      </div>
      <ul class="flex flex-col gap-1 font-mono text-[12px]">
        <li
          v-for="client in clients"
          :key="client.target"
          class="flex items-center justify-between rounded-sm px-2 py-1 text-ink-muted"
        >
          <span class="truncate">{{ client.target }}</span>
          <span
            class="ml-2 shrink-0 text-[10px]"
            :class="{
              'text-success': client.health === 'connected',
              'text-info': client.health === 'configured',
              'text-warning': client.health === 'stale_config' || client.health === 'timeout',
              'text-ink-faint': client.health === 'not_configured' || client.health === 'not_detected',
            }"
          >{{ client.health }}</span>
        </li>
      </ul>
    </section>
  </aside>
</template>
