/**
 * Sync coordinator — manages manual and automatic sync.
 * Listens for SW SYNC_COMPLETE messages and updates UI.
 */

const SyncManager = (() => {
  let _isSyncing = false;

  async function triggerManualSync() {
    if (_isSyncing) return;
    const token = localStorage.getItem("asha_token");
    if (!token) return;

    _isSyncing = true;
    _updateSyncBadge("syncing");

    try {
      const queue = await window.AshaDB.getSyncQueue();
      if (!queue.length) {
        _updateSyncBadge("synced");
        _isSyncing = false;
        return;
      }

      const deviceId = localStorage.getItem("asha_device_id") ||
        (() => { const id = "dev-" + Math.random().toString(36).slice(2); localStorage.setItem("asha_device_id", id); return id; })();
      const lastSyncTs = parseFloat(localStorage.getItem("last_sync_ts") || "0");

      const resp = await fetch("/sync/", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          device_id: deviceId,
          last_sync_ts: lastSyncTs,
          records: queue,
        }),
      });

      if (resp.ok) {
        const result = await resp.json();
        localStorage.setItem("last_sync_ts", String(result.server_ts));
        // Clear the local queue so items aren't resent on next sync
        await window.AshaDB.clearSyncQueue();
        _showToast(`Synced: ${result.created} new, ${result.updated} updated`);
        _updateSyncBadge("synced");
        _updatePendingCount(0);
        // Reload patient list to reflect server state
        if (typeof loadDashboard === "function") loadDashboard();
      } else {
        _updateSyncBadge("error");
      }
    } catch (err) {
      _updateSyncBadge("offline");
      _showToast("Offline — data saved locally, will sync when connected");
    }
    _isSyncing = false;
  }

  function _updateSyncBadge(state) {
    const badge = document.getElementById("sync-badge");
    if (!badge) return;
    const states = {
      synced:  { text: "Synced",   cls: "badge-synced" },
      syncing: { text: "Syncing…", cls: "badge-syncing" },
      offline: { text: "Offline",  cls: "badge-offline" },
      error:   { text: "Sync Error", cls: "badge-error" },
      pending: { text: "Pending",  cls: "badge-pending" },
    };
    const s = states[state] || states.synced;
    badge.textContent = s.text;
    badge.className = `sync-badge ${s.cls}`;
  }

  function _updatePendingCount(count) {
    const el = document.getElementById("pending-count");
    if (el) el.textContent = count > 0 ? `${count} pending` : "";
  }

  function _showToast(msg) {
    const t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 3000);
  }

  // Listen for SW sync completion
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data?.type === "SYNC_COMPLETE") {
        _updateSyncBadge("synced");
        _showToast("Background sync complete");
      }
    });
  }

  // Auto-sync when coming online
  window.addEventListener("online", () => {
    _updateSyncBadge("syncing");
    triggerManualSync();
  });

  window.addEventListener("offline", () => _updateSyncBadge("offline"));

  // Check initial state
  document.addEventListener("DOMContentLoaded", async () => {
    const queue = await window.AshaDB?.getSyncQueue?.() || [];
    if (!navigator.onLine) {
      _updateSyncBadge("offline");
    } else if (queue.length > 0) {
      _updateSyncBadge("pending");
      _updatePendingCount(queue.length);
    } else {
      _updateSyncBadge("synced");
    }
  });

  return { triggerManualSync };
})();

window.SyncManager = SyncManager;
