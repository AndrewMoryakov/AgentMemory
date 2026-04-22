import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

const API_TARGET = process.env.AGENTMEMORY_API_URL ?? "http://localhost:8765";
const API_TOKEN = process.env.AGENTMEMORY_API_TOKEN ?? "";
const PROXIED_PATHS = [
  "/admin",
  "/add",
  "/search",
  "/update",
  "/health",
  "/metrics",
  "/memories",
  "/mcp",
  "/oauth",
  "/.well-known",
];

const proxyOptions = {
  target: API_TARGET,
  changeOrigin: false,
  configure: (proxy: { on: (event: string, handler: (proxyReq: { setHeader: (name: string, value: string) => void }) => void) => void }) => {
    if (!API_TOKEN) return;
    proxy.on("proxyReq", (proxyReq) => {
      proxyReq.setHeader("Authorization", `Bearer ${API_TOKEN}`);
    });
  },
};

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(PROXIED_PATHS.map((path) => [path, proxyOptions])),
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
});
