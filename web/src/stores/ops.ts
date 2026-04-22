import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/api/client";

const MAX_POINTS = 60;   // ~5 min of history at 5s poll
const POLL_MS = 5000;

export interface OpSnapshot {
  ok: number;
  errors: number;
  latency_count?: number;
  latency_avg_ms?: number;
  latency_p50_ms?: number;
  latency_p95_ms?: number;
  latency_p99_ms?: number;
}

export const useOpsStore = defineStore("ops", () => {
  const snapshots = ref<Record<string, OpSnapshot>>({});
  const series = ref<Record<string, number[]>>({});
  const errorSeries = ref<Record<string, number[]>>({});
  const uptimeSeconds = ref(0);
  const lastUpdated = ref<number | null>(null);
  const active = ref(false);

  const operationNames = computed(() => {
    const known = new Set([
      ...Object.keys(snapshots.value),
      ...Object.keys(series.value),
    ]);
    return Array.from(known).sort();
  });

  let timer: number | null = null;
  let consumers = 0;
  const prevOk = new Map<string, number>();
  const prevErr = new Map<string, number>();
  let primed = false;

  function pushSample(
    target: Record<string, number[]>,
    name: string,
    value: number,
  ) {
    const buf = target[name] ? [...target[name]] : [];
    buf.push(value);
    while (buf.length > MAX_POINTS) buf.shift();
    target[name] = buf;
  }

  async function poll() {
    try {
      const payload = await api.operations();
      const raw = payload as unknown as {
        operations?: Record<string, OpSnapshot>;
        uptime_seconds?: number;
      };
      const ops = raw.operations ?? {};
      uptimeSeconds.value = raw.uptime_seconds ?? 0;
      lastUpdated.value = Date.now();
      snapshots.value = ops;

      const nextSeries = { ...series.value };
      const nextErrors = { ...errorSeries.value };

      // ensure every known op has an entry even at zero
      const seen = new Set<string>();
      for (const [name, data] of Object.entries(ops)) {
        seen.add(name);
        const priorOk = prevOk.has(name) ? prevOk.get(name)! : data.ok ?? 0;
        const priorErr = prevErr.has(name) ? prevErr.get(name)! : data.errors ?? 0;
        const deltaOk = Math.max(0, (data.ok ?? 0) - priorOk);
        const deltaErr = Math.max(0, (data.errors ?? 0) - priorErr);
        prevOk.set(name, data.ok ?? 0);
        prevErr.set(name, data.errors ?? 0);

        // first tick is always 0 to avoid a huge spike from initial value
        if (primed) {
          pushSample(nextSeries, name, deltaOk);
          pushSample(nextErrors, name, deltaErr);
        } else {
          pushSample(nextSeries, name, 0);
          pushSample(nextErrors, name, 0);
        }
      }

      // ops that previously existed but didn't come back this tick — still push 0
      for (const name of Object.keys(nextSeries)) {
        if (!seen.has(name)) pushSample(nextSeries, name, 0);
      }
      for (const name of Object.keys(nextErrors)) {
        if (!seen.has(name)) pushSample(nextErrors, name, 0);
      }

      series.value = nextSeries;
      errorSeries.value = nextErrors;
      primed = true;
    } catch {
      /* surfaced elsewhere */
    }
  }

  function start() {
    consumers += 1;
    if (timer !== null) return;
    active.value = true;
    poll();
    timer = window.setInterval(poll, POLL_MS);
  }

  function stop() {
    consumers = Math.max(0, consumers - 1);
    if (consumers === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
      active.value = false;
    }
  }

  return {
    snapshots,
    series,
    errorSeries,
    uptimeSeconds,
    lastUpdated,
    active,
    operationNames,
    start,
    stop,
  };
});
