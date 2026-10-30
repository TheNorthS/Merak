/** Build and verify the Windows x64 backend embedded in the desktop installer. */

const { spawnSync } = require('child_process')
const { createHash } = require('crypto')
const {
  existsSync, cpSync, mkdirSync, readFileSync, readdirSync,
  renameSync, rmSync, writeFileSync,
} = require('fs')
const path = require('path')

const projectRoot = path.resolve(__dirname, '..')
const runtimeRoot = path.join(projectRoot, 'resources', 'server-bundle', 'runtime')
const runtimeDir = path.join(runtimeRoot, 'win32-x64')
const executableName = 'merak-backend.exe'

function requireWindowsX64(platform, arch) {
  if (platform !== 'win32' || arch !== 'x64') {
    throw new Error('The standalone Merak installer currently supports Windows x64 only.')
  }
}

function buildPython() {
  if (process.env.MERAK_BUILD_PYTHON) return process.env.MERAK_BUILD_PYTHON
  const localVenv = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
  return existsSync(localVenv) ? localVenv : 'python'
}

function run(executable, args, options = {}) {
  const result = spawnSync(executable, args, {
    cwd: projectRoot,
    windowsHide: true,
    timeout: options.timeout || 15 * 60 * 1000,
    stdio: options.capture ? 'pipe' : 'inherit',
    encoding: options.capture ? 'utf8' : undefined,
    maxBuffer: 8 * 1024 * 1024,
  })
  if (result.error || result.status !== 0) {
    const detail = [result.error?.message, result.stderr, result.stdout]
      .filter(Boolean).join('\n').trim().slice(-4000)
    throw new Error(`${path.basename(executable)} failed (${result.status ?? 'no exit code'}): ${detail}`)
  }
  return result
}

function digestFile(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

function collectFiles(directory, include, excludedDirectories = new Set()) {
  const files = []
  const visit = (directory) => {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      if (item.isDirectory() && excludedDirectories.has(item.name)) continue
      const candidate = path.join(directory, item.name)
      if (item.isDirectory()) visit(candidate)
      else if (item.isFile() && include(candidate)) files.push(candidate)
    }
  }
  visit(directory)
  return files.sort()
}

function backendPythonSources(root = projectRoot) {
  return collectFiles(
    path.join(root, 'server'), file => file.endsWith('.py'),
    new Set(['tests', '__pycache__']),
  )
}

function backendTemplates(root = projectRoot) {
  return collectFiles(path.join(root, 'server'), file => file.endsWith('.tmpl'), new Set(['tests', '__pycache__']))
}

function backendSourceSnapshot(root = projectRoot) {
  return [...backendPythonSources(root), ...backendTemplates(root)].sort()
}

function skillSources(root = projectRoot) {
  return collectFiles(
    path.join(root, 'merak-skills'), file => !file.endsWith('.pyc'),
    new Set(['__pycache__']),
  )
}

function sourceDigest(root = projectRoot) {
  const files = [
    path.join(root, 'pyproject.toml'),
    path.join(root, 'requirements.lock'),
    path.join(root, 'scripts', 'merak_backend_entry.py'),
    path.join(root, 'scripts', 'build-backend.js'),
    ...backendSourceSnapshot(root),
    ...skillSources(root),
  ]
  const digest = createHash('sha256')
  for (const file of files.sort()) {
    digest.update(path.relative(root, file).replaceAll('\\', '/'))
    digest.update('\0')
    digest.update(readFileSync(file))
  }
  return digest.digest('hex')
}

function stageSources(files, sourceRoot, destination) {
  for (const file of files) {
    const target = path.join(destination, path.relative(sourceRoot, file))
    mkdirSync(path.dirname(target), { recursive: true })
    cpSync(file, target)
  }
  return destination
}

function verifyBundledSources(internalDir, root = projectRoot) {
  const groups = [
    [backendSourceSnapshot(root), path.join(root, 'server'), path.join(internalDir, 'merak-source', 'server')],
    [backendTemplates(root), path.join(root, 'server'), path.join(internalDir, 'server')],
    [skillSources(root), path.join(root, 'merak-skills'), path.join(internalDir, 'merak-skills')],
  ]
  for (const [files, sourceRoot, destination] of groups) {
    for (const file of files) {
      const bundled = path.join(destination, path.relative(sourceRoot, file))
      if (!existsSync(bundled) || digestFile(bundled) !== digestFile(file)) {
        throw new Error(`Bundled backend source snapshot is missing or changed: ${bundled}`)
      }
    }
  }
}

function publishBundle(builtDir, sourceSha256) {
  mkdirSync(runtimeRoot, { recursive: true })
  const nonce = `${process.pid}-${Date.now()}`
  const pending = path.join(runtimeRoot, `.win32-x64-pending-${nonce}`)
  const previous = path.join(runtimeRoot, `.win32-x64-previous-${nonce}`)
  cpSync(builtDir, pending, { recursive: true })
  writeFileSync(path.join(pending, 'merak-bundle.json'), JSON.stringify({
    schema_version: 1,
    platform: 'win32',
    arch: 'x64',
    source_sha256: sourceSha256,
    executable_sha256: digestFile(path.join(pending, executableName)),
  }, null, 2) + '\n', 'utf8')
  const hadPrevious = existsSync(runtimeDir)
  if (hadPrevious) renameSync(runtimeDir, previous)
  try {
    renameSync(pending, runtimeDir)
  } catch (error) {
    if (hadPrevious) renameSync(previous, runtimeDir)
    throw error
  }
  if (hadPrevious) rmSync(previous, { recursive: true, force: true })
}

function buildBackend() {
  requireWindowsX64(process.platform, process.arch)
  const python = buildPython()
  const templates = path.join(projectRoot, 'server', 'services', 'simulation_plot_templates')
  const skills = path.join(projectRoot, 'merak-skills')
  if (!existsSync(templates) || !existsSync(skills)) {
    throw new Error('Backend templates or merak-skills are missing from the source tree.')
  }
  const sourceSha256 = sourceDigest()
  const staging = path.join(projectRoot, '.backend-build', sourceSha256.slice(0, 20))
  mkdirSync(staging, { recursive: true })
  try {
    const pythonSources = stageSources(
      backendSourceSnapshot(), path.join(projectRoot, 'server'),
      path.join(staging, 'merak-source', 'server'),
    )
    const bundledSkills = stageSources(
      skillSources(), skills, path.join(staging, 'merak-skills'),
    )
    run(python, ['-m', 'PyInstaller', '--version'], { capture: true, timeout: 30000 })
    const args = [
      '-m', 'PyInstaller', '--noconfirm', '--onedir', '--console', '--noupx',
      '--name', 'merak-backend',
      '--distpath', path.join(staging, 'dist'),
      '--workpath', path.join(staging, 'work'),
      '--specpath', path.join(staging, 'spec'),
      '--paths', projectRoot,
      '--add-data', `${templates};server/services/simulation_plot_templates`,
      '--add-data', `${pythonSources};merak-source/server`,
      '--add-data', `${bundledSkills};merak-skills`,
      '--collect-submodules', 'server.agent',
      '--collect-submodules', 'server.api',
      '--collect-submodules', 'server.contracts',
      '--collect-submodules', 'server.db',
      '--collect-submodules', 'server.experiment_protocols',
      '--collect-submodules', 'server.models',
      '--collect-submodules', 'server.services',
      '--collect-submodules', 'server.utils',
      '--collect-submodules', 'server.workflows',
      '--collect-submodules', 'server.ws',
      '--hidden-import', 'pandas',
      '--collect-submodules', 'PIL',
      '--hidden-import', 'matplotlib.backends.backend_agg',
      '--hidden-import', 'matplotlib.backends.backend_pdf',
      '--hidden-import', 'matplotlib.backends.backend_svg',
      '--hidden-import', 'uvicorn.loops.asyncio',
      '--hidden-import', 'uvicorn.protocols.http.h11_impl',
      '--hidden-import', 'uvicorn.protocols.websockets.websockets_impl',
      '--hidden-import', 'uvicorn.lifespan.on',
      '--hidden-import', 'aiosqlite',
      '--hidden-import', 'asyncpg',
      '--hidden-import', 'sqlalchemy.dialects.sqlite.aiosqlite',
      '--exclude-module', 'server.tests',
      '--exclude-module', 'pandas.tests',
      '--exclude-module', 'numpy.tests',
      '--exclude-module', 'matplotlib.tests',
      '--exclude-module', 'pytest',
      '--exclude-module', '_pytest',
      '--exclude-module', 'tkinter',
      path.join(projectRoot, 'scripts', 'merak_backend_entry.py'),
    ]
    run(python, args, { timeout: 30 * 60 * 1000 })
    const builtDir = path.join(staging, 'dist', 'merak-backend')
    const executable = path.join(builtDir, executableName)
    if (!existsSync(executable) || !existsSync(path.join(builtDir, '_internal'))) {
      throw new Error(`PyInstaller did not produce a complete backend at ${builtDir}`)
    }
    if (sourceDigest() !== sourceSha256) {
      throw new Error('Backend sources changed during packaging; rebuild from a stable tree.')
    }
    verifyBundledSources(path.join(builtDir, '_internal'))
    const check = run(executable, ['--self-check'], { capture: true, timeout: 5 * 60 * 1000 })
    if (!check.stdout.includes('MERAK_BACKEND_BUNDLE_OK')) {
      throw new Error('The bundled backend did not pass its import self-check.')
    }
    publishBundle(builtDir, sourceSha256)
    console.log(`Verified backend bundle: ${path.join(runtimeDir, executableName)}`)
  } catch (error) {
    console.error(`Build cache retained for retry: ${staging}`)
    throw error
  }
  if (existsSync(runtimeDir)) {
    rmSync(staging, { recursive: true, force: true })
  }
}

exports.backendPythonSources = backendPythonSources
exports.backendTemplates = backendTemplates
exports.backendSourceSnapshot = backendSourceSnapshot
exports.skillSources = skillSources
exports.sourceDigest = sourceDigest
exports.stageSources = stageSources
exports.verifyBundledSources = verifyBundledSources

// electron-builder also invokes this hook when called directly, so an
// unsupported target or missing backend cannot silently yield a broken app.
exports.default = function beforePack(context) {
  const { Arch } = require('builder-util')
  if (context.electronPlatformName !== 'win32' || context.arch !== Arch.x64) {
    throw new Error('A matching bundled backend is unavailable for this Electron target.')
  }
  const executable = path.join(runtimeDir, executableName)
  if (!existsSync(executable) || !existsSync(path.join(runtimeDir, '_internal'))) {
    throw new Error(`Bundled backend is missing at ${executable}; run npm run build:backend.`)
  }
  const manifestPath = path.join(runtimeDir, 'merak-bundle.json')
  let manifest
  try {
    manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  } catch {
    throw new Error('Bundled backend manifest is missing or invalid; run npm run build:backend.')
  }
  if (
    manifest.schema_version !== 1
    || manifest.platform !== 'win32'
    || manifest.arch !== 'x64'
    || manifest.source_sha256 !== sourceDigest()
    || manifest.executable_sha256 !== digestFile(executable)
  ) {
    throw new Error('Bundled backend is stale or modified; run npm run build:backend.')
  }
  verifyBundledSources(path.join(runtimeDir, '_internal'))
}

if (require.main === module) {
  try {
    buildBackend()
  } catch (error) {
    console.error(`[Merak] Backend packaging failed: ${error.message}`)
    console.error('Use a Windows x64 build host with Python 3.11+ and pip install -e ".[build]".')
    process.exitCode = 1
  }
}
