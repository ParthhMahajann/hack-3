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

// ── Offline risk computation (mirrors risk_engine.py exactly) ───────────────
// Weights and thresholds kept identical to backend so risk level is stable
// before and after sync.  References match risk_engine.py inline citations.

function computeRiskOffline(visit) {
  const result = _computeRiskDetail(visit);
  return result.level;
}

function computeRiskDetailOffline(visit) {
  return _computeRiskDetail(visit);
}

function _computeRiskDetail(visit) {
  const v = visit.vitals || {};
  const o = visit.observations || {};
  const patientType = visit.patient_type || "maternal";
  if (patientType === "child") return _childRiskOffline(v, o);
  return _maternalRiskOffline(v, o);
}

// Thresholds must stay in sync with risk_engine.py constants
const _HB_SEVERE = 7.0, _HB_MODERATE = 10.0;
const _BP_SEVERE_SYS = 160, _BP_SEVERE_DIA = 110;
const _BP_PREEC_SYS = 140, _BP_PREEC_DIA = 90;
const _IMMUN_OVERDUE_DAYS = 28, _IMMUNIZATION_URGENT_DAYS = 60;
const _FEVER_DANGER_DAYS = 7, _FEVER_TEMP_HIGH = 38.5;
const _MUAC_SAM = 115, _MUAC_MAM = 125;
const _GDM_FBS = 126;

function _maternalRiskOffline(v, o) {
  let score = 0;
  const hb  = parseFloat(v.hemoglobin   || 12);
  const sys = parseInt(v.systolic_bp    || 110);
  const dia = parseInt(v.diastolic_bp   || 70);
  const fbs = parseFloat(v.fbs         || 0);

  // Haemoglobin [WHO ANC Rec 38]
  if (hb < _HB_SEVERE)    score += 60;
  else if (hb < _HB_MODERATE) score += 20;

  // Blood pressure [WHO ANC Rec 29]
  if (sys >= _BP_SEVERE_SYS || dia >= _BP_SEVERE_DIA) score += 80;
  else if (sys >= _BP_PREEC_SYS || dia >= _BP_PREEC_DIA) score += 35;

  // Pre-eclampsia signs
  if (o.edema_generalised)  score += 15;
  if (o.proteinuria_2plus)  score += 20;

  // Pre-eclampsia triad synergy override [WHO ANC]
  if ((sys >= _BP_PREEC_SYS || dia >= _BP_PREEC_DIA) &&
      o.edema_generalised && o.proteinuria_2plus) {
    score = Math.max(score, 80);
  }

  // Obstetric history + ANC adherence [FOGSI 2020]
  if (o.previous_complications) score += 15;
  if ((o.missed_anc_visits || 0) >= 2) score += 10;
  else if ((o.missed_anc_visits || 0) >= 1) score += 5;

  // Gestational diabetes [IDF/WHO]
  if (fbs > _GDM_FBS) score += 15;

  return { score, level: _classifyScore(score) };
}

function _childRiskOffline(v, o) {
  // IMNCI General Danger Signs → immediate PURPLE [IMNCI India 2009, Ch 2]
  const dangerSigns = o.danger_signs || [];
  const imncis = ["not_able_to_drink", "vomits_everything", "convulsions",
                  "lethargic_unconscious", "severe_chest_indrawing", "stridor_calm"];
  if (dangerSigns.some(s => imncis.includes(s))) {
    return { score: 100, level: "purple" };
  }

  let score = 0;
  const muac = parseFloat(v.muac_mm || 0);
  const temp = parseFloat(v.temperature_c || 0);

  // MUAC [WHO Pocket Book 2013]
  if (muac > 0) {
    if (muac < _MUAC_SAM)      score += 40;
    else if (muac < _MUAC_MAM) score += 20;
  }

  // Fever [IMNCI Ch 3] — persistent fever >= 7 days = RED minimum
  if ((o.fever_days || 0) >= _FEVER_DANGER_DAYS) score += 60;
  else if (temp >= _FEVER_TEMP_HIGH)              score += 10;

  // Breastfeeding (under 6 months)
  if ((o.age_months || 12) < 6 && o.breastfeeding_ok === false) score += 15;

  // Immunisation overdue [NVHCP schedule]
  if ((o.immunisation_overdue_days || 0) >= _IMMUNIZATION_URGENT_DAYS) score += 60;
  else if ((o.immunisation_overdue_days || 0) >= _IMMUN_OVERDUE_DAYS)  score += 15;

  return { score, level: _classifyScore(score) };
}

function _classifyScore(score) {
  if (score >= 80) return "purple";
  if (score >= 60) return "red";
  if (score >= 30) return "yellow";
  return "green";
}

async function clearSyncQueue() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("sync_queue", "readwrite");
    tx.objectStore("sync_queue").clear().onsuccess = resolve;
    tx.onerror = reject;
  });
}

// Export for use in templates
window.AshaDB = {
  savePatient, getPatients,
  saveVisit, getVisitsForPatient,
  getSyncQueue, clearSyncQueue,
  computeRiskOffline, computeRiskDetailOffline,
};
