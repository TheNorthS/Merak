import { lazy, Suspense, type ComponentProps } from 'react'
import type { EditorProps } from '@monaco-editor/react'

type MarkdownEditorProps = ComponentProps<typeof import('./MarkdownEditor').MarkdownEditor>

// Keep optional editor engines outside the welcome screen's startup import graph.
const MonacoEditor = lazy(() => import('@monaco-editor/react'))
const MarkdownEditor = lazy(() => import('./MarkdownEditor').then(module => ({
  default: module.MarkdownEditor,
})))

function EditorLoading() {
  return (
    <div role="status" className="flex h-full items-center justify-center text-xs text-muted-foreground">
      正在加载编辑器…
    </div>
  )
}

export function DeferredCodeEditor(props: EditorProps) {
  return (
    <Suspense fallback={<EditorLoading />}>
      <MonacoEditor {...props} />
    </Suspense>
  )
}

export function DeferredMarkdownEditor(props: MarkdownEditorProps) {
  return (
    <Suspense fallback={<EditorLoading />}>
      <MarkdownEditor {...props} />
    </Suspense>
  )
}
