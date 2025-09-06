/* static/sw.js
 * Offline support for CalmCollective
 * Strategy:
 *  - cache-first for static assets (CSS/JS/fonts/images, CDN Chart.js)
 *  - network-first for /api/entries (fresh when online, fallback to cache when offline)
 *  - pages (/, /entries, /export) cached for offline navigation
 */

const VERSION = 'v1';
const STATIC_CACHE = `static-${VERSION}`;
const PAGES_CACHE  = `pages-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;
const CDN_CACHE = `cdn-${VERSION}`;

// Precache core pages + local assets (add more if needed)
const PRECACHE_URLS = [
  '/',               // home
  '/entries',        // entries page
  '/export',         // export page

  // Local assets
  '/static/css/styles.css',
  '/static/js/app.js',

  // CDN assets (opaque, but cacheable)
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'
];

// Simple offline fallback page (inline string response)
const OFFLINE_HTML = `
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Offline — CalmCollective</title>
<style>
  body{margin:0;background:#0b0e11;color:#eef2f7;font-family:system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif;}
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

// Utility: network request with timeout (for network-first)
function fetchWithTimeout(req, ms = 3500) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  return fetch(req, { signal: controller.signal })
    .finally(() => clearTimeout(id));
}

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    (async () => {
      const staticCache = await caches.open(STATIC_CACHE);
      await staticCache.addAll(PRECACHE_URLS.map(u => new Request(u, { credentials: 'same-origin' })));
    })()
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(k => ![STATIC_CACHE, PAGES_CACHE, RUNTIME_CACHE, CDN_CACHE].includes(k))
          .map(k => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;

  // Only handle same-origin + CDN GETs
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  const isSameOrigin = url.origin === self.location.origin;
  const isCDNChart = url.href.startsWith('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/');

  // Network-first for API to keep data fresh
  if (isSameOrigin && url.pathname.startsWith('/api/entries')) {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME_CACHE);
      try {
        const res = await fetchWithTimeout(request, 3500);
        if (res && res.ok) cache.put(request, res.clone());
        return res;
      } catch {
        const cached = await cache.match(request);
        // fallback to empty list if nothing cached
        return cached || new Response('[]', { headers: { 'Content-Type': 'application/json' } });
      }
    })());
    return;
  }

  // For navigations (pages), try cache first, then network, then offline fallback
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      const cache = await caches.open(PAGES_CACHE);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const res = await fetch(request);
        if (res && res.ok) cache.put(request, res.clone());
        return res;
      } catch {
        return new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      }
    })());
    return;
  }

  // Cache-first for static assets (local) and CDN Chart.js
  if ((isSameOrigin && url.pathname.startsWith('/static/')) || isCDNChart) {
    event.respondWith((async () => {
      const cacheName = isCDNChart ? CDN_CACHE : STATIC_CACHE;
      const cache = await caches.open(cacheName);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const res = await fetch(request);
        // Cache opaque CDN responses as well
        if (res && (res.ok || res.type === 'opaque')) cache.put(request, res.clone());
        return res;
      } catch {
        return cached || new Response('', { status: 504 });
      }
    })());
    return;
  }

  // Default: try cache, then network
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
