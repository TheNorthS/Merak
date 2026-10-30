import type { Monaco } from '@monaco-editor/react'

export function configureMerakMonaco(monaco: Monaco) {
  monaco.editor.defineTheme('merak-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6c7086', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'cba6f7' },
      { token: 'string', foreground: 'a6e3a1' },
      { token: 'number', foreground: 'fab387' },
      { token: 'type', foreground: '89dceb' },
      { token: 'function', foreground: '89b4fa' },
      { token: 'variable', foreground: 'cdd6f4' },
    ],
    colors: {
      'editor.background': '#1e1e2e',
      'editor.foreground': '#cdd6f4',
      'editor.lineHighlightBackground': '#2a2a3c',
      'editor.selectionBackground': '#45475a80',
      'editorCursor.foreground': '#f5e0dc',
      'editorLineNumber.foreground': '#6c7086',
      'editorLineNumber.activeForeground': '#bac2de',
      'editor.inactiveSelectionBackground': '#45475a40',
      'editorIndentGuide.background1': '#313147',
      'editorIndentGuide.activeBackground1': '#45475a',
    },
  })

  monaco.editor.defineTheme('merak-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '8c8fa1', fontStyle: 'italic' },
      { token: 'keyword', foreground: '8839ef' },
      { token: 'string', foreground: '40a02b' },
      { token: 'number', foreground: 'fe640b' },
      { token: 'type', foreground: '04a5e5' },
      { token: 'function', foreground: '1e66f5' },
      { token: 'variable', foreground: '4c4f69' },
    ],
    colors: {
      'editor.background': '#eff1f5',
      'editor.foreground': '#4c4f69',
      'editor.lineHighlightBackground': '#e6e9ef',
      'editor.selectionBackground': '#acb0be80',
      'editorCursor.foreground': '#dc8a78',
      'editorLineNumber.foreground': '#8c8fa1',
      'editorLineNumber.activeForeground': '#4c4f69',
      'editor.inactiveSelectionBackground': '#acb0be40',
      'editorIndentGuide.background1': '#ccd0da',
      'editorIndentGuide.activeBackground1': '#acb0be',
    },
  })

  if (!monaco.languages.getLanguages().some(language => language.id === 'latex')) {
    monaco.languages.register({ id: 'latex' })
  }
  monaco.languages.setMonarchTokensProvider('latex', {
    tokenizer: {
      root: [
        [/\\[a-zA-Z]+/, 'keyword'],
        [/\{/, 'delimiter.curly'],
        [/\}/, 'delimiter.curly'],
        [/\[/, 'delimiter.square'],
        [/\]/, 'delimiter.square'],
        [/%.*$/, 'comment'],
        [/\$[^$]*\$/, 'string'],
      ],
    },
  })
}
