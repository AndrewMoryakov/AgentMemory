<script setup lang="ts">
defineEmits<{ (e: "close"): void }>();

interface Row {
  keys: string[];
  label: string;
}
interface Group {
  title: string;
  rows: Row[];
}

const groups: Group[] = [
  {
    title: "Navigate",
    rows: [
      { keys: ["j", "↓"], label: "Next record" },
      { keys: ["k", "↑"], label: "Previous record" },
      { keys: ["g"], label: "First record" },
      { keys: ["G"], label: "Last record" },
      { keys: ["⌘K", "Ctrl K", "/"], label: "Open search palette" },
    ],
  },
  {
    title: "Select (bulk)",
    rows: [
      { keys: ["Space"], label: "Toggle check on focused record" },
      { keys: ["⌘A", "Ctrl A"], label: "Check all visible" },
      { keys: ["Shift ·click"], label: "Check range of records" },
      { keys: ["Esc"], label: "Clear checked" },
    ],
  },
  {
    title: "Edit",
    rows: [
      { keys: ["n"], label: "New memory" },
      { keys: ["p"], label: "Toggle pin" },
      { keys: ["x", "Del"], label: "Delete record" },
      { keys: ["r"], label: "Reload records" },
    ],
  },
  {
    title: "View",
    rows: [
      { keys: ["t"], label: "Table ↔ Timeline" },
      { keys: ["i"], label: "Toggle inspector" },
      { keys: ["?"], label: "Show this help" },
    ],
  },
];

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape" || event.key === "?") {
    event.preventDefault();
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm pt-[10vh]"
    @click.self="$emit('close')"
    @keydown="onKey"
  >
    <Transition name="panel" appear>
      <div
        class="w-[620px] max-w-[92vw] overflow-hidden rounded-lg border border-line-strong bg-bg-raised shadow-2xl"
      >
        <header
          class="flex items-center justify-between border-b border-line px-4 py-3"
        >
          <h2 class="text-[14px] font-medium text-ink-strong">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            class="text-ink-faint hover:text-ink"
            @click="$emit('close')"
          >
            ×
          </button>
        </header>

        <div class="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-4 text-[12px]">
          <section v-for="group in groups" :key="group.title">
            <h3 class="mb-2 text-[11px] uppercase tracking-wider text-ink-faint">
              {{ group.title }}
            </h3>
            <ul class="flex flex-col gap-1.5">
              <li
                v-for="row in group.rows"
                :key="row.label"
                class="flex items-center justify-between gap-3"
              >
                <span class="text-ink">{{ row.label }}</span>
                <span class="flex shrink-0 items-center gap-1">
                  <kbd
                    v-for="(k, idx) in row.keys"
                    :key="k + idx"
                    class="rounded border border-line-strong bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-muted"
                  >
                    {{ k }}
                  </kbd>
                </span>
              </li>
            </ul>
          </section>
        </div>

        <footer
          class="flex items-center justify-between border-t border-line bg-surface-sunken px-4 py-2"
        >
          <span class="font-mono text-[11px] text-ink-faint">
            esc to close
          </span>
          <span class="font-mono text-[11px] text-ink-faint">
            shortcuts work when focus isn't in an input
          </span>
        </footer>
      </div>
    </Transition>
  </div>
</template>
