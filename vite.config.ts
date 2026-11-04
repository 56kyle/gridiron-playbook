import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => ({
  root: "web",
  base: "./",
  plugins: [vue()],
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    rollupOptions: {
      input:
        mode === "test"
          ? {
              app: fileURLToPath(new URL("./web/index.html", import.meta.url)),
              harness: fileURLToPath(new URL("./web/test-harness.html", import.meta.url)),
            }
          : fileURLToPath(new URL("./web/index.html", import.meta.url)),
    },
  },
  worker: { format: "es" },
}));
