import { jsxLocPlugin } from "@builder.io/vite-plugin-jsx-loc";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

const plugins = [react(), tailwindcss(), jsxLocPlugin()];

export default defineConfig({
  plugins,
  resolve: {
    alias: {
      "@": path.resolve(
        import.meta.dirname,
        "packages",
        "ce-web-client",
        "src"
      ),
      "@context-engineering/core": path.resolve(
        import.meta.dirname,
        "packages",
        "ce-core",
        "src"
      ),
      "@context-engineering/memory": path.resolve(
        import.meta.dirname,
        "packages",
        "ce-memory",
        "src"
      ),
      "@context-engineering/providers": path.resolve(
        import.meta.dirname,
        "packages",
        "ce-providers",
        "src"
      ),
    },
  },
  envDir: path.resolve(import.meta.dirname),
  root: path.resolve(import.meta.dirname, "packages", "ce-web-client"),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    strictPort: false,
    host: true,
    allowedHosts: ["localhost", "127.0.0.1"],
    fs: {
      strict: true,
      deny: ["**/.*"],
    },
  },
});
