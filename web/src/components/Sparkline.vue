<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    data: number[];
    width?: number;
    height?: number;
    stroke?: number;
    color?: string;
    fillOpacity?: number;
  }>(),
  {
    width: 64,
    height: 14,
    stroke: 1.25,
    color: "var(--accent-500)",
    fillOpacity: 0.18,
  },
);

const pad = 1; // keep stroke fully inside the viewBox

const max = computed(() => Math.max(1, ...props.data));
const safeData = computed(() =>
  props.data.length ? props.data : [0, 0],
);

const points = computed(() => {
  const n = safeData.value.length;
  const w = props.width - pad * 2;
  const h = props.height - pad * 2;
  return safeData.value
    .map((v, i) => {
      const x = n === 1 ? props.width / 2 : pad + (i / (n - 1)) * w;
      const y = pad + (h - (v / max.value) * h);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
});

const areaPath = computed(() => {
  const n = safeData.value.length;
  if (!n) return "";
  const w = props.width - pad * 2;
  const h = props.height - pad * 2;
  const first = safeData.value
    .map((v, i) => {
      const x = n === 1 ? props.width / 2 : pad + (i / (n - 1)) * w;
      const y = pad + (h - (v / max.value) * h);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `${first} L${props.width - pad},${props.height - pad} L${pad},${props.height - pad} Z`;
});

const hasMotion = computed(() =>
  safeData.value.some((v, i, arr) => i > 0 && v !== arr[i - 1]),
);
</script>

<template>
  <svg
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    aria-hidden="true"
    class="inline-block align-middle"
  >
    <path
      v-if="hasMotion"
      :d="areaPath"
      :fill="color"
      :fill-opacity="fillOpacity"
    />
    <polyline
      :points="points"
      fill="none"
      :stroke="hasMotion ? color : 'var(--line-strong)'"
      :stroke-width="stroke"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>
