# CalmCollective — Local & Inclusive Mental Health AI (MVP)

_By Wiqi Lee — Twitter: [@wiqi_lee](https://twitter.com/wiqi_lee)_

CalmCollective is a lightweight, privacy-first web app for **gentle mental wellness**.  
It supports multiple "support flavors" — **Secular**, **Cultural (Nusantara)**, or **Faith-informed**
(Islam, Christian, Hindu, Buddhist) — so users can opt-in to the voice that resonates with them.  
It is **not** a medical tool and **not** a replacement for professional care.

> This MVP demo is intended for local/offline experimentation — all data is stored locally on disk or in your browser.

---

## ✨ Features
- 📝 **Mood journaling** with rotating daily prompts  
- 🤖 **Lightweight mood analysis** (lexicon-based) for instant feedback  
- 🌬️ **Micro-interventions**: 60-second self-care ideas (breathing, grounding, reframing, connection)  
- 💬 **Support flavors** (secular / cultural / faith-informed — opt-in)  
- 🔍 **Filter entries** by flavor or date range  
- 📊 **Mood chart** with color bands (0–3 low, 4–6 mid, 7–10 high)  
- ⏱️ **Breathing timer** (shows under footer on Entries page only)  
- 🚨 **Crisis alert** banner if risk signals (e.g. “suicide”, “hopeless”) are detected  
- 📦 Local JSON storage (no external APIs)  
- 📤 Export to **JSON / CSV / PDF** (PDF respects your filters)  
- 📱 **Offline mode** with service worker + PWA manifest (journal without internet)  
- ⚠️ **Safety disclaimer** + customizable emergency contact  

---

## 🚀 Quickstart
```bash
# 1) Create & activate a virtual environment
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Run
python app.py --port=5050
# Open http://127.0.0.1:5050
```

---

## 📂 Project Structure
```
calmcollective/
├─ app.py
├─ requirements.txt
├─ README.md
├─ LICENSE
├─ utils/
│  └─ analyzer.py
├─ assets/
│  ├─ prompts.json
│  ├─ quotes.json
│  ├─ scriptures.json
│  └─ wisdom.json
├─ templates/
│  ├─ layout.html
│  ├─ index.html
│  ├─ entries.html
│  └─ export.html
├─ static/
│  ├─ css/styles.css
│  ├─ js/app.js
│  ├─ sw.js
│  └─ manifest.webmanifest
└─ data/
   ├─ entries.json
   └─ settings.json
```

---

## ⚙️ Configuration
Edit `data/settings.json` to customize emergency info and default support flavor:

```json
{
  "emergency_text": "If you are in immediate danger, contact local emergency services.",
  "emergency_contact_label": "Family",
  "emergency_contact_value": "Phone Number",
  "default_support_flavor": "secular"
}
```

---

## 📤 Export Options
- **JSON** — raw entries with analysis  
- **CSV** — spreadsheet-friendly  
- **PDF** — formatted export with mood, text, quotes, wisdom, and applied filters  

Example:  
```
/export/pdf?flavor=secular&start=2025-09-01&end=2025-09-30
```

---

## 📱 Offline Mode (PWA)
- A **service worker (`static/sw.js`)** caches static assets and API responses  
- **Cache-first** for CSS/JS/images  
- **Network-first** for `/api/entries` (fresh when online, fallback when offline)  
- `manifest.webmanifest` allows install to home screen  

---

## 🧘 Ethics & Safety
- For **self-care and reflection**, not therapy or diagnosis  
- For crisis: **seek professional and emergency help immediately**  
- Custom quotes, especially faith-based, should be verified for **accuracy & attribution**  

---

## 📚 Evidence Basis
The suggestions are inspired by common psychoeducation frameworks:  
- **CBT** (cognitive reframing, alternative thoughts)  
- **DBT** (STOP skill, mindfulness steps)  
- **ACT** (cognitive defusion, values-based action)  
- **Grounding** (5-4-3-2-1 sensory exercise)  

---

## ➕ Add Your Own Wisdom
Edit `assets/wisdom.json`. Each entry must have `text` and `author`:

```json
{
  "islam": [
    { "text": "Sabar itu indah.", "author": "Ulama" }
  ],
  "secular": [
    { "text": "Keep going, keep growing.", "author": "Unknown" }
  ]
}
```

The app will automatically use the matching **support flavor**, or fall back to `secular`.

---

## 📜 License
MIT — © Wiqi Lee
