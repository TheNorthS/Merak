import { handleTrusted } from '../trusted-ipc'
/**
 * Draw.io 集成 — Electron 主进程
 *
 * 提供两种能力：
 * 1. IPC drawio:save-export  — 前端把 export 数据 base64 保存到磁盘
 * 2. HTTP /drawio-export     — Python 后端调用，用隐藏 BrowserWindow + embed.diagrams.net
 *    渲染 .drawio XML 并导出 PDF/PNG/SVG，无需安装 draw.io 桌面版
 */

import { BrowserWindow, app } from 'electron'
import { join, dirname, extname, resolve } from 'path'
import { writeFileSync, mkdirSync, readFileSync, renameSync, rmSync } from 'fs'
import http from 'http'
import net from 'net'
import { randomUUID } from 'crypto'

let _electronApiPort = 0
const MAX_RENDER_REQUEST_BYTES = 8 * 1024 * 1024
const MAX_IPC_EXPORT_BYTES = 32 * 1024 * 1024
let renderRequestActive = false

function decodeBase64Export(data: string): Buffer {
  const encoded = data.includes(',') ? data.slice(data.indexOf(',') + 1) : data
  const normalized = encoded.replace(/\s/g, '')
  if (
    !normalized ||
    normalized.length % 4 !== 0 ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(normalized)
  ) {
    throw new Error('Export data is not valid base64')
  }
  const decoded = Buffer.from(normalized, 'base64')
  if (!decoded.length) throw new Error('Export data is empty')
  if (decoded.length > MAX_IPC_EXPORT_BYTES) {
    throw new Error('Export data exceeds the 32 MiB limit')
  }
  return decoded
}

function atomicWriteBuffer(outputPath: string, value: Buffer): void {
  const outputDir = dirname(outputPath)
  mkdirSync(outputDir, { recursive: true })
  const temporary = join(outputDir, `.${randomUUID()}.merak-render.tmp`)
  try {
    writeFileSync(temporary, value, { flag: 'wx' })
    renameSync(temporary, outputPath)
  } finally {
    try { rmSync(temporary, { force: true }) } catch { /* best effort */ }
  }
}

export function getElectronApiPort(): number {
  return _electronApiPort
}

// ── 找空闲端口 ──────────────────────────────────────────────────────────────
async function findFreePort(start: number): Promise<number> {
  for (let port = start; port < start + 20; port++) {
    const free = await new Promise<boolean>((resolve) => {
      const s = net.createServer()
      s.once('error', () => resolve(false))
      s.once('listening', () => { s.close(); resolve(true) })
      s.listen(port, '127.0.0.1')
    })
    if (free) return port
  }
  return start
}

// ── 隐藏窗口渲染导出 ────────────────────────────────────────────────────────
async function exportDrawioXml(
  xml: string,
  format: 'pdf' | 'png' | 'svg',
): Promise<Buffer> {
  const isDev = !app.isPackaged
  const exportHtml = isDev
    ? join(__dirname, '../resources/drawio-export.html')
    : join(process.resourcesPath, 'drawio-export.html')

  const win = new BrowserWindow({
    show: false,
    width: 1280,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  })

  try {
    await win.loadFile(exportHtml)

    // 注入 postMessage 桥接脚本（与 embed.diagrams.net 通信）
    await win.webContents.executeJavaScript(`
      (() => {
        window.__merak_export_done = null;
        const _xml = ${JSON.stringify(xml)};
        const _fmt = ${JSON.stringify(format)};

        function post(msg) {
          const f = document.getElementById('drawio');
          if (f && f.contentWindow)
            f.contentWindow.postMessage(JSON.stringify(msg), 'https://embed.diagrams.net');
        }

        window.addEventListener('message', function(ev) {
          const frame = document.getElementById('drawio');
          if (ev.origin !== 'https://embed.diagrams.net' || ev.source !== frame?.contentWindow) return;
          if (typeof ev.data !== 'string') return;
          try {
            const m = JSON.parse(ev.data);
            if (m.event === 'init') {
              post({ action: 'load', xml: _xml });
              setTimeout(() => post({ action: 'export', format: _fmt }), 800);
            } else if (m.event === 'export') {
              window.__merak_export_done = m.data || '';
            }
          } catch(e) {}
        });
      })();
    `)

    // 轮询等待 export 数据（最多 30 s）
    let data: string | null = null
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000))
      data = await win.webContents.executeJavaScript('window.__merak_export_done')
      if (data !== null) break
    }

    if (data === null) throw new Error('draw.io export timed out after 30s')

    // data URL 格式：data:<mime>;base64,<base64>
    return decodeBase64Export(data)
  } finally {
    win.destroy()
  }
}


// ── Mermaid 内置渲染：与前端使用同一版本的官方 Mermaid ────────────────────
function mermaidViewport(svg: string): { width: number; height: number } {
  const match = svg.match(/viewBox=["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)["']/i)
  const sourceWidth = match ? Number(match[1]) : 1200
  const sourceHeight = match ? Number(match[2]) : 800
  const width = 1600
  const ratio = Number.isFinite(sourceHeight / sourceWidth) ? sourceHeight / sourceWidth : 2 / 3
  const height = Math.max(320, Math.min(2000, Math.round(width * ratio)))
  return { width, height }
}

async function exportMermaidCode(
  code: string,
  format: 'pdf' | 'png' | 'svg' = 'svg',
): Promise<Buffer> {
  const win = new BrowserWindow({
    show: false,
    width: 1600,
    height: 1000,
    useContentSize: true,
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  })

  try {
    await win.loadURL('data:text/html;charset=utf-8,<html><body></body></html>')
    const rendererPath = join(__dirname, 'mermaid-renderer.js')
    const rendererScript = readFileSync(rendererPath, 'utf8')
    await win.webContents.executeJavaScript(rendererScript)
    const svg = await win.webContents.executeJavaScript(
      `window.__merakRenderMermaid(${JSON.stringify(code)}, 'neutral')`,
    )
    if (!svg || typeof svg !== 'string') {
      throw new Error('Mermaid renderer returned an empty SVG')
    }
    if (format === 'svg') {
      return Buffer.from(svg, 'utf8')
    }

    const viewport = mermaidViewport(svg)
    win.setContentSize(viewport.width, viewport.height)
    await win.webContents.executeJavaScript(`
      document.documentElement.style.background = '#ffffff';
      document.documentElement.style.overflow = 'hidden';
      document.body.style.cssText = 'margin:0;background:#fff;overflow:hidden;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;';
      document.body.innerHTML = ${JSON.stringify(svg)};
      const rendered = document.body.querySelector('svg');
      if (rendered) {
        rendered.removeAttribute('width');
        rendered.removeAttribute('height');
        rendered.style.width = '100%';
        rendered.style.height = '100%';
        rendered.style.maxWidth = 'none';
        rendered.style.background = '#ffffff';
      }
    `)
    await new Promise((resolve) => setTimeout(resolve, 150))
    if (format === 'pdf') {
      const pdf = await win.webContents.printToPDF({ printBackground: true })
      if (!pdf.length) throw new Error('Mermaid PDF export was empty')
      return pdf
    }
    const image = await win.webContents.capturePage()
    const png = image.toPNG()
    if (!png.length) throw new Error('Mermaid PNG capture was empty')
    return png
  } finally {
    win.destroy()
  }
}

// ── 注册 IPC + HTTP API ─────────────────────────────────────────────────────
export async function registerDrawioHandlers(): Promise<void> {
  // IPC: 前端把 drawio export 的 base64 数据保存到磁盘
  handleTrusted(
    'drawio:save-export',
    async (_event, { data, format, outputPath }: { data: string; format: string; outputPath: string }) => {
      try {
        const normalizedFormat = String(format || '').toLowerCase()
        if (!['svg', 'pdf', 'png'].includes(normalizedFormat)) {
          throw new Error('Unsupported Draw.io export format')
        }
        const resolvedOutput = resolve(outputPath)
        if (extname(resolvedOutput).toLowerCase() !== `.${normalizedFormat}`) {
          throw new Error('Export path extension does not match its format')
        }
        atomicWriteBuffer(resolvedOutput, decodeBase64Export(data))
        return { success: true, path: resolvedOutput }
      } catch (err: any) {
        return { success: false, error: err.message }
      }
    },
  )

  // HTTP API: Python 后端调用
  // POST /drawio-export  body: { xml, format, output_path }
  const port = await findFreePort(18765)
  _electronApiPort = port

  const server = http.createServer(async (req, res) => {
    const route = req.url || ''
    if (req.method !== 'POST' || !['/drawio-export', '/mermaid-export'].includes(route)) {
      res.writeHead(404)
      res.end()
      return
    }

    if (renderRequestActive) {
      res.writeHead(429, { 'Content-Type': 'application/json', 'Retry-After': '1' })
      res.end(JSON.stringify({ success: false, error: 'Renderer is busy' }))
      return
    }
    renderRequestActive = true
    let body = ''
    let bodyBytes = 0
    let rejected = false
    req.on('data', (c: Buffer) => {
      bodyBytes += c.length
      if (bodyBytes > MAX_RENDER_REQUEST_BYTES) {
        rejected = true
        res.writeHead(413, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ success: false, error: 'Render request is too large' }))
        req.destroy()
        renderRequestActive = false
        return
      }
      body += c.toString('utf8')
    })
    req.on('end', async () => {
      if (rejected) return
      try {
        const payload = JSON.parse(body) as {
          xml?: string
          code?: string
          format?: 'pdf' | 'png' | 'svg'
        }
        let buf: Buffer
        if (route === '/mermaid-export') {
          if (!payload.code) throw new Error('Mermaid code is required')
          buf = await exportMermaidCode(payload.code, payload.format || 'svg')
        } else {
          if (!payload.xml) throw new Error('Draw.io XML is required')
          buf = await exportDrawioXml(payload.xml, payload.format || 'pdf')
        }
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({
          success: true,
          format: payload.format || (route === '/mermaid-export' ? 'svg' : 'pdf'),
          data: buf.toString('base64'),
        }))
      } catch (err: any) {
        res.writeHead(500, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ success: false, error: err.message }))
      } finally {
        renderRequestActive = false
      }
    })
    req.on('error', () => { renderRequestActive = false })
  })

  server.listen(port, '127.0.0.1', () => {
    // Keep launcher output ASCII-only so Windows consoles with a legacy code
    // page do not render the arrow as mojibake (for example, "鈫?").
    console.log(`[Merak] Draw.io export endpoint -> http://127.0.0.1:${port}/drawio-export`)
    console.log('[Merak] Mermaid export endpoint -> http://127.0.0.1:' + port + '/mermaid-export')
  })
  server.on('error', (err) => {
    console.warn('[Merak] Draw.io HTTP API failed to start:', err.message)
  })
}
