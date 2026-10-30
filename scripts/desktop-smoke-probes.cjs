/** Browser-side checks that never submit chat messages or start a workflow. */
async function probeDesktop() {
  const base = 'http://127.0.0.1:8011'
  async function pingSocket(route = '/ws/workflow') {
    return new Promise(resolve => {
      const socket = new WebSocket(base.replace('http', 'ws') + route)
      const finish = result => { clearTimeout(timer); socket.close(); resolve(result) }
      const timer = setTimeout(() => finish('timeout'), 10000)
      socket.onopen = () => socket.send(JSON.stringify({ type: 'ping' }))
      socket.onmessage = event => finish(JSON.parse(event.data).type)
      socket.onerror = () => finish('error')
    })
  }
  const pings = [await pingSocket(), await pingSocket()]
  const chatPing = await pingSocket('/api/chat/ws')
  const childDenied = await new Promise(resolve => {
    const frame = document.createElement('iframe')
    const finish = value => {
      clearTimeout(timer); window.removeEventListener('message', receive); frame.remove(); resolve(value)
    }
    const receive = event => {
      if (event.source === frame.contentWindow && event.data?.probe === 'merak-smoke') finish(event.data.denied)
    }
    const timer = setTimeout(() => finish(false), 10000)
    window.addEventListener('message', receive)
    frame.srcdoc = `<script>const ws=new WebSocket('ws://127.0.0.1:8011/ws/workflow');
      ws.onopen=()=>{ws.close();parent.postMessage({probe:'merak-smoke',denied:false},'*')};
      ws.onerror=()=>{ws.close();parent.postMessage({probe:'merak-smoke',denied:true},'*')};</script>`
    document.body.appendChild(frame)
  })
  const settings = await (await fetch(base + '/api/settings/models')).json()
  settings.openai_model = 'desktop-storage-fixture'
  const saved = await fetch(base + '/api/settings/models', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings),
  })
  const health = await (await fetch(base + '/api/health')).json()
  return { pings, chatPing, childDenied, settingsStatus: saved.status, version: health.version, title: document.title }
}

module.exports = { probeDesktop }
