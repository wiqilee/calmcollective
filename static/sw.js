/* static/sw.js
 * Safe offline support for CalmCollective
 * Key points:
 *  - Never cache HTML pages (prevents stale CSRF tokens)
 *  - Pass all non-GET (e.g., POST form submits) straight to the network
 *  - Network-first for /api/entries (fresh when online, fallback to cache)
 *  - Cache-first for static assets (CSS/JS/images) and CDN Chart.js
 */

const VERSION = 'v2';                 // bump this when you change the SW
const STATIC_CACHE = `static-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;
const CDN_CACHE = `cdn-${VERSION}`;

// Precache only static assets (no HTML pages)
const STATIC_ASSETS = [
  '/static/css/styles.css',
  '/static/js/app.js',
  // add icons if you have them, e.g.:
  // '/static/icons/icon-192.png',
  // '/static/icons/icon-512.png',
];

// Optional offline fallback page (served only when navigation fails)
const OFFLINE_HTML = `
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Offline — CalmCollective</title>
<style>
  body{margin:0;background:#0b0e11;color:#eef2f7;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial,sans-serif}
  .wrap{max-width:720px;margin:0 auto;padding:24px}
  .card{background:#12161b;border:1px solid #1f2733;border-radius:16px;padding:18px}
  a{color:#8fd3ff}
</style>
<div class="wrap">
  <div class="card">
    <h2>You're offline</h2>
    <p>Your journal is available offline for writing. Some features may be limited until you're back online.</p>
    <p>Try again from <a href="/">Home</a> or <a href="/entries">Entries</a>.</p>
  </div>
</div>
`;

// Helper: network request with timeout (used for API network-first)
function fetchWithTimeout(req, ms = 3500) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  return fetch(req, { signal: controller.signal })
    .finally(() => clearTimeout(id));
}

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((k) => ![STATIC_CACHE, RUNTIME_CACHE, CDN_CACHE].includes(k))
        .map((k) => caches.delete(k))
    );
    // Clean up any old "pages-*" caches from previous versions
    await Promise.all(
      keys
        .filter((k) => k.startsWith('pages-'))
        .map((k) => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 1) Never intercept non-GET (e.g., form POST) — let them hit Flask directly
  if (request.method !== 'GET') return;

  const isSameOrigin = url.origin === self.location.origin;
  const isCDNChart = url.href.startsWith('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/');

  // 2) Navigations (HTML pages): network-only (no caching) with offline fallback
  const isNavigation =
    request.mode === 'navigate' ||
    (request.headers.get('accept') || '').includes('text/html');

  if (isNavigation) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
      )
    );
    return;
  }

  // 3) API: network-first -> cache on success -> fallback to cached (if any)
  if (isSameOrigin && url.pathname.startsWith('/api/entries')) {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME_CACHE);
      try {
        const res = await fetchWithTimeout(request, 3500);
        if (res && res.ok) cache.put(request, res.clone());
        return res;
      } catch {
        const cached = await cache.match(request);
        return (
          cached ||
          new Response('[]', { headers: { 'Content-Type': 'application/json' } })
        );
      }
    })());
    return;
  }

  // 4) Static assets (local) and CDN Chart.js: cache-first
  if ((isSameOrigin && url.pathname.startsWith('/static/')) || isCDNChart) {
    event.respondWith((async () => {
      const cacheName = isCDNChart ? CDN_CACHE : STATIC_CACHE;
      const cache = await caches.open(cacheName);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const res = await fetch(request);
        if (res && (res.ok || res.type === 'opaque')) cache.put(request, res.clone());
        return res;
      } catch {
        return cached || new Response('', { status: 504 });
      }
    })());
    return;
  }

  // 5) Default: runtime cache-first as a mild optimization for other GETs
  event.respondWith((async () => {
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match(request);
    if (cached) return cached;
    try {
      const res = await fetch(request);
      if (res && res.ok) cache.put(request, res.clone());
      return res;
    } catch {
      return cached || new Response('', { status: 504 });
    }
  })());
});
