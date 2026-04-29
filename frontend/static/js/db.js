/**
 * IndexedDB wrapper (Dexie-free, vanilla IDB)
 * Stores patients, visits, and sync queue locally.
 * All writes to this DB are queued for background sync.
 */

const DB_NAME = "asha-saheli";
const DB_VERSION = 1;

let _db = null;

async function openDB() {
  if (_db) return _db;
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("patients")) {
        const ps = db.createObjectStore("patients", { keyPath: "id" });
        ps.createIndex("asha_id", "asha_id");
        ps.createIndex("risk_level", "current_risk_level");
      }
      if (!db.objectStoreNames.contains("visits")) {
        const vs = db.createObjectStore("visits", { keyPath: "id" });
        vs.createIndex("patient_id", "patient_id");
        vs.createIndex("risk_level", "risk_level");
      }
      if (!db.objectStoreNames.contains("sync_queue")) {
        db.createObjectStore("sync_queue", { keyPath: "id" });
      }
    };
    req.onsuccess = (e) => { _db = e.target.result; resolve(_db); };
    req.onerror = reject;
  });
}

// ── Generic helpers ──────────────────────────────────────────────────────────

async function dbPut(storeName, record) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).put(record).onsuccess = resolve;
    tx.onerror = reject;
  });
}

async function dbGet(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const req = tx.objectStore(storeName).get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = reject;
  });
}

async function dbGetAll(storeName) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const req = tx.objectStore(storeName).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = reject;
  });
}

async function dbDelete(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).delete(key).onsuccess = resolve;
    tx.onerror = reject;
  });
}

// ── Patient operations ───────────────────────────────────────────────────────

async function savePatient(patient) {
  patient.updated_at = Date.now() / 1000;
  patient.entity_type = "patient";
  await dbPut("patients", patient);
  await enqueueSync(patient);
}

async function getPatients() {
  // Try network first, fall back to IndexedDB
  try {
    const token = localStorage.getItem("asha_token");
    const resp = await fetch("/patients/", {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (resp.ok) {
      const patients = await resp.json();
      // Cache locally
      for (const p of patients) await dbPut("patients", p);
      return patients;
    }
  } catch { /* offline */ }
  return dbGetAll("patients");
}

// ── Visit operations ─────────────────────────────────────────────────────────

async function saveVisit(visit) {
  visit.updated_at = Date.now() / 1000;
  visit.entity_type = "visit";
  // Compute risk offline before queuing
  visit.risk_level = computeRiskOffline(visit);
  await dbPut("visits", visit);
  await enqueueSync(visit);
  // Trigger background sync when possible
  if ("serviceWorker" in navigator && "SyncManager" in window) {
    const reg = await navigator.serviceWorker.ready;
    await reg.sync.register("asha-sync");
  }
}

async function getVisitsForPatient(patientId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("visits", "readonly");
    const idx = tx.objectStore("visits").index("patient_id");
    const req = idx.getAll(patientId);
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = reject;
  });
}

// ── Sync queue ───────────────────────────────────────────────────────────────

async function enqueueSync(record) {
  await dbPut("sync_queue", { ...record, queued_at: Date.now() / 1000 });
}

async function getSyncQueue() {
  return dbGetAll("sync_queue");
}

async function clearSyncQueueItem(id) {
  return dbDelete("sync_queue", id);
}

// ── Offline risk computation (mirrors risk_engine.py logic) ─────────────────
// This is kept in sync manually with the Python backend.
// It runs instantly in-browser so the ASHA sees the risk level before sync.

function computeRiskOffline(visit) {
  const v = visit.vitals || {};
  const o = visit.observations || {};
  const patientType = visit.patient_type || "maternal";

  if (patientType === "child") return _childRiskOffline(v, o);
  return _maternalRiskOffline(v, o);
}

function _maternalRiskOffline(v, o) {
  let score = 0;
  const hb = parseFloat(v.hemoglobin || 12);
  const sys = parseInt(v.systolic_bp || 110);
  const dia = parseInt(v.diastolic_bp || 70);

  if (hb < 7)       score += 30;
  else if (hb < 10) score += 15;

  if (sys >= 160 || dia >= 110) score += 40;
  else if (sys >= 140 || dia >= 90) score += 25;

  if (o.edema_generalised)   score += 15;
  if (o.proteinuria_2plus)   score += 15;
  if (o.previous_complications) score += 15;
  if ((o.missed_anc_visits || 0) >= 2) score += 10;

  return _classifyScore(score);
}

function _childRiskOffline(v, o) {
  // IMNCI danger signs → immediate PURPLE
  const dangerSigns = o.danger_signs || [];
  const imncis = ["not_able_to_drink","vomits_everything","convulsions",
                  "lethargic_unconscious","severe_chest_indrawing"];
  if (dangerSigns.some(s => imncis.includes(s))) return "purple";

  let score = 0;
  const muac = parseFloat(v.muac_mm || 999);
  if (muac < 115)      score += 40;
  else if (muac < 125) score += 20;
  if ((o.fever_days || 0) >= 7) score += 20;
  if ((o.immunisation_overdue_days || 0) >= 60) score += 20;

  return _classifyScore(score);
}

function _classifyScore(score) {
  if (score >= 80) return "purple";
  if (score >= 60) return "red";
  if (score >= 30) return "yellow";
  return "green";
}

// Export for use in templates
window.AshaDB = {
  savePatient, getPatients,
  saveVisit, getVisitsForPatient,
  getSyncQueue, computeRiskOffline,
};
