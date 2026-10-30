const { app, BrowserWindow } = require('electron')
const fs = require('fs')
const path = require('path')

function viewport(svg) {
  const match = svg.match(/viewBox=["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)["']/i)
  const sourceWidth = match ? Number(match[1]) : 1200
  const sourceHeight = match ? Number(match[2]) : 800
  const width = 1600
  const ratio = Number.isFinite(sourceHeight / sourceWidth) ? sourceHeight / sourceWidth : 2 / 3
  return { width, height: Math.max(320, Math.min(2000, Math.round(width * ratio))) }
}

async function render() {
  const outputPath = path.resolve(process.argv[2] || '')
  const rendererPath = path.resolve(process.argv[3] || '')
  const code = fs.readFileSync(0, 'utf8')
  if (!outputPath || !code.trim()) throw new Error('Output path and Mermaid source are required')
  if (!fs.existsSync(rendererPath)) throw new Error(`Mermaid renderer is missing: ${rendererPath}`)
  fs.mkdirSync(path.dirname(outputPath), { recursive: true })

  const win = new BrowserWindow({
    show: false,
    width: 1600,
    height: 1000,
    useContentSize: true,
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: false,
      sandbox: false,
      webSecurity: false,
    },
  })
  try {
    await win.loadURL('data:text/html;charset=utf-8,<html><body></body></html>')
    await win.webContents.executeJavaScript(fs.readFileSync(rendererPath, 'utf8'))
    const svg = await win.webContents.executeJavaScript(
      `window.__merakRenderMermaid(${JSON.stringify(code)}, 'neutral')`,
    )
    if (!svg || typeof svg !== 'string') throw new Error('Mermaid renderer returned an empty SVG')
    const format = path.extname(outputPath).slice(1).toLowerCase()
    if (format === 'svg') {
      fs.writeFileSync(outputPath, svg, 'utf8')
      return
    }

    const size = viewport(svg)
    win.setContentSize(size.width, size.height)
    await win.webContents.executeJavaScript(`
      document.documentElement.style.cssText = 'background:#fff;overflow:hidden';
      document.body.style.cssText = 'margin:0;background:#fff;overflow:hidden;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center';
      document.body.innerHTML = ${JSON.stringify(svg)};
      const rendered = document.body.querySelector('svg');
      if (rendered) {
        rendered.removeAttribute('width'); rendered.removeAttribute('height');
        rendered.style.cssText = 'width:100%;height:100%;max-width:none;background:#fff';
      }
    `)
    await new Promise((resolve) => setTimeout(resolve, 150))
    if (format === 'pdf') {
      const pdf = await win.webContents.printToPDF({ printBackground: true })
      if (!pdf.length) throw new Error('Mermaid PDF export was empty')
      fs.writeFileSync(outputPath, pdf)
      return
    }
    if (format === 'png') {
      const png = (await win.webContents.capturePage()).toPNG()
      if (!png.length) throw new Error('Mermaid PNG export was empty')
      fs.writeFileSync(outputPath, png)
      return
    }
    throw new Error(`Unsupported Mermaid output format: ${format}`)
  } finally {
    win.destroy()
  }
}

app.commandLine.appendSwitch('disable-gpu')
app.commandLine.appendSwitch('disable-software-rasterizer')
app.whenReady()
  .then(render)
  .then(() => app.exit(0))
  .catch((error) => {
    process.stderr.write(`${error && error.stack ? error.stack : error}\n`)
    app.exit(1)
  })
