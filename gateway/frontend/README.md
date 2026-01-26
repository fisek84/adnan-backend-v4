# Adnan.AI Gateway Frontend (Vite + React)

This frontend now includes a minimal, production-safe PWA setup (installable on Android; “Add to Home Screen” on iOS) without changing any backend/API flows.

## PWA Features

- Installable (`manifest.webmanifest` + icons)
- Standalone mode (`display: standalone`)
- Minimal offline fallback (`/offline.html`) served **only** for navigations when offline
- Service worker caching is **static-assets only** (SWR). **No caching** for `/api/*` or auth-like routes.

## Local development

```bash
npm install
npm run dev
```

By default, the service worker is **OFF** in dev.

To test service worker behavior locally in dev, you can opt-in:

```bash
# Windows PowerShell
$env:VITE_PWA_SW_ENABLED = "true"

npm run dev
```

(Recommendation: prefer production preview testing below to match real behavior.)

## Build + preview (production-like)

```bash
npm run build
npm run preview
```

Open the preview URL, then check:

- Chrome DevTools → Application → Manifest
- Chrome DevTools → Application → Service Workers

## PWA Smoke Test

Runs a minimal validation:
- `manifest.webmanifest` returns `200`
- `/offline.html` returns `200`
- `/service-worker.js` returns `200`
- `<head>` contains manifest link + required iOS meta

```bash
npm run test:pwa
```

If port `4173` is taken, set `PWA_TEST_PORT`.

## iOS Install (Add to Home Screen)

iOS does not show the Android-style install prompt.

1. Open the app in Safari
2. Tap Share
3. Tap “Add to Home Screen”

It should open in standalone mode with the app icon.

## Notes / Safety Guarantees

- Service worker is registered only when:
  - production build (`import.meta.env.PROD`), **or**
  - `VITE_PWA_SW_ENABLED === "true"`
- **Network-only** (never cached): `/api/*`, `/auth*`, `/login*`, `/logout*`, `/callback*`, websocket/SSE-like paths.
- Offline fallback is served **only** when `request.mode === "navigate"`.

## Asset files

- PWA manifest: `public/manifest.webmanifest`
- Service worker: `public/service-worker.js`
- Offline page: `public/offline.html`
- Icons: `public/icon-*.png`, `public/apple-touch-icon.png`, `public/favicon-*.png`

To regenerate icons (solid-color placeholders, no external deps):

```bash
npm run gen:pwa-icons
```
