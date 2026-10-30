const assert = require('node:assert/strict')
const { existsSync } = require('node:fs')
const { resolve } = require('node:path')
const test = require('node:test')

const projectRoot = resolve(__dirname, '..')
const configPath = resolve(projectRoot, 'vite.config.mts')
const expectedWarmupFiles = [
  './src/main.tsx',
  './src/App.tsx',
  './src/layouts/IDELayout.tsx',
  './src/components/editor/CodeEditor.tsx',
]

// Loading the real configuration proves the policy without opening a listener.
async function loadConfig(environment = {}) {
  const keys = ['MERAK_VITE_PORT', 'MERAK_VITE_HOST']
  const previous = keys.map((key) => [key, process.env[key]])
  for (const key of keys) {
    if (environment[key] === undefined) delete process.env[key]
    else process.env[key] = environment[key]
  }
  try {
    const { loadConfigFromFile } = await import('vite')
    const result = await loadConfigFromFile(
      { command: 'serve', mode: 'development' }, configPath, projectRoot,
    )
    assert.ok(result, 'the application Vite configuration must load')
    return result.config
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
}

test('startup warms a small existing shell, not broad or optional renderer trees', async () => {
  const config = await loadConfig()
  assert.deepEqual(config.server.warmup.clientFiles, expectedWarmupFiles)
  assert.equal(config.server.warmup.ssrFiles, undefined)
  for (const file of config.server.warmup.clientFiles) {
    assert.equal(/[?*{}]/.test(file), false, 'startup warmup must not expand into broad globs')
    assert.equal(existsSync(resolve(projectRoot, file)), true, `${file} must exist`)
  }
  assert.deepEqual(config.optimizeDeps, { entries: ['index.html'] }, 'scan only the SPA, retaining optimizer defaults')
})

test('watcher prunes generated directories without disabling frontend HMR inputs', async () => {
  const config = await loadConfig()
  const ignored = config.server.watch.ignored
  const directoryRule = ignored.find(value => value instanceof RegExp)
  assert.ok(directoryRule)
  for (const directory of ['.pytest-flow-123', 'test-tmp-delegate104', 'implementation-snapshot-123', '.backend-bytecode-cache', 'dist-electron']) {
    assert.equal(directoryRule.test(resolve(projectRoot, directory)), true, 'ignore the directory itself before crawling children')
    assert.equal(directoryRule.test(resolve(projectRoot, directory, 'nested/output.html')), true)
  }
  for (const file of ['src/main.tsx', 'src/bootstrap/startupSignal.ts', 'shared/renderer-startup.ts', 'index.html', 'vite.config.mts', 'public/test-api.html', 'resources/icon.png']) {
    const absolute = resolve(projectRoot, file).replace(/\\/g, '/')
    assert.equal(directoryRule.test(absolute), false, `${file} must remain watchable`)
    assert.equal(ignored.filter(value => typeof value === 'string').some(value => absolute.startsWith(value.slice(0, -3))), false)
  }
  for (const directory of ['server', 'merak-skills', 'docs']) {
    assert.ok(ignored.includes(`${projectRoot.replace(/\\/g, '/')}/${directory}/**`))
  }
  assert.equal(config.server.watch.usePolling, undefined, 'do not add expensive polling')
})

test('warmup preserves the selected local port and backend proxy contracts', async () => {
  const config = await loadConfig({ MERAK_VITE_PORT: '5193', MERAK_VITE_HOST: '127.0.0.1' })
  assert.equal(config.server.port, 5193)
  assert.equal(config.server.host, '127.0.0.1')
  assert.equal(config.server.strictPort, true)
  assert.deepEqual(config.server.proxy, {
    '/api': { target: 'http://127.0.0.1:8011', changeOrigin: true },
    '/ws': { target: 'ws://127.0.0.1:8011', ws: true },
  })
})

test('the default and invalid configured ports retain the existing safe fallback', async () => {
  for (const environment of [{}, { MERAK_VITE_PORT: 'invalid' }, { MERAK_VITE_PORT: '0' }]) {
    const config = await loadConfig(environment)
    assert.equal(config.server.port, 5178)
    assert.equal(config.server.host, '127.0.0.1')
  }
})
