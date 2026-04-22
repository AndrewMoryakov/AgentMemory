<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "@/api/client";
import { useRecordsStore } from "@/stores/records";

const records = useRecordsStore();
const provider = ref<string>("…");
const host = ref<string>("");
const healthy = ref(true);
const lastError = ref<string | null>(null);

let timer: number | undefined;

async function poll() {
  try {
    const stats = await api.stats();
    provider.value = stats.provider;
    host.value = `${stats.runtime?.api_host ?? "?"}:${stats.runtime?.api_port ?? "?"}`;
    healthy.value = true;
    lastError.value = null;
  } catch (exc) {
    healthy.value = false;
    lastError.value = (exc as Error).message;
  }
}

onMounted(() => {
  poll();
  timer = window.setInterval(poll, 5000);
});

onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <footer
    class="flex items-center justify-between border-t border-line bg-bg-raised px-4 font-mono text-[11px] text-ink-muted"
  >
    <div class="flex items-center gap-4">
      <span class="flex items-center gap-1.5">
        <span
          class="inline-block h-1.5 w-1.5 rounded-full"
          :class="healthy ? 'bg-success pulse-dot' : 'bg-danger'"
        />
        {{ healthy ? "connected" : "offline" }}
      </span>
      <span>{{ provider }}</span>
      <span>{{ host }}</span>
      <span>{{ records.items.length }} rec</span>
    </div>
    <div class="flex items-center gap-4">
      <span v-if="lastError" class="text-danger">{{ lastError }}</span>
      <router-link to="/me" class="hover:text-ink">/me</router-link>
    </div>
  </footer>
</template>
