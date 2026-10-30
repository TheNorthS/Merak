/** Include browser session cookies only for this installation's API origin. */
export function installApiSession(base: string): void {
  const original = window.fetch.bind(window)
  const origin = new URL(base, window.location.href).origin
  window.fetch = (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
    if (url.origin !== origin) return original(input, init)
    return original(input, { ...init, credentials: 'include' }).then(response => {
      if (response.status === 401) window.dispatchEvent(new Event('merak-ide:authentication-required'))
      return response
    })
  }
}
