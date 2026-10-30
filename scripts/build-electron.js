/**
 * Electron 构建脚本
 * Dev: esbuild watch + spawn electron
 * Prod: esbuild build once
 */
const esbuild = require('esbuild')
const { spawn } = require('child_process')
const { createElectronDevLifecycle } = require('./electron-dev-lifecycle.cjs')

const isDev = process.argv.includes('--watch')

const commonOptions = {
  bundle: true,
  platform: 'node',
  target: 'node20',
  format: 'cjs',
  sourcemap: isDev,
  external: ['electron'],
  logLevel: 'info',
}

const rendererOptions = {
  bundle: true,
  platform: 'browser',
  target: 'chrome120',
  format: 'iife',
  sourcemap: isDev,
  logLevel: 'info',
}

async function build() {
  await esbuild.build({ ...commonOptions, entryPoints: ['electron/main.ts'], outfile: 'dist-electron/main.js' })
  await esbuild.build({ ...commonOptions, entryPoints: ['electron/preload.ts'], outfile: 'dist-electron/preload.js' })
  await esbuild.build({ ...rendererOptions, entryPoints: ['electron/mermaid-renderer.ts'], outfile: 'dist-electron/mermaid-renderer.js' })
  console.log('✓ Electron built')
}

async function watch() {
  const lifecycle = createElectronDevLifecycle({
    viteUrl: process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5178',
    spawnElectron: viteUrl => spawn(require('electron'), ['.'], {
      stdio: 'inherit',
      env: { ...process.env, VITE_DEV_SERVER_URL: viteUrl },
    }),
  })

  const mainCtx = await esbuild.context({
    ...commonOptions,
    entryPoints: ['electron/main.ts'],
    outfile: 'dist-electron/main.js',
    plugins: [{
      name: 'electron-restart',
      setup(build) {
        build.onEnd((result) => {
          if (result.errors.length > 0) return
          // Only the current build may launch after the selected Vite URL is ready.
          void lifecycle.restart().catch(error => console.error('[Merak] Electron restart failed:', error))
        })
      }
    }],
  })

  await esbuild.context({
    ...commonOptions,
    entryPoints: ['electron/preload.ts'],
    outfile: 'dist-electron/preload.js',
  }).then(ctx => ctx.watch())

  await esbuild.context({
    ...rendererOptions,
    entryPoints: ['electron/mermaid-renderer.ts'],
    outfile: 'dist-electron/mermaid-renderer.js',
  }).then(ctx => ctx.watch())

  await mainCtx.watch()
  console.log('👀 Watching...')

  const shutdown = () => {
    void lifecycle.shutdown()
      .catch(error => console.error('[Merak] Electron shutdown failed:', error))
      .finally(() => process.exit())
  }
  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
}

isDev ? watch() : build()
