/**
 * Service Worker for the World Cup 2026 Predictor PWA.
 *
 * IMPORTANT: This site shows LIVE data (scores, forecasts) that must always be
 * fresh. So this worker deliberately does NOT cache anything — every request
 * goes straight to the network. Its only job is to exist, which is what makes
 * the site installable as a PWA on Android.
 *
 * DO NOT add caching here without implementing cache-busting/versioning, or the
 * app will serve users a stale copy of the site (old scores, old forecast) even
 * after you deploy updates. For a live site, network-first with no cache is correct.
 */

self.addEventListener('install', (e) => {
  // activate immediately, don't wait for old workers
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  // safety net: delete any caches a previous/accidental version may have created
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  // always go to the network — never serve cached (possibly stale) content
  e.respondWith(fetch(e.request));
});
