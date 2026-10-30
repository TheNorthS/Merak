# Development startup readiness

Vite's listener-ready message is not proof that application dependencies have
been transformed or that React has rendered the interface. Electron document
load completion is also not proof of a usable application.

The startup path now has three independent boundaries:

1. Vite scans only the SPA `index.html` and warms four initial shell entries.
   Its watcher prunes backend/skill/docs and generated test/bytecode trees rather
   than traversing the repository's hundreds of temporary fixture directories.
   Frontend/shared/public/resources and config HMR remain watched. Port selection,
   optimizer cache defaults and API/WebSocket proxies remain unchanged.
2. Optional Monaco and Markdown engines load only when their editor is mounted.
   The welcome screen does not import them eagerly. Workflow state is still
   mounted as before; hiding the workflow is not used to stop its controller.
3. React reports its first successful application commit through one fixed
   preload channel. Each Electron navigation has a fresh runtime nonce; main
   accepts only the expected window, main frame, exact URL and nonce.

At 30 seconds the loader reports a soft wait and preserves the current page.
A mounted application can finish startup even if document loading remains
pending. The renderer wait has a 120-second hard boundary; navigation failures
still retry sequentially and close cancels requests, timers and listeners.
Bootstrap/render failures retain a visible diagnostic instead of blind reloads.
An HTML response, document load event or empty React root never grants readiness.

Verification:

```text
npm run test:dev-startup
npm run typecheck
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json
npm run lint
npm run check:standards
npm run build:web
```

Startup tests use fake requests, windows and IPC plus isolated source/config
loading. They do not start Electron, listeners or workflows. Cold-start timing
still needs a separate real launch measurement; do not infer a guaranteed
startup duration from Vite's listener timing.
