/** Apply the same saved theme before the startup screen and the workspace mount. */
export function applyTheme(theme: string): void {
  document.documentElement.classList.toggle('light', theme === 'light')
}

export function applyStoredTheme(): void {
  try { applyTheme(localStorage.getItem('merak-ide:theme') || 'dark') }
  catch { applyTheme('dark') }
}
