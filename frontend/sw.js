// RepoScroller Service Worker - Network-First Strategy with Offline Cache Fallback
const CACHE_NAME = 'reposcroller-cache-v2';
const STATIC_ASSETS = [
  './',
  'index.html',
  'style.css',
  'manifest.json',
  'public/icon-192.png',
  'public/icon-512.png',
  'public/favicon.ico'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('Pre-cache error (non-fatal):', err);
      });
    })
  );
  // Activate immediately without waiting for existing tabs to close
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        // Purge any older cache versions (including legacy v1)
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  // Immediately take control of all active clients
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Pass through non-GET and API calls directly to the network
  if (event.request.method !== 'GET' || event.request.url.includes('/api/')) {
    return;
  }

  // Network-First: Always fetch the fresh asset from server first
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        // If the server returns a successful response, update the cache in the background
        if (
          networkResponse &&
          networkResponse.status === 200 &&
          networkResponse.type === 'basic'
        ) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        // Network unavailable (offline) -> fall back to cached copy
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // If offline navigation request, fallback to cached index.html
          if (event.request.mode === 'navigate' || event.request.destination === 'document') {
            return caches.match('index.html') || caches.match('./');
          }
          return new Response('Offline: Network unavailable and asset not cached', {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'text/plain' }
          });
        });
      })
  );
});
