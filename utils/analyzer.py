from __future__ import annotations
import re
from typing import Dict, Tuple, List, Union

# --- Lexicons (demo) ---
POSITIVE = {
    "calm","peace","relief","grateful","gratitude","hope","okay","better","progress",
    "rest","proud","joy","happy","content","support","breathe","breathing"
}
NEGATIVE = {
    "sad","down","tired","exhausted","anxious","anxiety","panic","angry","mad","lonely",
    "burnout","burned","stress","stressed","worry","worried","overwhelmed","depressed",
    "cry","crying","fear","scared","hopeless","worthless"
}

# Risk/crisis phrases (non-exhaustive)
CRISIS = {
    "hopeless","no way out","end it","suicide","kill myself","want to die","self harm","hurt myself",
    "bunuh diri","menyakiti diri","putus asa","tidak ada harapan"
}

STRESS = {"stress","stressed","overwhelm","overwhelmed","deadline","burnout","exhausted"}
SADNESS = {"sad","down","blue","cry","crying","empty","hopeless","worthless","depressed"}
ANGER = {"angry","mad","furious","irritated","annoyed"}
LONELY = {"lonely","alone","isolated","left out"}
ANXIETY = {"anxious","anxiety","panic","scared","fear","khawatir","cemas"}

def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z']+|[\u00C0-\u024F\u1E00-\u1EFF]+", text.lower())

def _nice_number(x: float) -> Union[int, float]:
    """
    Clamp to [-1, 1], round to 2 decimals, and return an int if it's an exact integer.
    This ensures values like -1.00 -> -1, 0.00 -> 0, 0.50 -> 0.5.
    """
    # Clamp
    x = max(-1.0, min(1.0, float(x)))
    # Round to 2 decimals
    r2 = round(x, 2)
    # If it's an exact integer after rounding, return int
    if abs(r2 - int(r2)) < 1e-12:
        return int(r2)
    return r2

def analyze_text(text: str) -> Dict:
    toks = tokenize(text)
    pos = sum(1 for t in toks if t in POSITIVE)
    neg = sum(1 for t in toks if t in NEGATIVE)

    # Mood score in [-1, 1] with clean formatting (no trailing zeros like -1.00)
    if pos + neg > 0:
        raw = (pos - neg) / (pos + neg)
        mood_score = _nice_number(raw)
    else:
        mood_score = 0  # exact int zero

    # Signals
    joined = " ".join(toks)
    signals = {
        "stress": any(t in STRESS for t in toks),
        "sadness": any(t in SADNESS for t in toks),
        "anger": any(t in ANGER for t in toks),
        "lonely": any(t in LONELY for t in toks),
        "anxiety": any(t in ANXIETY for t in toks),
        "crisis": any(phrase in joined for phrase in CRISIS),
    }
    return {
        "tokens": toks,
        "positive": pos,
        "negative": neg,
        "mood_score": mood_score,
        "signals": signals
    }

def _cbt_cognitive_diffusion() -> str:
    return "ACT — Cognitive defusion: Notice the thought, name it (e.g., ‘I’m having the thought that…’), and watch it pass like a cloud for 60 seconds."

def _cbt_reframe() -> str:
    return "CBT — Reframe: Write the thought, then list 1 evidence for and 2 pieces of evidence against it. Finish with a balanced alternative thought."

def _dbt_stop() -> str:
    return "DBT — STOP skill: Stop. Take a step back. Observe. Proceed mindfully. Give yourself 1 minute before acting or replying."

def _ground_54321() -> str:
    return "Grounding — 5-4-3-2-1: Name 5 things you see, 4 you feel, 3 you hear, 2 you smell, 1 you taste. Do it slowly."

def _behavioral_activation() -> str:
    return "Behavioral activation: Do one tiny valued action now (stand up, drink water, open a window, put one cup away)."

def _paced_breathing() -> str:
    return "Breathing — 4-6: Inhale 4s through the nose, exhale 6s through the mouth. Repeat 6 rounds."

def _self_compassion() -> str:
    return "Self-compassion: Place a hand on your chest and say, ‘This is hard, and I’m doing my best. May I be kind to myself right now.’"

def _reach_out() -> str:
    return "Connection: Message one trusted person ‘Hey, could use a quick hello today.’"

def _urge_surfing() -> str:
    return "Urge surfing: If a strong urge appears, observe it like a wave—rise, peak, fall—without acting for 10 minutes."

def crisis_message() -> List[str]:
    return [
        "⚠️ If you are in immediate danger or thinking about harming yourself: contact local emergency services or a trusted person now.",
        "You are not alone. Please reach out to someone you trust.",
        _ground_54321()
    ]

def micro_interventions(analysis: Dict) -> List[str]:
    """Return up to 4 brief, evidence-informed suggestions.
    These are general self-care skills from CBT/DBT/ACT/grounding, not medical advice."""
    sig = analysis.get("signals", {})
    outs: List[str] = []

    if sig.get("crisis"):
        return crisis_message()

    # Always offer paced breathing for down-regulation
    outs.append(_paced_breathing())

    if sig.get("anxiety"):
        outs.append(_ground_54321())
        outs.append(_cbt_cognitive_diffusion())

    if sig.get("stress"):
        outs.append(_dbt_stop())
        outs.append(_behavioral_activation())

    if sig.get("sadness"):
        outs.append(_behavioral_activation())
        outs.append(_self_compassion())

    if sig.get("anger"):
        outs.append("Take space for 2 minutes; unclench your jaw and hands.")
        outs.append(_dbt_stop())

    if sig.get("lonely"):
        outs.append(_reach_out())

    # Fallbacks to ensure we return something practical
    if len(outs) < 3:
        outs.append(_behavioral_activation())
        outs.append(_self_compassion())

    # Keep unique and concise
    uniq = []
    for s in outs:
        if s not in uniq:
            uniq.append(s)
    return uniq[:4]
