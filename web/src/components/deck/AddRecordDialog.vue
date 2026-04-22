<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { useScopeStore } from "@/stores/scope";

const emit = defineEmits<{
  (e: "close"): void;
  (e: "created"): void;
}>();

const scope = useScopeStore();

const text = ref("");
const userId = ref(scope.user_id);
const agentId = ref(scope.agent_id);
const runId = ref(scope.run_id);
const metadataText = ref("");
const submitting = ref(false);
const error = ref<string | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);

onMounted(() => {
  nextTick(() => textareaRef.value?.focus());
});

function hasAnyScope() {
  return Boolean(
    userId.value.trim() || agentId.value.trim() || runId.value.trim(),
  );
}

async function submit() {
  if (!text.value.trim()) return;
  error.value = null;

  let metadata: Record<string, unknown> | undefined;
  if (metadataText.value.trim()) {
    try {
      metadata = JSON.parse(metadataText.value);
    } catch {
      error.value = "Metadata must be valid JSON.";
      return;
    }
  }

  submitting.value = true;
  try {
    await api.addMemory({
      text: text.value.trim(),
      user_id: userId.value.trim() || undefined,
      agent_id: agentId.value.trim() || undefined,
      run_id: runId.value.trim() || undefined,
      metadata,
      infer: false,
      dedup: false,
    });
    emit("created");
    emit("close");
  } catch (exc) {
    error.value = (exc as Error).message;
  } finally {
    submitting.value = false;
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
  } else if (
    (event.metaKey || event.ctrlKey) &&
    event.key === "Enter" &&
    text.value.trim()
  ) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-start justify-center bg-black/55 backdrop-blur-sm pt-[12vh]"
    @click.self="emit('close')"
    @keydown="onKeydown"
  >
    <Transition name="panel" appear>
      <form
        class="w-[560px] max-w-[92vw] overflow-hidden rounded-lg border border-line-strong bg-bg-raised shadow-2xl"
        @submit.prevent="submit"
      >
      <header class="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 class="text-[14px] font-medium text-ink-strong">New memory</h2>
        <button
          type="button"
          class="text-ink-faint hover:text-ink"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <div class="flex flex-col gap-3 px-4 py-3">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] uppercase tracking-wider text-ink-faint">
            Memory
          </span>
          <textarea
            ref="textareaRef"
            v-model="text"
            rows="4"
            placeholder="What should the assistant remember?"
            class="resize-y rounded-md border border-line bg-surface px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent-500"
          />
        </label>

        <div class="grid grid-cols-3 gap-2">
          <label class="flex flex-col gap-1">
            <span class="text-[11px] uppercase tracking-wider text-ink-faint">user</span>
            <input
              v-model="userId"
              class="rounded-md border border-line bg-surface px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] uppercase tracking-wider text-ink-faint">agent</span>
            <input
              v-model="agentId"
              class="rounded-md border border-line bg-surface px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
            />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] uppercase tracking-wider text-ink-faint">run</span>
            <input
              v-model="runId"
              class="rounded-md border border-line bg-surface px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
            />
          </label>
        </div>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] uppercase tracking-wider text-ink-faint">
            Metadata (JSON, optional)
          </span>
          <textarea
            v-model="metadataText"
            rows="3"
            placeholder='{"tags": ["preferences"]}'
            class="resize-y rounded-md border border-line bg-surface px-3 py-2 font-mono text-[12px] text-ink outline-none focus:border-accent-500"
          />
        </label>

        <p
          v-if="!hasAnyScope()"
          class="text-[11px] text-warning"
        >
          No scope set — some providers require at least one of user / agent / run.
        </p>

        <div
          v-if="error"
          class="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger"
        >
          {{ error }}
        </div>
      </div>

      <footer class="flex items-center justify-between border-t border-line bg-surface-sunken px-4 py-3">
        <span class="font-mono text-[11px] text-ink-faint">
          ⌘↵ save · esc cancel
        </span>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-md border border-line-strong bg-surface px-3 py-1.5 text-[12px] text-ink-muted hover:bg-surface-hover"
            @click="emit('close')"
          >
            Cancel
          </button>
          <button
            type="submit"
            class="rounded-md bg-accent-500 px-4 py-1.5 text-[12px] font-medium text-accent-contrast hover:bg-accent-600 disabled:opacity-40"
            :disabled="submitting || !text.trim()"
          >
            {{ submitting ? "Saving…" : "Save" }}
          </button>
        </div>
      </footer>
      </form>
    </Transition>
  </div>
</template>
