/**
 * Service Worker — ASHA Saheli PWA
 * Strategy:
 *   App shell   → CacheFirst (never stale, always fast)
 *   API reads   → NetworkFirst with cache fallback
 *   API writes  → Background Sync queue (retry on connectivity)
 */

const CACHE_VERSION = "asha-saheli-v1";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const API_CACHE = `${CACHE_VERSION}-api`;
const SYNC_QUEUE_KEY = "sync-queue";

const SHELL_ASSETS = [
  "/app",
  "/static/css/app.css",
  "/static/js/db.js",
  "/static/js/sync.js",
  "/static/manifest.json",
];

// ── Install: cache app shell ────────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// ── Activate: purge old caches ──────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith("asha-saheli-") && k !== SHELL_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: route requests ───────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // App shell → CacheFirst
  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(cacheFirst(event.request, SHELL_CACHE));
    return;
  }

  // API GETs → NetworkFirst with cache fallback
  if (url.pathname.startsWith("/patients") || url.pathname.startsWith("/dashboard")) {
    if (event.request.method === "GET") {
      event.respondWith(networkFirst(event.request, API_CACHE));
      return;
    }
  }

  // Default: network only
  event.respondWith(fetch(event.request).catch(() => new Response("Offline", { status: 503 })));
});

// ── Background Sync ─────────────────────────────────────────────────────────
self.addEventListener("sync", (event) => {
  if (event.tag === "asha-sync") {
    event.waitUntil(flushSyncQueue());
  }
});

async function flushSyncQueue() {
  const db = await openSyncDB();
  const queue = await getAllFromStore(db, SYNC_QUEUE_KEY);
  if (!queue.length) return;

  // Sort by priority: purple → red → yellow → green
  const levelOrder = { purple: 0, red: 1, yellow: 2, green: 3 };
  queue.sort((a, b) => (levelOrder[a.risk_level] ?? 4) - (levelOrder[b.risk_level] ?? 4));

  const token = await getAuthToken();
  if (!token) return;

  try {
    const resp = await fetch("/sync/", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        device_id: await getDeviceId(),
        last_sync_ts: (await getLastSyncTs()) || 0,
        records: queue,
      }),
    });

    if (resp.ok) {
      const result = await resp.json();
      await clearSyncQueue(db);
      await setLastSyncTs(result.server_ts);
      // Merge server changes into local IndexedDB
      await mergeServerChanges(result.server_changes);
      // Notify open clients
      const clients = await self.clients.matchAll();
      clients.forEach((c) => c.postMessage({ type: "SYNC_COMPLETE", result }));
    }
  } catch (err) {
    console.warn("[SW] Sync failed, will retry:", err);
  }
}

// ── Cache helpers ────────────────────────────────────────────────────────────
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  const cache = await caches.open(cacheName);
  cache.put(request, response.clone());
  return response;
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    const cache = await caches.open(cacheName);
    cache.put(request, response.clone());
    return response;
  } catch {
    return caches.match(request) || new Response("[]", { headers: { "Content-Type": "application/json" } });
  }
}

// ── IndexedDB helpers ────────────────────────────────────────────────────────
function openSyncDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("asha-sync-db", 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(SYNC_QUEUE_KEY))
        db.createObjectStore(SYNC_QUEUE_KEY, { keyPath: "id" });
      if (!db.objectStoreNames.contains("meta"))
        db.createObjectStore("meta");
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = reject;
  });
}

function getAllFromStore(db, storeName) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const req = tx.objectStore(storeName).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = reject;
  });
}

function clearSyncQueue(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(SYNC_QUEUE_KEY, "readwrite");
    const req = tx.objectStore(SYNC_QUEUE_KEY).clear();
    req.onsuccess = resolve;
    req.onerror = reject;
  });
}

// NOTE: Service Workers do NOT have access to localStorage.
// Use IndexedDB 'meta' store instead for all persistent SW state.

function _getMetaValue(key) {
  return new Promise((resolve) => {
    const req = indexedDB.open("asha-sync-db", 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(SYNC_QUEUE_KEY))
        db.createObjectStore(SYNC_QUEUE_KEY, { keyPath: "id" });
      if (!db.objectStoreNames.contains("meta"))
        db.createObjectStore("meta");
    };
    req.onsuccess = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("meta")) { resolve(null); return; }
      const tx = db.transaction("meta", "readonly");
      const r = tx.objectStore("meta").get(key);
      r.onsuccess = () => resolve(r.result ?? null);
      r.onerror = () => resolve(null);
    };
    req.onerror = () => resolve(null);
  });
}

function _setMetaValue(key, value) {
  return new Promise((resolve) => {
    const req = indexedDB.open("asha-sync-db", 1);
    req.onsuccess = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("meta")) { resolve(); return; }
      const tx = db.transaction("meta", "readwrite");
      tx.objectStore("meta").put(value, key);
      tx.oncomplete = resolve;
      tx.onerror = () => resolve();
    };
    req.onerror = () => resolve();
  });
}

async function getAuthToken() {
  // Auth token is stored by the main page into IndexedDB meta store
  return _getMetaValue("asha_token");
}

async function getDeviceId() {
  let id = await _getMetaValue("asha_device_id");
  if (!id) {
    id = "dev-" + Math.random().toString(36).slice(2);
    await _setMetaValue("asha_device_id", id);
  }
  return id;
}

async function getLastSyncTs() {
  const val = await _getMetaValue("last_sync_ts");
  return parseFloat(val || "0");
}

async function setLastSyncTs(ts) {
  await _setMetaValue("last_sync_ts", String(ts));
}

async function mergeServerChanges(changes) {
  if (!changes || !changes.length) return;
  // Write server-side visit changes into the main asha-saheli IndexedDB
  // so the ASHA sees updated data immediately without a page reload.
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("asha-saheli", 1);
    req.onsuccess = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("visits")) { resolve(); return; }
      const tx = db.transaction("visits", "readwrite");
      const store = tx.objectStore("visits");
      for (const record of changes) store.put(record);
      tx.oncomplete = resolve;
      tx.onerror = reject;
    };
    req.onerror = reject;
  });
}
