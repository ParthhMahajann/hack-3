const CACHE = 'asha-saheli-v1';
const SHELL = [
  './', './login.html', './dashboard.html',
  './new-patient.html', './visit.html',
  './incentives.html', './officer.html',
  './shared.css'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => null);
      return cached || network;
    })
  );
});

// Background sync queue
self.addEventListener('sync', e => {
  if (e.tag === 'sync-visits') {
    e.waitUntil(syncPendingVisits());
  }
});

async function syncPendingVisits() {
  // In production: read from IndexedDB, POST to /visits/, mark as synced
  console.log('[SW] Background sync: visits');
}
