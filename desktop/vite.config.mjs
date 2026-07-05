import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

const real = (p) => {
  try { return fs.realpathSync(p) } catch { return null }
}

const fsAllow = [
  ...new Set([
    path.resolve(process.cwd(), '..'),
    real(path.resolve(process.cwd(), 'node_modules')),
    real(path.resolve(process.cwd(), '../node_modules'))
  ].filter(Boolean))
]

export default defineConfig({
  base: './',
  plugins: [react()],
  css: { postcss: { plugins: [] } },
  build: {
    chunkSizeWarningLimit: 25000,
    rollupOptions: {
      output: { manualChunks: undefined }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(process.cwd(), './src'),
      '@hermes/shared': path.resolve(process.cwd(), '../shared/src'),
    },
    dedupe: ['react', 'react-dom']
  },
  server: { host: '127.0.0.1', port: 5174, strictPort: true, fs: { allow: fsAllow } },
  preview: { host: '127.0.0.1', port: 4174 }
})
