#!/usr/bin/env node
'use strict'

const fs = require('fs')
const rough = require('roughjs')

const [, , sourcePath, outputPath] = process.argv
if (!sourcePath || !outputPath) {
  process.stderr.write('Usage: node render-excalidraw.cjs scene.excalidraw output.svg\n')
  process.exit(2)
}

const scene = JSON.parse(fs.readFileSync(sourcePath, 'utf8'))
const elements = Array.isArray(scene.elements) ? scene.elements.filter(item => !item.isDeleted) : []
if (!elements.length) {
  throw new Error('Scene contains no visible elements')
}

const generator = rough.generator()
const connectorTypes = new Set(['arrow', 'line'])
const shapeTypes = new Set(['rectangle', 'ellipse', 'diamond', 'frame'])

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function bounds(element) {
  const x = Number(element.x || 0)
  const y = Number(element.y || 0)
  if (connectorTypes.has(element.type)) {
    const points = element.points || [[0, 0]]
    const xs = points.map(point => x + Number(point[0] || 0))
    const ys = points.map(point => y + Number(point[1] || 0))
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  }
  return [x, y, x + Number(element.width || 0), y + Number(element.height || 0)]
}

const boxes = elements.map(bounds)
const minX = Math.min(...boxes.map(item => item[0])) - 70
const minY = Math.min(...boxes.map(item => item[1])) - 70
const maxX = Math.max(...boxes.map(item => item[2])) + 70
const maxY = Math.max(...boxes.map(item => item[3])) + 70
const width = Math.max(1, maxX - minX)
const height = Math.max(1, maxY - minY)

function options(element) {
  const strokeStyle = String(element.strokeStyle || 'solid')
  return {
    seed: Number(element.seed || 1),
    stroke: String(element.strokeColor || '#334155'),
    strokeWidth: Number(element.strokeWidth || 2),
    roughness: Number(element.roughness ?? 0.9),
    bowing: Math.max(0.25, Number(element.roughness ?? 0.9) * 0.65),
    fill: String(element.backgroundColor || 'transparent'),
    fillStyle: String(element.fillStyle || 'solid'),
    strokeLineDash: strokeStyle === 'dashed' ? [9, 7] : strokeStyle === 'dotted' ? [2, 6] : undefined,
    preserveVertices: true,
  }
}

function drawable(drawableValue, opacity = 100) {
  return generator.toPaths(drawableValue).map(path => {
    const fill = path.fill && path.fill !== 'none' && path.fill !== 'transparent' ? path.fill : 'none'
    const stroke = path.stroke && path.stroke !== 'transparent' ? path.stroke : 'none'
    return `<path d="${esc(path.d)}" fill="${esc(fill)}" stroke="${esc(stroke)}" stroke-width="${Number(path.strokeWidth || 0)}" opacity="${Number(opacity) / 100}" stroke-linecap="round" stroke-linejoin="round"/>`
  }).join('')
}

function renderShape(element) {
  const x = Number(element.x || 0)
  const y = Number(element.y || 0)
  const w = Number(element.width || 0)
  const h = Number(element.height || 0)
  const opts = options(element)
  let value
  if (element.type === 'ellipse') {
    value = generator.ellipse(x + w / 2, y + h / 2, w, h, opts)
  } else if (element.type === 'diamond') {
    value = generator.polygon(
      [[x + w / 2, y], [x + w, y + h / 2], [x + w / 2, y + h], [x, y + h / 2]],
      opts,
    )
  } else {
    value = generator.rectangle(x, y, w, h, opts)
  }
  return drawable(value, element.opacity)
}

function renderText(element) {
  const x = Number(element.x || 0)
  const y = Number(element.y || 0)
  const width = Number(element.width || 0)
  const height = Number(element.height || 0)
  const fontSize = Number(element.fontSize || 18)
  const lineHeight = Number(element.lineHeight || 1.25) * fontSize
  const lines = String(element.text || '').split('\n')
  const totalHeight = Math.max(lineHeight, lines.length * lineHeight)
  const vertical = String(element.verticalAlign || 'middle')
  const startY = vertical === 'top' ? y + fontSize : vertical === 'bottom'
    ? y + height - totalHeight + fontSize
    : y + (height - totalHeight) / 2 + fontSize
  const align = String(element.textAlign || 'left')
  const anchor = align === 'center' ? 'middle' : align === 'right' ? 'end' : 'start'
  const tx = align === 'center' ? x + width / 2 : align === 'right' ? x + width : x
  const color = String(element.strokeColor || '#0f172a')
  const spans = lines.map((line, index) =>
    `<tspan x="${tx}" y="${startY + index * lineHeight}">${esc(line)}</tspan>`,
  ).join('')
  return `<text font-family="Arial, Helvetica, sans-serif" font-size="${fontSize}" font-weight="${element.fontStyle === 1 ? 600 : 400}" text-anchor="${anchor}" fill="${esc(color)}" opacity="${Number(element.opacity || 100) / 100}">${spans}</text>`
}

function renderConnector(element) {
  const x = Number(element.x || 0)
  const y = Number(element.y || 0)
  const points = (element.points || []).map(point => [x + Number(point[0] || 0), y + Number(point[1] || 0)])
  if (points.length < 2) return ''
  const opts = { ...options(element), fill: 'none' }
  const body = drawable(
    element.roundness ? generator.curve(points, opts) : generator.linearPath(points, opts),
    element.opacity,
  )
  if (!element.endArrowhead) return body
  const end = points[points.length - 1]
  const previous = points[points.length - 2]
  const angle = Math.atan2(end[1] - previous[1], end[0] - previous[0])
  const length = 13 + Number(element.strokeWidth || 2) * 2
  const spread = Math.PI / 7
  const left = [
    end[0] - Math.cos(angle - spread) * length,
    end[1] - Math.sin(angle - spread) * length,
  ]
  const right = [
    end[0] - Math.cos(angle + spread) * length,
    end[1] - Math.sin(angle + spread) * length,
  ]
  return body
    + drawable(generator.line(end[0], end[1], left[0], left[1], opts), element.opacity)
    + drawable(generator.line(end[0], end[1], right[0], right[1], opts), element.opacity)
}

const backgrounds = elements.filter(element =>
  element.type === 'frame'
  || ['zone', 'background', 'frame'].includes(String(element.customData?.role || '').toLowerCase()),
)
const connectors = elements.filter(element => connectorTypes.has(element.type))
const shapes = elements.filter(element =>
  shapeTypes.has(element.type) && !backgrounds.includes(element),
)
const texts = elements.filter(element => element.type === 'text')
const ordered = [...backgrounds, ...connectors, ...shapes, ...texts]

const content = ordered.map(element => {
  if (element.type === 'text') return renderText(element)
  if (connectorTypes.has(element.type)) return renderConnector(element)
  return renderShape(element)
}).join('')

const background = String(scene.appState?.viewBackgroundColor || '#ffffff')
const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${Math.round(width)}" height="${Math.round(height)}" viewBox="${minX} ${minY} ${width} ${height}">
  <rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="${esc(background)}"/>
  ${content}
</svg>
`
fs.mkdirSync(require('path').dirname(outputPath), { recursive: true })
fs.writeFileSync(outputPath, svg, 'utf8')
process.stdout.write(JSON.stringify({ width, height, elements: elements.length }))
