/**
 * Merak 工具安装脚本
 * 在 Electron 安装包的 afterInstall hook 中运行，也可手动执行：
 *   node scripts/install-tools.js
 *
 * 安装内容：
 *   1. @mermaid-js/mermaid-cli (mmdc) — Mermaid 渲染为 PDF/PNG
 *   2. draw.io CLI 检测提示
 */

const { execSync, spawnSync } = require('child_process')
const path = require('path')
const fs = require('fs')
const os = require('os')

// 安装包携带的工具目录（Electron 打包后在 resources/tools/）
const TOOLS_DIR = process.env.MERAK_TOOLS_DIR
  || path.join(__dirname, '..', 'resources', 'tools')

function log(msg) { console.log(`[MERAK tools] ${msg}`) }
function warn(msg) { console.warn(`[MERAK tools] ⚠ ${msg}`) }

function hasCommand(cmd) {
  const r = spawnSync(os.platform() === 'win32' ? 'where' : 'which', [cmd], { stdio: 'pipe' })
  return r.status === 0
}

// ──────────────────────────────────────────────────────────────
// 1. mmdc (mermaid-cli)
// ──────────────────────────────────────────────────────────────
function installMmdc() {
  const mmdcInTools = path.join(TOOLS_DIR, 'node_modules', '.bin',
    os.platform() === 'win32' ? 'mmdc.cmd' : 'mmdc')

  if (fs.existsSync(mmdcInTools)) {
    log('mmdc already installed in tools dir')
    return
  }

  if (hasCommand('mmdc')) {
    log('mmdc found in PATH, skipping bundled install')
    return
  }

  log(`Installing @mermaid-js/mermaid-cli into ${TOOLS_DIR} ...`)
  fs.mkdirSync(TOOLS_DIR, { recursive: true })

  // 在 TOOLS_DIR 里本地安装（不污染全局）
  const result = spawnSync(
    os.platform() === 'win32' ? 'npm.cmd' : 'npm',
    ['install', '--prefix', TOOLS_DIR, '@mermaid-js/mermaid-cli', '--no-save'],
    { stdio: 'inherit', cwd: TOOLS_DIR }
  )

  if (result.status === 0) {
    log('mmdc installed successfully')
  } else {
    warn('mmdc install failed. Mermaid figures will be saved as .mmd source only.')
    warn('Manual install: npm install -g @mermaid-js/mermaid-cli')
  }
}

// ──────────────────────────────────────────────────────────────
// 2. drawio 导出（Merak 已内置 Electron 渲染导出，无需安装桌面版）
// ──────────────────────────────────────────────────────────────
function checkDrawio() {
  // Merak 通过隐藏 BrowserWindow + embed.diagrams.net 导出 PDF/PNG，
  // 不再依赖 draw.io 桌面版 CLI。
  // 如果用户已安装 draw.io 桌面版，保存路径作为额外备用。
  const candidates = os.platform() === 'win32'
    ? [
        'C:\\Program Files\\draw.io\\draw.io.exe',
        path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'draw.io', 'draw.io.exe'),
      ]
    : os.platform() === 'darwin'
    ? ['/Applications/draw.io.app/Contents/MacOS/draw.io']
    : ['/usr/bin/drawio', '/opt/drawio/drawio']

  const found = candidates.find(c => fs.existsSync(c))
  if (found) {
    log(`drawio desktop found at ${found} (will be used as CLI fallback)`)
    fs.mkdirSync(TOOLS_DIR, { recursive: true })
    fs.writeFileSync(path.join(TOOLS_DIR, 'drawio-path.txt'), found, 'utf8')
  } else {
    log('draw.io desktop not installed — using MERAK built-in Electron export instead (no action needed).')
  }
}

// ──────────────────────────────────────────────────────────────
// 写入工具目录路径供 Python 后端识别
// ──────────────────────────────────────────────────────────────
function writeToolsConfig() {
  fs.mkdirSync(TOOLS_DIR, { recursive: true })
  const config = { tools_dir: TOOLS_DIR, installed_at: new Date().toISOString() }
  fs.writeFileSync(
    path.join(TOOLS_DIR, 'tools-config.json'),
    JSON.stringify(config, null, 2),
    'utf8'
  )
  log(`Tools config written to ${path.join(TOOLS_DIR, 'tools-config.json')}`)
}

// ──────────────────────────────────────────────────────────────
// main
// ──────────────────────────────────────────────────────────────
log('Starting MERAK tool installation...')
writeToolsConfig()
installMmdc()
checkDrawio()
log('Tool installation complete.')
