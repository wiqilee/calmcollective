from __future__ import annotations
import json
import os
import csv
import argparse
import random
from io import StringIO, BytesIO
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file
from flask_wtf.csrf import CSRFProtect   # CSRF

# --- PDF (ReportLab) ---
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.units import mm

from utils.analyzer import analyze_text, micro_interventions

APP_NAME = "CalmCollective"
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

ENTRIES_PATH = os.path.join(DATA_DIR, "entries.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

QUOTES_PATH = os.path.join(ASSETS_DIR, "quotes.json")
PROMPTS_PATH = os.path.join(ASSETS_DIR, "prompts.json")
SCRIPTURES_PATH = os.path.join(ASSETS_DIR, "scriptures.json")
WISDOM_PATH = os.path.join(ASSETS_DIR, "wisdom.json")

# ---------- Friendly flavor labels (global) ----------
FLAVOR_LABELS: Dict[str, str] = {
    "secular": "Supportive (Secular)",
    "cultural_nusantara": "Nusantara Wisdom",
    "islam": "Spiritual (Islam)",
    "christian": "Spiritual (Christian)",
    "hindu": "Spiritual (Hindu)",
    "buddhist": "Spiritual (Buddhist)",
}

app = Flask(__name__)
app.secret_key = "dev-key-change-me"  # For flash messages

# ---------- Security ----------
csrf = CSRFProtect(app)

# Make flavor_labels available in ALL templates
@app.context_processor
def inject_globals():
    return {
        "flavor_labels": FLAVOR_LABELS,
        "flavor_label": lambda key: FLAVOR_LABELS.get(key, key),
    }

# ---------- Utilities ----------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for p, d in [(ENTRIES_PATH, []), (SETTINGS_PATH, {})]:
        if not os.path.exists(p):
            save_json(p, d)

def _append_to_map_list(path: str, flavor: str, item):
    """Append an item to a flavor list inside a JSON map file (create if missing)."""
    m = load_json(path, {})
    if flavor not in m or not isinstance(m[flavor], list):
        m[flavor] = []
    m[flavor].append(item)
    save_json(path, m)

def _last_entry() -> Optional[Dict]:
    entries: List[Dict] = load_json(ENTRIES_PATH, [])
    return entries[-1] if entries else None

def _pick_variant(options: List, last_value):
    """Pick a random item from options, trying not to repeat the previous selection."""
    if not options:
        return None
    if last_value in options and len(options) > 1:
        pool = [o for o in options if o != last_value]
        return random.choice(pool)
    return random.choice(options)

def _same_wisdom(a, b) -> bool:
    return (
        isinstance(a, dict) and isinstance(b, dict)
        and a.get("text") == b.get("text")
        and a.get("author") == b.get("author")
    )

def _parse_date_yyyy_mm_dd(s: Optional[str]) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD' -> datetime (naive). Return None if invalid/empty."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None

def _parse_entry_ts(e: Dict) -> Optional[datetime]:
    """Entries store timestamp like '2025-09-05T12:34:56'. Parse safely."""
    ts = e.get("timestamp")
    if not ts:
        return None
    try:
        ts = ts.replace(" ", "T")
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def _filter_entries(entries: List[Dict], flavor: Optional[str], start: Optional[str], end: Optional[str]) -> List[Dict]:
    """Filter by flavor and inclusive date range [start, end]. Dates are in local naive time."""
    f = (flavor or "").strip().lower()
    start_dt = _parse_date_yyyy_mm_dd(start)
    end_dt = _parse_date_yyyy_mm_dd(end)

    # Normalize end to end-of-day if provided
    if end_dt:
        end_dt = end_dt + timedelta(days=1) - timedelta(seconds=1)

    out = []
    for e in entries:
        # flavor filter
        if f and f != "all" and e.get("flavor") != f:
            continue

        # date filter
        if start_dt or end_dt:
            et = _parse_entry_ts(e)
            if not et:
                continue
            if start_dt and et < start_dt:
                continue
            if end_dt and et > end_dt:
                continue

        out.append(e)
    return out

def _fmt_entry_ts(e: Dict) -> str:
    """Format entry timestamp -> 'YYYY-MM-DD HH:MM' (fallback to raw)."""
    dt = _parse_entry_ts(e)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (e.get("timestamp", "") or "")

def _wrap_text_by_width(text: str, c: pdfcanvas.Canvas, max_width_pt: float, font_name: str = "Helvetica", font_size: int = 10) -> List[str]:
    """
    Wrap text into lines that fit within max_width using the current canvas font metrics.
    """
    if not text:
        return []
    words = text.replace("\r", "").split()
    lines: List[str] = []
    current = ""
    for w in words:
        candidate = w if not current else (current + " " + w)
        if c.stringWidth(candidate, font_name, font_size) <= max_width_pt:
            current = candidate
        else:
            if current:
                lines.append(current)
            # If a single word itself is longer than width, hard-split it
            if c.stringWidth(w, font_name, font_size) > max_width_pt:
                buf = ""
                for ch in w:
                    if c.stringWidth(buf + ch, font_name, font_size) <= max_width_pt:
                        buf += ch
                    else:
                        if buf:
                            lines.append(buf)
                        buf = ch
                current = buf
            else:
                current = w
    if current:
        lines.append(current)
    return lines

# ---------- Support message crafting (psych-informed) ----------
def _craft_support_messages(text: str, analysis: Dict, mood: float) -> List[str]:
    """
    Produce up to 2 brief, compassionate, and actionable suggestions.
    Uses mood, simple keyword cues in text, and micro_interventions() as a pool.
    """
    t = (text or "").lower()
    pos = int(analysis.get("positive", 0) or 0)
    neg = int(analysis.get("negative", 0) or 0)

    # Base micro-interventions pool (from utils) + curated short actions
    pool = (micro_interventions(analysis) or []) + [
        "Take 6 slow breaths: inhale 4s through your nose, exhale 6s. Notice your shoulders drop.",
        "Try 5-4-3-2-1 grounding: 5 see, 4 touch, 3 hear, 2 smell, 1 taste.",
        "Choose one tiny valued action: drink water, open a window, or tidy one item.",
        "Message a trusted person one honest sentence about how you're feeling.",
        "Place a hand on your chest and say: ‘This is hard, and I’m doing my best.’",
        "Write down one thing that is within your control for the next hour."
    ]

    # Gentle prioritization based on cues in text
    keyword_sets = [
        ({"panic", "cemas", "anxious", "anxiety", "overwhelmed"}, [
            "Take 6 slow breaths: inhale 4s through your nose, exhale 6s. Notice your shoulders drop.",
            "Try 5-4-3-2-1 grounding: 5 see, 4 touch, 3 hear, 2 smell, 1 taste."
        ]),
        ({"lelah", "tired", "exhausted", "burnout"}, [
            "Choose one tiny valued action: drink water, open a window, or tidy one item.",
            "Place a hand on your chest and say: ‘This is hard, and I’m doing my best.’"
        ]),
        ({"sedih", "alone", "lonely"}, [
            "Message a trusted person one honest sentence about how you're feeling.",
            "Choose one tiny valued action: drink water, open a window, or tidy one item."
        ]),
        ({"marah", "anger", "kesal", "frustrated"}, [
            "Take 6 slow breaths: inhale 4s through your nose, exhale 6s, for 1 minute.",
            "Write down one thing that is within your control for the next hour."
        ]),
        ({"stress", "stres", "overwhelm"}, [
            "Write down one thing that is within your control for the next hour.",
            "Choose one tiny valued action: drink water, open a window, or tidy one item."
        ]),
    ]

    prioritized: List[str] = []
    for keys, suggestions in keyword_sets:
        if any(k in t for k in keys):
            prioritized.extend(suggestions)

    # If strong negative tilt, lean to grounding + self-compassion
    if neg >= max(1, pos * 2):
        prioritized.extend([
            "Try 5-4-3-2-1 grounding: 5 see, 4 touch, 3 hear, 2 smell, 1 taste.",
            "Place a hand on your chest and say: ‘This is hard, and I’m doing my best.’",
        ])

    # Crisis tip when mood extremely low (kept short, non-alarming)
    crisis_tip = None
    if mood <= 2:
        crisis_tip = "If you feel unsafe or overwhelmed, consider reaching out to a trusted person or local helpline."

    # Build final list: crisis (if any) + two concise actions
    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for s in ([crisis_tip] if crisis_tip else []) + prioritized + pool:
        if not s:
            continue
        k = s.strip().lower()
        if k not in seen:
            seen.add(k)
            ordered.append(s)

    return ordered[:2] if not crisis_tip else [ordered[0]] + ordered[1:3]

# ---------- Routes ----------
@app.route("/")
def index():
    ensure_files()
    settings = load_json(SETTINGS_PATH, {})
    prompts = load_json(PROMPTS_PATH, [])
    # Rotate the prompt for variety
    prompt_text = random.choice(prompts) if isinstance(prompts, list) and prompts else "How are you feeling right now?"
    return render_template(
        "index.html",
        app_name=APP_NAME,
        settings=settings,
        prompt=prompt_text,
    )

@app.post("/journal")
def journal():
    ensure_files()
    text = request.form.get("entry_text", "").strip()
    try:
        mood = float(request.form.get("mood", "0"))
    except ValueError:
        mood = 0.0
    flavor = request.form.get("flavor", "secular")

    if not text:
        flash("Please write a few words about how you feel.", "error")
        return redirect(url_for("index"))

    analysis = analyze_text(text)

    # --- Psych-informed, concise suggestions (max 2) ---
    support = _craft_support_messages(text, analysis, mood)

    quotes_map = load_json(QUOTES_PATH, {})
    scriptures_map = load_json(SCRIPTURES_PATH, {})
    wisdom_map = load_json(WISDOM_PATH, {})

    last = _last_entry()

    # Spiritual note
    spiritual_candidates = scriptures_map.get(flavor) or scriptures_map.get("secular") or []
    last_spiritual = last.get("spiritual") if last else None
    spiritual = _pick_variant(spiritual_candidates, last_spiritual)

    # Quote
    quote_candidates = quotes_map.get(flavor) or quotes_map.get("secular") or ["You are doing the best you can."]
    last_quote = last.get("quote") if last else None
    quote = _pick_variant(quote_candidates, last_quote)

    # Wisdom
    wlist = wisdom_map.get(flavor) or wisdom_map.get("secular") or []
    last_wisdom = last.get("wisdom") if last else None
    if last_wisdom and wlist and any(_same_wisdom(last_wisdom, w) for w in wlist) and len(wlist) > 1:
        wpool = [w for w in wlist if not _same_wisdom(w, last_wisdom)]
        wisdom = random.choice(wpool)
    else:
        wisdom = random.choice(wlist) if wlist else None

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "text": text,
        "mood_slider": mood,
        "flavor": flavor,
        "analysis": analysis,
        "support": support,
        "quote": quote,
        "spiritual": spiritual,
        "wisdom": wisdom
    }

    entries: List[Dict] = load_json(ENTRIES_PATH, [])
    entries.append(entry)
    save_json(ENTRIES_PATH, entries)

    return redirect(url_for("entries"))

@app.get("/entries")
def entries():
    """
    Render entries page with optional filters via query string:
      /entries?flavor=secular&start=2025-09-01&end=2025-09-30
    """
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])
    settings = load_json(SETTINGS_PATH, {})

    flavor = request.args.get("flavor", default="", type=str)
    start  = request.args.get("start", default="", type=str)
    end    = request.args.get("end", default="", type=str)

    filtered = _filter_entries(all_entries, flavor, start, end)

    return render_template(
        "entries.html",
        app_name=APP_NAME,
        entries=filtered,
        settings=settings,
        current_flavor=flavor or "",
        current_start=start or "",
        current_end=end or "",
    )

@app.get("/api/entries")
def api_entries():
    """
    Return entries as JSON with optional filters and limit:
      /api/entries?flavor=secular&start=2025-09-01&end=2025-09-30&limit=90
    """
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])

    flavor = request.args.get("flavor", default="", type=str)
    start  = request.args.get("start",  default="", type=str)
    end    = request.args.get("end",    default="", type=str)
    limit  = request.args.get("limit",  type=int)

    filtered = _filter_entries(all_entries, flavor, start, end)

    # If limit is set, keep only the most recent N
    if isinstance(limit, int) and limit > 0:
        filtered = filtered[-limit:]

    return jsonify(filtered)

@app.get("/export")
def export_page():
    ensure_files()
    return render_template("export.html", app_name=APP_NAME)

@app.get("/export/json")
def export_json():
    ensure_files()
    entries = load_json(ENTRIES_PATH, [])
    return app.response_class(
        response=json.dumps(entries, ensure_ascii=False, indent=2),
        mimetype="application/json"
    )

@app.get("/export/csv")
def export_csv():
    """Safe CSV export using the csv module (proper quoting)."""
    ensure_files()
    entries = load_json(ENTRIES_PATH, [])
    fieldnames = ["timestamp", "mood_slider", "flavor", "mood_score", "positive", "negative", "text"]

    def row(e):
        a = e.get("analysis", {})
        return {
            "timestamp": e.get("timestamp", ""),
            "mood_slider": e.get("mood_slider", ""),
            "flavor": e.get("flavor", ""),
            "mood_score": a.get("mood_score", ""),
            "positive": a.get("positive", ""),
            "negative": a.get("negative", ""),
            "text": (e.get("text", "") or "").replace("\n", " ").strip(),
        }

    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for e in entries:
        writer.writerow(row(e))
    csv_data = sio.getvalue()
    return app.response_class(response=csv_data, mimetype="text/csv")

@app.get("/export/pdf")
def export_pdf():
    """
    Generate a PDF of entries with the same filters as /entries and /api/entries.
      /export/pdf?flavor=secular&start=2025-09-01&end=2025-09-30
    """
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])

    flavor = request.args.get("flavor", default="", type=str)
    start  = request.args.get("start",  default="", type=str)
    end    = request.args.get("end",    default="", type=str)

    entries = _filter_entries(all_entries, flavor, start, end)

    # Sort ascending by time for PDF readability
    entries.sort(key=lambda e: (_parse_entry_ts(e) or datetime.min))

    # Prepare PDF in memory
    buffer = BytesIO()
    page_w, page_h = A4
    margin = 18 * mm
    c = pdfcanvas.Canvas(buffer, pagesize=A4)

    # Header
    title = f"{APP_NAME} — Entries Export"
    subtitle_parts = []
    if flavor:
        subtitle_parts.append(f"Flavor: {FLAVOR_LABELS.get(flavor, flavor)}")
    if start:
        subtitle_parts.append(f"Start: {start}")
    if end:
        subtitle_parts.append(f"End: {end}")
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else "All entries"

    # Text settings
    y = page_h - margin
    c.setTitle(f"{APP_NAME} Export")
    c.setAuthor(APP_NAME)

    def draw_header():
        nonlocal y
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, y, title)
        y -= 14
        c.setFont("Helvetica", 10)
        c.drawString(margin, y, subtitle)
        y -= 8
        c.setLineWidth(0.5)
        c.line(margin, y, page_w - margin, y)
        y -= 10

    def ensure_space(lines_needed: int, line_height: int = 12):
        """Start a new page if there isn't enough vertical space."""
        nonlocal y
        min_y = margin + 20  # leave some bottom margin
        if y - (lines_needed * line_height) < min_y:
            c.showPage()
            y = page_h - margin
            draw_header()

    draw_header()

    if not entries:
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(margin, y, "No entries available for the selected filters.")
        c.showPage()
        c.save()
        buffer.seek(0)
        filename = "entries.pdf"
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)

    # Render each entry
    for e in entries:
        ts = _fmt_entry_ts(e)
        flavor_label = FLAVOR_LABELS.get(e.get("flavor", ""), e.get("flavor", ""))
        mood_slider = e.get("mood_slider", "")

        a = e.get("analysis", {}) or {}
        mood_score = a.get("mood_score", "")
        pos = a.get("positive", "")
        neg = a.get("negative", "")

        text = (e.get("text", "") or "").strip()
        quote = e.get("quote")
        spiritual = e.get("spiritual")
        wisdom = e.get("wisdom") or {}
        wisdom_text = wisdom.get("text")
        wisdom_author = wisdom.get("author")

        # Entry header line
        c.setFont("Helvetica-Bold", 11)
        header_line = f"{ts}   •   {flavor_label}   •   Mood: {mood_slider}"
        ensure_space(2)
        c.drawString(margin, y, header_line)
        y -= 13

        # Analysis line
        c.setFont("Helvetica", 10)
        analysis_line = f"Mood score: {mood_score}   (+{pos} / -{neg})"
        c.drawString(margin, y, analysis_line)
        y -= 12

        # Body text wrap
        max_w = page_w - 2 * margin
        c.setFont("Helvetica", 10)

        if text:
            ensure_space(2)
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(margin, y, "Your words:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in _wrap_text_by_width(text, c, max_w):
                ensure_space(1)
                c.drawString(margin, y, line)
                y -= 12

        # Quote / Spiritual / Wisdom blocks
        def draw_block(label: str, content: Optional[str], italic: bool = False):
            nonlocal y
            if not content:
                return
            ensure_space(2)
            c.setFont("Helvetica-Oblique", 10 if italic else 10)
            c.drawString(margin, y, f"{label}:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in _wrap_text_by_width(content, c, max_w):
                ensure_space(1)
                c.drawString(margin, y, f"“{line}”" if label != "Wisdom" else line)
                y -= 12

        if quote:
            draw_block("Supportive note", quote, italic=True)
        if spiritual:
            draw_block("Spiritual note", spiritual, italic=True)
        if wisdom_text:
            ensure_space(2)
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(margin, y, "Wisdom:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in _wrap_text_by_width(f"“{wisdom_text}”", c, max_w):
                ensure_space(1)
                c.drawString(margin, y, line)
                y -= 12
            if wisdom_author:
                ensure_space(1)
                c.setFont("Helvetica-Oblique", 10)
                c.drawString(margin, y, f"— {wisdom_author}")
                y -= 12

        # Spacer between entries
        ensure_space(1)
        y -= 6
        c.setLineWidth(0.3)
        c.setDash(1, 2)
        c.line(margin, y, page_w - margin, y)
        c.setDash()  # reset
        y -= 10

    c.showPage()
    c.save()
    buffer.seek(0)

    # Filename with filters for convenience
    parts = ["entries"]
    if flavor:
        parts.append(flavor)
    if start:
        parts.append(start)
    if end:
        parts.append(end)
    filename = "-".join(parts) + ".pdf"

    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)

# ---------- Root-served PWA files ----------
@app.get("/sw.js")
def service_worker():
    """Serve the service worker from the site root."""
    path = os.path.join(app.static_folder, "sw.js")
    return send_file(path, mimetype="application/javascript")

@app.get("/manifest.webmanifest")
def webmanifest():
    """Serve the web app manifest from the site root."""
    path = os.path.join(app.static_folder, "manifest.webmanifest")
    return send_file(path, mimetype="application/manifest+json")

@app.post("/settings")
def update_settings():
    ensure_files()
    data = {
        "emergency_text": request.form.get("emergency_text", ""),
        "emergency_contact_label": request.form.get("emergency_contact_label", ""),
        "emergency_contact_value": request.form.get("emergency_contact_value", ""),
        "default_support_flavor": request.form.get("default_support_flavor", "secular"),
    }
    save_json(SETTINGS_PATH, data)
    flash("Settings saved.", "ok")
    return redirect(url_for("index"))

# ---------- Admin mini-API ----------
@app.route("/add_wisdom", methods=["POST"], endpoint="add_wisdom")
def add_wisdom():
    ensure_files()
    flavor = (request.form.get("wisdom_flavor", "secular") or "secular").strip()
    text = (request.form.get("wisdom_text", "") or "").strip()
    author = (request.form.get("wisdom_author", "") or "Unknown").strip()
    if not text:
        flash("Please provide wisdom text.", "error")
        return redirect(url_for("index"))
    _append_to_map_list(WISDOM_PATH, flavor, {"text": text, "author": author})
    flash("Wisdom quote added.", "ok")
    return redirect(url_for("index"))

@app.route("/add_scripture", methods=["POST"], endpoint="add_scripture")
def add_scripture():
    ensure_files()
    flavor = (request.form.get("scripture_flavor", "secular") or "secular").strip()
    text = (request.form.get("scripture_text", "") or "").strip()
    if not text:
        flash("Please provide scripture text.", "error")
        return redirect(url_for("index"))
    _append_to_map_list(SCRIPTURES_PATH, flavor, text)
    flash("Scripture added.", "ok")
    return redirect(url_for("index"))

# Helper: list all registered routes
@app.get("/_routes")
def list_routes():
    return jsonify(sorted([r.endpoint for r in app.url_map.iter_rules()]))

# ---------- Main ----------
if __name__ == "__main__":
    ensure_files()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5050")))
    parser.add_argument("--host", type=str, default=os.getenv("HOST", "0.0.0.0"))
    args = parser.parse_args()
    app.run(debug=True, use_reloader=False, host=args.host, port=args.port)
