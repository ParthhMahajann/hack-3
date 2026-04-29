# 🌿 ASHA Saheli — Digital Field Diary for Frontline Health Workers

> An offline-first Progressive Web App (PWA) + Native Android App empowering India's 1 million+ ASHA workers with evidence-based risk scoring, ML-powered predictions, and automated incentive tracking.

[![Tests](https://img.shields.io/badge/tests-23%2F23%20passed-brightgreen)](#testing)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Android](https://img.shields.io/badge/android-APK%20ready-3DDC84?logo=android&logoColor=white)](#android-app)
[![Capacitor](https://img.shields.io/badge/capacitor-6.x-119EFF?logo=capacitor&logoColor=white)](https://capacitorjs.com)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

---

## 🎯 Problem Statement

India's **Accredited Social Health Activists (ASHA)** serve as the critical link between rural communities and the public health system. They track pregnancies, child health, immunizations, and nutrition using **paper-based MCP cards** — leading to:

- ❌ Delayed identification of high-risk pregnancies (pre-eclampsia, severe anaemia)
- ❌ Missed follow-up visits for malnourished children (SAM/MAM)
- ❌ No data connectivity in remote villages
- ❌ Manual, error-prone incentive calculations (JSY/JSSK schemes)
- ❌ No real-time visibility for Block Health Officers

## 💡 Solution

**ASHA Saheli** digitizes the entire ASHA workflow with an **offline-first** approach — every feature works without internet and syncs when connectivity returns. It is available both as a **Progressive Web App (PWA)** in any browser and as a **native Android APK** for one-tap installation.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🏥 **Risk Scoring Engine** | 16 clinical rules based on WHO ANC 2016, IMNCI 2009, FOGSI 2020 |
| 🤖 **ML 30-Day Predictor** | Logistic regression model predicting adverse outcomes, calibrated to NFHS-5 |
| 📱 **Offline-First PWA** | Service Worker + IndexedDB — works in zero-connectivity villages |
| 🤖 **Native Android App** | Capacitor-powered APK — installable directly on any Android phone |
| 🔄 **Delta Sync** | CRDT-inspired field-level sync with conflict resolution (Shapiro et al., 2011) |
| 💰 **Incentive Tracker** | Automated JSY/JSSK calculation per MOHFW 2015 guidelines |
| 📊 **Officer Dashboard** | Risk distribution charts, ANC coverage, HMIS CSV export |
| 🔔 **Alert System** | RED → in-app notification, PURPLE → SMS via Twilio |
| 📚 **Research Methodology** | Dedicated page mapping 10 research papers to code implementation |
| 🌐 **Bilingual NLP Summaries** | Auto-generates visit summaries in English + Hindi |
| 📍 **GPS Verification** | Captures visit location for audit trail |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│  📱 ASHA Phone (PWA / Android APK)      │
│  ├── IndexedDB (patients, visits)        │
│  ├── Service Worker (CacheFirst)         │
│  ├── Client-side risk scoring            │
│  └── Background Sync queue              │
│              ↕️                          │
│     (syncs when online)                 │
│              ↕️                          │
│  🌐 FastAPI Server (Python)             │
│  ├── SQLAlchemy async (models)          │
│  ├── Risk Engine (16 rules)             │
│  ├── ML Predictor (LogReg)             │
│  ├── NLP Summarizer (EN/HI)            │
│  ├── Sync Engine (delta merge)          │
│  ├── Incentive Calculator              │
│  └── Alert Service (Twilio/in-app)     │
│              ↕️                          │
│  🏢 Block Officer Dashboard             │
│  ├── Chart.js visualizations            │
│  ├── High-risk patient table            │
│  ├── Workload forecast API              │
│  └── HMIS CSV export                   │
└─────────────────────────────────────────┘
```

---

## 📚 Research Paper References

Every clinical threshold is traceable to a published source:

| # | Paper | Key Contribution |
|---|-------|-----------------|
| 1 | **WHO ANC 2016** (WHO/RHR/16.12) | BP, Hb, GDM thresholds; 8-contact schedule |
| 2 | **MOHFW IMNCI 2009** | 6 general danger signs → immediate referral |
| 3 | **WHO Growth Standards 2006** | Weight-for-Age Z-score (LMS method) |
| 4 | **WHO MUAC 2013** | SAM <115mm, MAM 115-125mm |
| 5 | **FOGSI 2020** | Adolescent/advanced maternal age risk |
| 6 | **IDF/WHO GDM Criteria** | FBS >126 mg/dL threshold |
| 7 | **Rana et al., BMC 2023** | ML prediction architecture (DOI: 10.1186/s12884-023-05387-5) |
| 8 | **Shapiro et al., INRIA 2011** | CRDT sync strategy (hal-00932836) |
| 9 | **JSY/JSSK MOHFW 2015** | Incentive amounts per event |
| 10 | **NFHS-5 India 2019-21** | ML calibration prevalence rates |

👉 **See the full methodology at `/app/research` in the live app or via `/api/methodology`**

---

## 🚀 Quick Start (Web / Backend)

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/ParthhMahajann/hack-3.git
cd hack-3

# Install dependencies
pip install -r requirements.txt

# Run the server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

### Demo Accounts

| Role | Email | Password |
|------|-------|----------|
| ASHA Worker | asha1@demo.in | asha123 |
| Block Officer | officer@demo.in | officer123 |

---

## 📱 Android App

The project includes a fully built native Android app powered by **Capacitor 6**. It wraps the PWA inside a native Android WebView container and can be installed directly on any Android device.

### Option A — Build from Source (Android Studio)

**Prerequisites:** Android Studio (with Android SDK), Node.js 18+, JDK 21

```bash
# Step 1: Install Capacitor dependencies
cd pwa
npm install

# Step 2: Sync web assets into the Android project
npx cap sync android

# Step 3: Open in Android Studio
npx cap open android
```

Once Android Studio opens, click the **▶ Run** button to install on your emulator or connected phone.

### Option B — Build APK from Command Line

```bash
cd pwa/android

# Windows
.\gradlew assembleDebug

# macOS / Linux
./gradlew assembleDebug
```

The final APK will be generated at:
```
pwa/android/app/build/outputs/apk/debug/app-debug.apk
```

### Installing the APK on a Phone

1. Copy `app-debug.apk` to your Android phone.
2. Tap the file in your phone's File Manager.
3. If prompted, allow **"Install from Unknown Sources"**.
4. The **ASHA Saheli** app icon will appear on your home screen.

### Android App Info

| Property | Value |
|----------|-------|
| App ID | `com.ashasaheli.app` |
| Min SDK | Android 7.0 (API 24) |
| Target SDK | Android 16 (API 36) |
| Build Tool | Capacitor 6 + Gradle 8.13 |
| JDK Required | JDK 21 |

---

## 🧪 Testing

```bash
# Run all 23 tests
python -m pytest tests/ -v

# Output:
# tests/test_risk_engine.py  — 16 clinical scenario tests ✅
# tests/test_integration.py  — 7 full-pipeline tests ✅
# ======================= 23 passed =======================
```

---

## 📁 Project Structure

```
hack-3/
├── backend/
│   ├── main.py                   # FastAPI app, routes, demo seeding
│   ├── config.py                  # Pydantic Settings (.env)
│   ├── database.py                # Async SQLAlchemy engine
│   ├── models.py                  # SQLAlchemy models
│   ├── core/
│   │   ├── risk_engine.py         # 16-rule clinical scoring (WHO/IMNCI)
│   │   ├── ml_risk_predictor.py   # Logistic regression 30-day forecast
│   │   ├── nlp_summarizer.py      # Bilingual visit summary generator
│   │   ├── sync_engine.py         # Delta sync with conflict resolution
│   │   ├── incentive_calculator.py# JSY/JSSK auto-calculation
│   │   └── alert_service.py       # Twilio SMS + in-app notifications
│   └── routers/
│       ├── auth.py                # JWT authentication
│       ├── patients.py            # Patient CRUD
│       ├── visits.py              # Visit logging + risk computation
│       ├── sync.py                # Bidirectional sync endpoint
│       ├── dashboard.py           # Officer dashboard APIs
│       └── analytics.py           # Research methodology + workload forecast
├── frontend/
│   ├── static/
│   │   ├── css/app.css            # Design system (glassmorphism, dark mode)
│   │   ├── js/db.js               # IndexedDB offline storage
│   │   ├── js/sync.js             # Sync coordinator
│   │   ├── sw.js                  # Service Worker (CacheFirst + BackgroundSync)
│   │   └── manifest.json          # PWA manifest
│   └── templates/
│       ├── base.html              # App shell
│       ├── index.html             # Login page
│       ├── asha/                  # ASHA worker pages
│       │   ├── dashboard.html
│       │   ├── patient_form.html
│       │   ├── visit_form.html    # Hindi bilingual labels + live risk preview
│       │   ├── incentives.html
│       │   └── research.html      # Research methodology page
│       └── officer/
│           └── dashboard.html     # Charts + HMIS export
├── pwa/                           # Android app (Capacitor)
│   ├── android/                   # Native Android Studio project
│   │   ├── app/
│   │   │   ├── src/main/
│   │   │   │   ├── AndroidManifest.xml
│   │   │   │   └── java/com/ashasaheli/app/MainActivity.java
│   │   │   └── build.gradle
│   │   ├── gradle/wrapper/
│   │   ├── build.gradle
│   │   └── variables.gradle
│   ├── capacitor.config.json      # Capacitor app configuration
│   └── package.json               # Capacitor npm dependencies
├── tests/
│   ├── test_risk_engine.py        # 16 clinical validation tests
│   └── test_integration.py        # 7 full-pipeline tests
├── requirements.txt
└── README.md
```

---

## 🛡️ Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, SQLAlchemy (async), Pydantic |
| Database | SQLite + aiosqlite (PostgreSQL-ready) |
| Frontend | Jinja2 templates, vanilla JS, CSS3 |
| Offline | Service Worker, IndexedDB, Background Sync API |
| Android App | Capacitor 6, Gradle 8.13, JDK 21 |
| ML | Scikit-learn-compatible Logistic Regression |
| Charts | Chart.js 4.x |
| Auth | JWT (python-jose) + bcrypt |
| SMS | Twilio (optional) |
| Font | Google Noto Sans |

---

## 👨‍💻 Author

**Parth Mahajan**
- GitHub: [@ParthhMahajann](https://github.com/ParthhMahajann)

---

## 📄 License

This project is open source under the **MIT License**.
