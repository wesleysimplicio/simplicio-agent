import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'
export default defineConfig({
  cacheDir: 'C:/Users/Z0059V7A/AppData/Local/Temp/claude/vitest-fresh-cache',
  plugins: [react()],
  resolve: { alias: {
    '@': path.resolve(import.meta.dirname, 'src'),
    '@hermes/shared': path.resolve(import.meta.dirname, '../apps/shared/src')
  } },
  test: { environment: 'jsdom' }
})
