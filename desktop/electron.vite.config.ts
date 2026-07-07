import { defineConfig } from "electron-vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  main: {
    build: {
      rollupOptions: { external: ["electron"] }
    }
  },
  preload: {
    build: {
      rollupOptions: { external: ["electron"] }
    }
  },
  renderer: {
    plugins: [react(), tailwindcss()],
    build: {
      rollupOptions: {
        output: { format: "es" }
      }
    }
  }
})
