import mermaid from 'mermaid'

type MermaidTheme = 'default' | 'neutral' | 'dark' | 'forest' | 'base'

declare global {
  interface Window {
    __merakRenderMermaid: (code: string, theme?: MermaidTheme) => Promise<string>
  }
}

let renderQueue: Promise<unknown> = Promise.resolve()

window.__merakRenderMermaid = (code: string, theme: MermaidTheme = 'neutral') => {
  const render = async () => {
    mermaid.initialize({
      startOnLoad: false,
      theme,
      securityLevel: 'strict',
      fontFamily: 'Inter, "Segoe UI", Arial, sans-serif',
      flowchart: {
        htmlLabels: true,
        curve: 'basis',
        useMaxWidth: false,
      },
    })
    const id = `merak-mermaid-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const { svg } = await mermaid.render(id, code)
    return svg
  }

  const result = renderQueue.then(render, render)
  renderQueue = result.then(() => undefined, () => undefined)
  return result
}
