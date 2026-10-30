let renderQueue: Promise<unknown> = Promise.resolve()

export function renderMermaidSvg(code: string): Promise<string> {
  const render = async () => {
    const { default: mermaid } = await import('mermaid')
    mermaid.initialize({
      startOnLoad: false,
      theme: 'neutral',
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
