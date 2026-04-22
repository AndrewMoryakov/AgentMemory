<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { api, ApiError } from "@/api/client";
import type { MemoryRecord } from "@/api/types";
import { useScopesStore } from "@/stores/scopes";
import MeTimeline from "@/components/me/MeTimeline.vue";

const scopes = useScopesStore();

const profile = ref(localStorage.getItem("me.profile") ?? "");
const draft = ref(profile.value);
const query = ref("");
const items = ref<MemoryRecord[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const loadedOnce = ref(false);

const hasProfile = computed(() => profile.value.trim().length > 0);

const knownProfiles = computed(() => scopes.byKind.user);

async function reload() {
  if (!hasProfile.value) {
    items.value = [];
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    const payload = await api.listMemories({
      user_id: profile.value.trim(),
      query: query.value.trim() || undefined,
      limit: 500,
    });
    items.value = payload.items ?? [];
    loadedOnce.value = true;
  } catch (exc) {
    items.value = [];
    error.value = exc instanceof ApiError ? exc.message : (exc as Error).message;
  } finally {
    loading.value = false;
  }
}

function selectProfile(value: string) {
  profile.value = value;
  draft.value = value;
  query.value = "";
  reload();
}

function applyDraft() {
  profile.value = draft.value.trim();
  reload();
}

function switchProfile() {
  profile.value = "";
  items.value = [];
  draft.value = "";
  query.value = "";
}

async function forget(id: string) {
  if (!confirm("Forget this memory?")) return;
  await api.deleteMemory(id);
  items.value = items.value.filter((item) => item.id !== id);
}

async function forgetAll() {
  if (!items.value.length) return;
  const confirmed = confirm(
    `Forget all ${items.value.length} memories in this profile? This cannot be undone.`,
  );
  if (!confirmed) return;
  for (const item of [...items.value]) {
    await api.deleteMemory(item.id);
  }
  items.value = [];
}

watch(profile, (value) => {
  if (value) {
    localStorage.setItem("me.profile", value);
  } else {
    localStorage.removeItem("me.profile");
  }
});

onMounted(async () => {
  await scopes.ensureLoaded();
  if (hasProfile.value) reload();
});
</script>

<template>
  <div class="mx-auto flex h-full max-w-[720px] flex-col px-6 py-10">
    <header class="mb-8">
      <h1 class="text-2xl font-medium text-ink-strong">
        What does the assistant remember?
      </h1>
      <p class="mt-1 text-ink-muted">
        Pick a profile to inspect what it has stored.
      </p>
    </header>

    <template v-if="!hasProfile">
      <section class="rounded-md border border-line bg-surface p-5">
        <div
          v-if="scopes.loading && !knownProfiles.length"
          class="text-center text-ink-faint"
        >
          Loading profiles…
        </div>

        <div v-else-if="knownProfiles.length">
          <p class="mb-3 text-[12px] uppercase tracking-wider text-ink-faint">
            Known profiles
          </p>
          <ul class="flex flex-col gap-1.5">
            <li v-for="entry in knownProfiles" :key="entry.value">
              <button
                class="flex w-full items-center justify-between rounded-md border border-line bg-surface-sunken px-3 py-2.5 text-left hover:border-accent-500 hover:bg-surface-hover"
                @click="selectProfile(entry.value)"
              >
                <span class="font-mono text-[13px] text-ink">{{ entry.value }}</span>
                <span class="font-mono text-[11px] text-ink-muted">
                  {{ entry.count }} record{{ entry.count === 1 ? "" : "s" }}
                </span>
              </button>
            </li>
          </ul>
        </div>

        <p v-else class="text-center text-ink-muted">
          No profiles with memory yet.
        </p>

        <form
          class="mt-5 flex gap-2 border-t border-line pt-4"
          @submit.prevent="applyDraft"
        >
          <input
            v-model="draft"
            placeholder="Or enter a profile id…"
            class="flex-1 rounded-md border border-line bg-surface-sunken px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent-500"
          />
          <button
            type="submit"
            class="rounded-md bg-accent-500 px-4 py-2 text-[13px] font-medium text-accent-contrast hover:bg-accent-600 disabled:opacity-40"
            :disabled="!draft.trim()"
          >
            Show
          </button>
        </form>
      </section>
    </template>

    <template v-else>
      <section class="mb-6 flex items-center justify-between rounded-md border border-line bg-surface px-3 py-2">
        <div class="text-[13px]">
          <span class="text-ink-muted">Profile:</span>
          <span class="ml-2 font-mono text-ink-strong">{{ profile }}</span>
        </div>
        <button
          class="text-[12px] text-ink-muted hover:text-ink"
          @click="switchProfile"
        >
          switch
        </button>
      </section>

      <div v-if="items.length || loadedOnce" class="mb-6">
        <input
          v-model="query"
          placeholder="Search what I remember…"
          class="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent-500"
          @keydown.enter="reload"
        />
      </div>

      <div
        v-if="error"
        class="mb-4 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[13px] text-danger"
      >
        {{ error }}
      </div>

      <div
        v-if="loading && !items.length"
        class="rounded-md border border-line bg-surface p-6 text-center text-ink-muted"
      >
        Loading…
      </div>

      <div
        v-else-if="!items.length && loadedOnce && !error"
        class="rounded-md border border-line bg-surface p-6 text-center text-ink-muted"
      >
        Nothing remembered for this profile yet.
      </div>

      <MeTimeline
        v-else-if="items.length"
        :items="items"
        class="flex-1 min-h-0 overflow-auto"
        @forget="forget"
      />

      <footer v-if="items.length" class="mt-6 border-t border-line pt-4">
        <button
          class="text-[12px] text-danger hover:underline"
          @click="forgetAll"
        >
          Forget everything in this profile
        </button>
      </footer>
    </template>
  </div>
</template>
