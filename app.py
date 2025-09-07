from __future__ import annotations
import json
import os
import csv
import argparse
import random
from io import StringIO, BytesIO
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, flash, send_file, make_response
)
from flask_wtf.csrf import CSRFProtect, CSRFError

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

# ---------- Friendly flavor labels ----------
FLAVOR_LABELS: Dict[str, str] = {
    "secular": "Supportive (Secular)",
    "cultural_nusantara": "Nusantara Wisdom",
    "islam": "Spiritual (Islam)",
    "christian": "Spiritual (Christian)",
    "hindu": "Spiritual (Hindu)",
    "buddhist": "Spiritual (Buddhist)",
}

app = Flask(__name__)

# ===== Security / session =====
app.secret_key = os.getenv("SECRET_KEY", "dev-key-change-me")
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["WTF_CSRF_ENABLED"] = os.getenv("WTF_CSRF_ENABLED", "1") not in ("0", "false", "False")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
csrf = CSRFProtect(app)


# ---------- Helpers ----------
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
    if not os.path.exists(ENTRIES_PATH):
        save_json(ENTRIES_PATH, [])
    if not os.path.exists(SETTINGS_PATH):
        save_json(SETTINGS_PATH, {
            "emergency_text": "If you are in immediate danger, contact local emergency services.",
            "emergency_contact_label": "Family",
            "emergency_contact_value": "",
            "default_support_flavor": "secular",
        })


def _append_to_map_list(path: str, flavor: str, item):
    m = load_json(path, {})
    if flavor not in m or not isinstance(m[flavor], list):
        m[flavor] = []
    m[flavor].append(item)
    save_json(path, m)


def _last_entry() -> Optional[Dict]:
    entries: List[Dict] = load_json(ENTRIES_PATH, [])
    return entries[-1] if entries else None


def _parse_date_yyyy_mm_dd(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _parse_entry_ts(e: Dict) -> Optional[datetime]:
    ts = e.get("timestamp")
    if not ts:
        return None
    try:
        ts = ts.replace(" ", "T")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _filter_entries(entries: List[Dict], flavor: Optional[str], start: Optional[str], end: Optional[str]) -> List[Dict]:
    """Filter by flavor and inclusive date range [start, end]."""
    f = (flavor or "").strip().lower()
    start_dt = _parse_date_yyyy_mm_dd(start)
    end_dt = _parse_date_yyyy_mm_dd(end)
    if end_dt:
        end_dt = end_dt + timedelta(days=1) - timedelta(seconds=1)

    out = []
    for e in entries:
        if f and f != "all" and e.get("flavor") != f:
            continue
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
    dt = _parse_entry_ts(e)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (e.get("timestamp", "") or "")


# (optional) small helper to craft suggestions; falls back to micro_interventions
def _craft_support_messages(text: str, analysis: Dict, mood: float) -> List[str]:
    base = micro_interventions(analysis) or []
    extras = [
        "Take 6 slow breaths: inhale 4s, exhale 6s.",
        "Try 5-4-3-2-1 grounding.",
        "Send one honest message to someone you trust.",
    ]
    seen = set()
    out = []
    for s in base + extras:
        k = (s or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(s)
    return out[:3]


# ---------- Global template context ----------
@app.context_processor
def inject_globals():
    return {
        "flavor_labels": FLAVOR_LABELS,
        "flavor_label": lambda key: FLAVOR_LABELS.get(key, key),
    }


# ---------- CSRF handler ----------
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("Your form session expired or the CSRF token was missing. Please try again.", "error")
    return redirect(url_for("index")), 302


@app.after_request
def add_no_store(resp):
    """Avoid cached HTML serving stale CSRF tokens."""
    content_type = resp.headers.get("Content-Type", "")
    if content_type.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# ---------- Routes ----------
@app.route("/")
def index():
    ensure_files()
    settings = load_json(SETTINGS_PATH, {})
    prompts = load_json(PROMPTS_PATH, [])
    prompt_text = random.choice(prompts) if isinstance(prompts, list) and prompts else "How are you feeling right now?"
    return render_template("index.html", app_name=APP_NAME, settings=settings, prompt=prompt_text)


@app.get("/journal")
def journal_get_redirect():
    return redirect(url_for("index"))


@app.post("/journal")
def journal():
    ensure_files()
    text = (request.form.get("entry_text") or "").strip()
    try:
        mood = float(request.form.get("mood", "0"))
    except ValueError:
        mood = 0.0
    flavor = request.form.get("flavor", "secular")

    if not text:
        flash("Please write a few words about how you feel.", "error")
        return redirect(url_for("index"))

    analysis = analyze_text(text)
    support = _craft_support_messages(text, analysis, mood)

    # optional content picks (quotes/scriptures/wisdom)
    quotes_map = load_json(QUOTES_PATH, {})
    scriptures_map = load_json(SCRIPTURES_PATH, {})
    wisdom_map = load_json(WISDOM_PATH, {})

    last = _last_entry()

    spiritual_candidates = scriptures_map.get(flavor) or scriptures_map.get("secular") or []
    last_spiritual = last.get("spiritual") if last else None
    spiritual = random.choice(spiritual_candidates) if spiritual_candidates else None
    if last_spiritual and spiritual_candidates and len(spiritual_candidates) > 1:
        pool = [s for s in spiritual_candidates if s != last_spiritual]
        spiritual = random.choice(pool)

    quote_candidates = quotes_map.get(flavor) or quotes_map.get("secular") or ["You are doing the best you can."]
    last_quote = last.get("quote") if last else None
    quote = random.choice(quote_candidates)
    if last_quote and len(quote_candidates) > 1:
        pool = [q for q in quote_candidates if q != last_quote]
        quote = random.choice(pool)

    wlist = wisdom_map.get(flavor) or wisdom_map.get("secular") or []
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
    """Render entries page with optional filters."""
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])
    settings = load_json(SETTINGS_PATH, {})

    flavor = request.args.get("flavor", default="", type=str)
    start = request.args.get("start", default="", type=str)
    end = request.args.get("end", default="", type=str)

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


# ---------- Delete entry (explicit endpoint name) ----------
@app.route("/entries/delete", methods=["POST"], endpoint="delete_entry")
def delete_entry():
    """
    Delete one journal entry identified by its timestamp string (exact match).
    Expects form field: ts = 'YYYY-MM-DDTHH:MM:SS'
    """
    ensure_files()
    ts = (request.form.get("ts") or "").strip()
    if not ts:
        flash("Missing entry identifier.", "error")
        return redirect(url_for("entries"))

    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])
    kept = [e for e in all_entries if (e.get("timestamp") or "").strip() != ts]

    if len(kept) < len(all_entries):
        save_json(ENTRIES_PATH, kept)
        flash("Entry deleted.", "ok")
    else:
        flash("Entry not found.", "error")

    return redirect(url_for("entries"))


# ---------- Entries API (used by chart) ----------
@app.get("/api/entries")
def api_entries():
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])

    flavor = request.args.get("flavor", default="", type=str)
    start = request.args.get("start", default="", type=str)
    end = request.args.get("end", default="", type=str)
    limit = request.args.get("limit", type=int)

    filtered = _filter_entries(all_entries, flavor, start, end)
    if isinstance(limit, int) and limit > 0:
        filtered = filtered[-limit:]

    resp = make_response(json.dumps(filtered, ensure_ascii=False))
    resp.mimetype = "application/json"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ---------- Export pages & files ----------
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
    ensure_files()
    entries = load_json(ENTRIES_PATH, [])
    fieldnames = ["timestamp", "mood_slider", "flavor", "mood_score", "positive", "negative", "text"]

    def row(e):
        a = e.get("analysis", {}) or {}
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
    return app.response_class(response=sio.getvalue(), mimetype="text/csv")


@app.get("/export/pdf")
def export_pdf():
    ensure_files()
    all_entries: List[Dict] = load_json(ENTRIES_PATH, [])
    flavor = request.args.get("flavor", default="", type=str)
    start = request.args.get("start", default="", type=str)
    end = request.args.get("end", default="", type=str)

    entries = _filter_entries(all_entries, flavor, start, end)
    entries.sort(key=lambda e: (_parse_entry_ts(e) or datetime.min))

    buffer = BytesIO()
    page_w, page_h = A4
    margin = 18 * mm
    c = pdfcanvas.Canvas(buffer, pagesize=A4)

    title = f"{APP_NAME} — Entries Export"
    subtitle_parts = []
    if flavor:
        subtitle_parts.append(f"Flavor: {FLAVOR_LABELS.get(flavor, flavor)}")
    if start:
        subtitle_parts.append(f"Start: {start}")
    if end:
        subtitle_parts.append(f"End: {end}")
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else "All entries"

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
        nonlocal y
        min_y = margin + 20
        if y - (lines_needed * line_height) < min_y:
            c.showPage()
            y = page_h - margin
            draw_header()

    def wrap(text: str, max_w: float, font="Helvetica", size=10) -> List[str]:
        if not text:
            return []
        words = text.replace("\r", "").split()
        out: List[str] = []
        cur = ""
        for w in words:
            cand = w if not cur else (cur + " " + w)
            if c.stringWidth(cand, font, size) <= max_w:
                cur = cand
            else:
                if cur:
                    out.append(cur)
                if c.stringWidth(w, font, size) > max_w:
                    buf = ""
                    for ch in w:
                        if c.stringWidth(buf + ch, font, size) <= max_w:
                            buf += ch
                        else:
                            if buf:
                                out.append(buf)
                            buf = ch
                    cur = buf
                else:
                    cur = w
        if cur:
            out.append(cur)
        return out

    draw_header()

    if not entries:
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(margin, y, "No entries available for the selected filters.")
        c.showPage()
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name="entries.pdf")

    max_w = page_w - 2 * margin
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

        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, f"{ts}   •   {flavor_label}   •   Mood: {mood_slider}")
        y -= 13

        c.setFont("Helvetica", 10)
        c.drawString(margin, y, f"Mood score: {mood_score}   (+{pos} / -{neg})")
        y -= 12

        if text:
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(margin, y, "Your words:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in wrap(text, max_w):
                c.drawString(margin, y, line)
                y -= 12

        def block(label: str, content: Optional[str], italic=False):
            nonlocal y
            if not content:
                return
            c.setFont("Helvetica-Oblique", 10 if italic else 10)
            c.drawString(margin, y, f"{label}:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in wrap(content if label != "Wisdom" else f"“{content}”", max_w):
                c.drawString(margin, y, line)
                y -= 12

        if quote:
            block("Supportive note", quote, italic=True)
        if spiritual:
            block("Spiritual note", spiritual, italic=True)
        if wisdom_text:
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(margin, y, "Wisdom:")
            y -= 12
            c.setFont("Helvetica", 10)
            for line in wrap(f"“{wisdom_text}”", max_w):
                c.drawString(margin, y, line)
                y -= 12
            if wisdom_author:
                c.setFont("Helvetica-Oblique", 10)
                c.drawString(margin, y, f"— {wisdom_author}")
                y -= 12

        y -= 6
        c.setLineWidth(0.3)
        c.setDash(1, 2)
        c.line(margin, y, page_w - margin, y)
        c.setDash()
        y -= 10

    c.showPage()
    c.save()
    buffer.seek(0)

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
    path = os.path.join(app.static_folder, "sw.js")
    return send_file(path, mimetype="application/javascript")


@app.get("/manifest.webmanifest")
def webmanifest():
    path = os.path.join(app.static_folder, "manifest.webmanifest")
    return send_file(path, mimetype="application/manifest+json")


# ---------- Settings / Admin ----------
@app.post("/settings", endpoint="update_settings")
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


# Utilities
@app.get("/_routes")
def list_routes():
    return jsonify(sorted([r.endpoint for r in app.url_map.iter_rules()]))


@app.get("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat(timespec="seconds")})


# ---------- Main ----------
if __name__ == "__main__":
    ensure_files()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5050")))
    parser.add_argument("--host", type=str, default=os.getenv("HOST", "0.0.0.0"))
    args = parser.parse_args()
    app.run(debug=True, use_reloader=False, host=args.host, port=args.port)
