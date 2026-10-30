import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const configuredPort = Number.parseInt(process.env.MERAK_VITE_PORT || '5178', 10)
const devPort = Number.isInteger(configuredPort) && configuredPort > 0
  ? configuredPort
  : 5178

export default defineConfig({
  // The installed renderer is loaded through file://, so assets must be relative.
  base: './',
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@shared': resolve(__dirname, 'shared'),
    },
  },
  plugins: [
    react(),
  ],
  // This is one SPA, not a collection of HTML fixtures. An explicit entry
  // prevents cold dependency discovery from crawling backend test outputs.
  optimizeDeps: { entries: ['index.html'] },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Mermaid's two lazily loaded renderer chunks are ~620 kB. Keep the
    // warning threshold above those while splitting the initial application
    // and editor/markdown/UI dependencies into separate cacheable chunks.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('monaco-editor') || id.includes('@monaco-editor')) {
            return 'vendor-monaco'
          }
          if (
            id.includes('react-markdown')
            || id.includes('remark-')
            || id.includes('rehype-')
            || id.includes('/unified/')
            || id.includes('/micromark')
          ) {
            return 'vendor-markdown'
          }
          if (id.includes('@radix-ui')) return 'vendor-radix'
          if (
            id.includes('/react/')
            || id.includes('/react-dom/')
            || id.includes('/scheduler/')
            || id.includes('/zustand/')
          ) {
            return 'vendor-react'
          }
          return undefined
        },
      },
    },
  },
  server: {
    host: process.env.MERAK_VITE_HOST || '127.0.0.1',
    port: devPort,
    strictPort: true,
    watch: {
      // Watch frontend inputs, not hundreds of Python fixtures/bytecode files.
      // Directory matches prune traversal before any children are enumerated.
      ignored: [
        /(?:^|[/\\])(?:\.pytest[^/\\]*|test-tmp[^/\\]*|implementation-snapshot-[^/\\]*|\.backend-bytecode-cache|dist-electron)(?:[/\\]|$)/,
        `${__dirname.replace(/\\/g, '/')}/server/**`,
        `${__dirname.replace(/\\/g, '/')}/merak-skills/**`,
        `${__dirname.replace(/\\/g, '/')}/docs/**`,
      ],
    },
    warmup: {
      // Warm only the initial shell, not optional editors or renderer trees.
      // Vite can prepare these transforms while Electron/preload are building.
      clientFiles: [
        './src/main.tsx',
        './src/App.tsx',
        './src/layouts/IDELayout.tsx',
        './src/components/editor/CodeEditor.tsx',
      ],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8011',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8011',
        ws: true,
      },
    },
  },
})
