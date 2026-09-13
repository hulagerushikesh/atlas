import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Built output is served by FastAPI at /app from src/atlas/api/static.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/app/",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    outDir: path.resolve(__dirname, "../src/atlas/api/static"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/query": "http://localhost:8010", "/namespaces": "http://localhost:8010",
      "/health": "http://localhost:8010", "/ingest": "http://localhost:8010",
      "/usage": "http://localhost:8010", "/keys": "http://localhost:8010",
    },
  },
})
