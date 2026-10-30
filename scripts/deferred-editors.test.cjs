const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const React = require('react')
const { renderToString } = require('react-dom/server')
const ts = require('typescript')

const editorDirectory = path.join(__dirname, '../src/components/editor')

function compileEditors() {
  const source = readFileSync(path.join(editorDirectory, 'DeferredEditors.tsx'), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText
  const imports = []
  const rendered = []
  const controlledRequire = name => {
    if (name === '@monaco-editor/react' || name === './MarkdownEditor') {
      imports.push(name)
      const component = props => {
        rendered.push({ name, props })
        return React.createElement('div', null, 'Editor ready')
      }
      return name === './MarkdownEditor'
        ? { MarkdownEditor: component }
        : { default: component }
    }
    return require(name)
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(controlledRequire, module, module.exports)
  return { ...module.exports, imports, rendered }
}

async function resolveImport() {
  for (let index = 0; index < 4; index++) await Promise.resolve()
}

test('CodeEditor keeps optional engines out of its static import graph', () => {
  const source = readFileSync(path.join(editorDirectory, 'CodeEditor.tsx'), 'utf8')
  const syntax = ts.createSourceFile('CodeEditor.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const imports = syntax.statements.filter(ts.isImportDeclaration)
    .map(statement => statement.moduleSpecifier.text)
  assert.ok(imports.includes('./DeferredEditors'))
  assert.ok(!imports.includes('@monaco-editor/react'))
  assert.ok(!imports.includes('./MarkdownEditor'))
})

test('initializing deferred wrappers does not load either editor engine', () => {
  const editors = compileEditors()
  assert.deepEqual(editors.imports, [])
})

test('code editor loads only on mount, shows loading state, and preserves all props', async () => {
  const editors = compileEditors()
  const onMount = () => {}
  const onChange = () => {}
  const beforeMount = () => {}
  const props = { value: 'source', language: 'python', theme: 'merak-dark', onMount, onChange, beforeMount }
  const first = renderToString(React.createElement(editors.DeferredCodeEditor, props))
  assert.match(first, /role="status"/)
  await resolveImport()
  assert.deepEqual(editors.imports, ['@monaco-editor/react'])
  const second = renderToString(React.createElement(editors.DeferredCodeEditor, props))
  assert.match(second, /Editor ready/)
  assert.deepEqual(editors.rendered[0].props, props)
  renderToString(React.createElement(editors.DeferredCodeEditor, props))
  assert.equal(editors.imports.length, 1)
})

test('Markdown loads independently and preserves file, clipboard, and edit callbacks', async () => {
  const editors = compileEditors()
  const props = {
    filePath: 'notes.md', content: '# Title', isDirty: true, fontSize: 14, editorTheme: 'merak-light',
    onChange: () => {}, readClipboard: () => 'clipboard',
  }
  const first = renderToString(React.createElement(editors.DeferredMarkdownEditor, props))
  assert.match(first, /role="status"/)
  await resolveImport()
  assert.deepEqual(editors.imports, ['./MarkdownEditor'])
  assert.match(renderToString(React.createElement(editors.DeferredMarkdownEditor, props)), /Editor ready/)
  assert.deepEqual(editors.rendered[0].props, props)
})
