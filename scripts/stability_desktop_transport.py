"""Drive only the isolated packaged renderer through its debugging connection."""

from contextlib import asynccontextmanager
import asyncio
import json
import secrets

from websockets.asyncio.client import connect


class DesktopTransport:
    def __init__(self, address: str):
        self.address = address

    async def evaluate(self, expression: str, timeout: float = 180):
        async with connect(self.address, max_size=32 * 1024 * 1024) as socket:
            await socket.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": expression, "awaitPromise": True, "returnByValue": True,
            }}))
            async with asyncio.timeout(timeout):
                async for raw in socket:
                    message = json.loads(raw)
                    if message.get("id") != 1:
                        continue
                    result = message.get("result", {})
                    if message.get("error") or result.get("exceptionDetails"):
                        # Expressions can contain credentials. Never log the request or exception object.
                        raise RuntimeError("Packaged renderer operation failed; inspect the operation receipt")
                    return result.get("result", {}).get("value")
        raise RuntimeError("Packaged renderer disconnected")

    async def request(self, method: str, route: str, **kwargs):
        request = {"method": method, "route": route, "body": kwargs.get("json"),
                   "params": kwargs.get("params", {}), "timeout": kwargs.get("timeout", 180) * 1000}
        encoded = json.dumps(request)
        return await self.evaluate("""(async () => {
            const request = REQUEST;
            const port = await window.merakIDE.backend.getPort();
            const url = new URL(request.route, `http://127.0.0.1:${port}`);
            for (const [key, value] of Object.entries(request.params)) url.searchParams.set(key, value);
            const response = await fetch(url, {method: request.method,
                headers: {'Content-Type': 'application/json'},
                body: request.body === undefined || request.body === null ? undefined : JSON.stringify(request.body),
                signal: AbortSignal.timeout(request.timeout)});
            return {status: response.status, text: await response.text()};
        })()""".replace("REQUEST", encoded), timeout=kwargs.get("timeout", 180) + 10)

    @asynccontextmanager
    async def websocket(self, route: str):
        key = "stabilitySocket" + secrets.token_hex(8)
        await self.evaluate("""(async () => {
            const port = await window.merakIDE.backend.getPort();
            const socket = new WebSocket(`ws://127.0.0.1:${port}` + ROUTE);
            const state = {socket, messages: [], waiters: [], closed: false};
            window[KEY] = state;
            socket.onmessage = event => {
                const waiter = state.waiters.shift();
                if (waiter) waiter(event.data); else state.messages.push(event.data);
            };
            socket.onclose = () => {state.closed = true; for (const done of state.waiters.splice(0)) done(null)};
            await new Promise((resolve, reject) => {
                socket.onopen = resolve;
                socket.onerror = () => reject(new Error('Socket connection failed'));
            });
            return true;
        })()""".replace("ROUTE", json.dumps(route)).replace("KEY", json.dumps(key)), timeout=20)
        try:
            yield DesktopSocket(self, key)
        finally:
            await self.evaluate("(() => { const state = window[KEY]; if (state) {state.socket.close(); delete window[KEY]} })()"
                                .replace("KEY", json.dumps(key)), timeout=10)


class DesktopSocket:
    def __init__(self, transport: DesktopTransport, key: str):
        self.transport, self.key = transport, key

    async def send(self, raw: str):
        await self.transport.evaluate("window[KEY].socket.send(MESSAGE)".replace("KEY", json.dumps(self.key))
                                      .replace("MESSAGE", json.dumps(raw)))

    async def recv(self) -> str:
        while True:
            result = await self.transport.evaluate("""(async () => {
                const state = window[KEY];
                if (!state || state.closed) return {closed: true};
                if (state.messages.length) return {message: state.messages.shift()};
                return await new Promise(resolve => {
                    const done = message => {clearTimeout(timer); resolve({message, closed: state.closed})};
                    const timer = setTimeout(() => {
                        const index = state.waiters.indexOf(done);
                        if (index >= 0) state.waiters.splice(index, 1);
                        resolve({timeout: true});
                    }, 20000);
                    state.waiters.push(done);
                });
            })()""".replace("KEY", json.dumps(self.key)), timeout=25)
            if result.get("closed"):
                raise RuntimeError("Packaged application's WebSocket closed")
            if "message" in result and result["message"] is not None:
                return result["message"]

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()
